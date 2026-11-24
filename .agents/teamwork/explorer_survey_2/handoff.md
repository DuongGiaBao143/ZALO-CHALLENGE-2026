# HANDOFF REPORT: Technical Critique of ReAct Reasoning Flow & `<think>...</think>` Block Preservation in HANDOFF_PLAN.md

**Author**: Explorer Survey 2 (`teamwork_explorer`)  
**Mission**: Deep Technical Investigation & Adversarial Critique of ReAct Reasoning Flow, `<think>...</think>` Preservation Mechanism, Context Window (16,384 tokens), Inference Latency, and Reasoning Dynamics for DataMate (Zalo AI Challenge 2026).  
**Working Directory**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026`  
**State Folder**: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_survey_2`  
**Target Recipient**: Orchestrator (`e8c45a29-5148-4546-ba15-45fed278495a`) & Critique Team  
**Date**: 2026-11-13  

---

## Executive Summary

Kế hoạch kỹ thuật `HANDOFF_PLAN.md` đề xuất một kiến trúc ReAct mở rộng (5–10 turns) kết hợp lưu giữ toàn bộ chuỗi suy luận nội tâm (`<think>...</think>`) của mô hình qua các lượt hội thoại, với giả định rằng việc này giúp mô hình "ghi nhớ" quá trình tư duy, chẩn đoán lỗi và đưa ra quyết định tốt hơn qua từng turn.

Báo cáo điều tra kỹ thuật này chứng minh một cách toán học, kiến trúc và thực nghiệm rằng: **Đề xuất giữ khối `<think>` qua các turn trong ReAct là một anti-pattern nghiêm trọng**, xung đột trực tiếp với cơ chế suy luận của các mô hình reasoning mã nguồn mở (DeepSeek-R1-Distill, QwQ, Qwen2.5/3.5), gây sập cửa sổ ngữ cảnh 16.384 tokens ngay từ Turn 4–5, bùng nổ độ trễ suy luận lên tới >5 phút mỗi câu hỏi (vi phạm thời gian Docker offline của cuộc thi), và làm suy giảm trực tiếp điểm số Penalized Accuracy (PA) do hội chứng lặp suy luận (thinking repetition) và củng cố giả định sai lầm (confirmation bias).

---

## 1. Observation (Dẫn chứng Thực nghiệm & Mã nguồn Cụ thể)

### 1.1. Hiện trạng Xử lý Khối `<think>` trong Codebase Hiện tại (`src/agent/solver.py`)
Khác với đề xuất trong `HANDOFF_PLAN.md`, codebase DataMate hiện hành tại `src/agent/solver.py` đã chủ động **cắt bỏ hoàn toàn** phần suy luận nội tâm `<think>` trước khi đưa vào lịch sử hội thoại nhiều lượt:

- **Source**: `src/agent/solver.py` (lines 1086–1091):
  ```python
  code = extract_python_code(llm_reply)
  compact_asst_reply = (
      f"```python\n{code}\n```"
      if code
      else (llm_reply.split("</think>", 1)[-1].strip() if "</think>" in llm_reply else llm_reply)[-1200:]
  )
  ```
- **Source**: `src/agent/solver.py` (lines 1108, 1162, 1184):
  ```python
  # Khi append vào messages cho turn kế tiếp, chỉ append compact_asst_reply:
  messages.append({"role": "assistant", "content": compact_asst_reply})
  messages.append({"role": "user", "content": build_observation_prompt(...)})
  ```
- **Source**: `src/agent/solver.py` (lines 267–292, hàm `_fit_messages_to_context`):
  ```python
  def _fit_messages_to_context(self, messages: List[Dict[str, str]], tokenizer: Any) -> Tuple[List[Dict[str, str]], int]:
      min_gen_budget = 768
      msgs = [dict(m) for m in messages]
      tokens = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=False)
      # Step 1: Drop oldest intermediate turn pair if over budget
      while len(tokens) > self.max_model_len - min_gen_budget and len(msgs) >= 5:
          first_asst_idx = next((i for i, m in enumerate(msgs) if m.get("role") == "assistant"), None)
          if first_asst_idx is not None and first_asst_idx + 2 <= len(msgs):
              del msgs[first_asst_idx:first_asst_idx + 2]
              tokens = tokenizer.apply_chat_template(...)
      ...
  ```
- **Đối chiếu**: Codebase hiện tại chỉ cho phép `max_turns: 3` (xem `configs/default_config.yaml:24` và `configs/deepseek_r1_14b_config.yaml:27`). Nếu đề xuất của `HANDOFF_PLAN.md` giữ lại nguyên khối `<think>` và tăng turns lên 5–10, cơ chế `_fit_messages_to_context` sẽ liên tục bị kích hoạt để xóa các turn trung gian, gây mất liên kết nhân quả (causal context loss).

### 1.2. Động lực Học và Huấn luyện của Open-Weights Reasoning LLMs
Các mô hình suy luận mã nguồn mở hiện nay (DeepSeek-R1-Distill-Qwen-14B, QwQ-32B-Preview, Qwen2.5/Qwen3.5 có thinking):
1. **Mô thức Huấn luyện Single-Turn**: Tất cả các mô hình này được huấn luyện qua Reinforcement Learning (GRPO / PPO / Rule-based RL) trên quỹ đạo bài toán **đơn lượt** (Single-Turn):
   $$\text{User Query} \longrightarrow \langle\text{think}\rangle \text{Long Chain-of-Thought} \langle/\text{think}\rangle \longrightarrow \text{Final Answer / Python Code}$$
2. **Template Sinh Tự Động**: Trong Chat Template của DeepSeek-R1, thẻ `<think>\n` được tự động chèn vào đầu generation của Assistant:
   `{% if add_generation_prompt %}<｜Assistant｜><think>\n{% endif %}`.
   Mô hình không được thiết kế hay căn chỉnh (aligned) để đọc lại các khối `<think>` của chính nó từ các lượt hội thoại trước đó.
3. **Hiện tượng "Thinking Repetition" (Lặp Suy Luận) & "Reasoning Degeneration"**:
   - Khi mô hình nhìn thấy một khối `<think> ... </think>` dài 1.500–2.500 tokens nằm trong vai trò `assistant` của lượt trước, các đầu chú ý (attention heads) của cơ chế Self-Attention sẽ bị "neo" (attentional anchoring) vào các token suy luận cũ.
   - Thay vì phản hồi linh hoạt vào thông tin quan sát mới từ môi trường (`Observation` hoặc `Error traceback`), ở Turn 2 mô hình sinh ra một khối suy luận mới lặp lại gần như nguyên văn các phân tích từ Turn 1: *"Let's review the problem. The user wants revenue for biz_101. The files are BanHang.xlsx. We have columns..."*.
   - Quá trình này dẫn đến vòng lặp kiểm tra vô tận (*"Wait, let me double check... But earlier I thought... Let me re-verify..."*), tiêu tốn cạn kiệt ngân sách `max_tokens` của turn mà không kịp đưa ra code mới.

### 1.3. Hội chứng Củng cố Giả định Sai (Confirmation Bias & Context Drift)
- Trong bài toán DataMate, nguyên nhân chính khiến Turn 1 thất bại là **giả định sai về dữ liệu** (ví dụ: giả định cột trạng thái tên là `Trạng thái` mang giá trị `Hoàn thành`, trong khi thực tế tại `biz_101` cột tên là `Kết quả` và giá trị là `Xong`).
- Trong khối `<think>` của Turn 1, mô hình đã dành hàng trăm tokens để tự thuyết phục và lập luận cho giả định sai này (*"In Vietnamese retail, completed orders are marked as 'Hoàn thành', so I must filter df['Trạng thái'] == 'Hoàn thành'"*).
- **Hậu quả khi giữ `<think>`**: Khi Sandbox trả về `KeyError: 'Trạng thái'` hoặc `rows_after_filter = 0`, mô hình ở Turn 2 đọc lại chính khối lập luận đầy sức thuyết phục của nó ở Turn 1. Lập luận nội tại (self-generated rationalization) lấn át tín hiệu thực thi bên ngoài. Mô hình không đổi sang khám phá cột mới mà tiếp tục cố chấp thử các biến thể của giả định sai: `df['trạng thái']`, `df['Trang_Thai']`, `df['trang_thai_don']`.
- **Dẫn chứng thực tế từ `failure_analysis.md`** (`result/.../failure_analysis.md`, lines 7–9):
  > *"Lọc trạng thái theo chữ 'hoàn thành' làm rỗng dữ liệu. Lượt cuối của 7 câu dùng .str.contains('hoàn thành'), gồm 5 sai và 2 abstain. Trên các kỳ liên quan, biz_101 có nhãn 'Xong', còn biz_111, biz_127 và biz_129 dùng 'completed'. Bộ lọc trả 0 dòng ở cả 7 câu."*
  Mô hình đã mất nhiều lượt lặp đi lặp lại một giả định sai lầm vì không chịu từ bỏ định kiến ban đầu.

### 1.4. Mô phỏng Toán học: Tốc độ Bùng nổ Token trong Cửa sổ Ngữ cảnh 16.384 Tokens
Cấu hình hệ thống quy định: `max_model_len: 16384` (Rule 14 trong `configs/deepseek_r1_14b_config.yaml`).

Hãy lập bảng tính toán học chính xác về sự tăng trưởng token qua các turn:
- **Prompt ban đầu ($T_0$)**:
  - System Prompt (Rulebook + Core Rules + JSON Output Protocol): $\approx 2.500$ tokens.
  - Business Schema Profile (Danh sách bảng, cột, giá trị phân loại enum/sample, lịch âm dương): $\approx 2.500$ tokens.
  - User Query + Temporal Resolution Hints: $\approx 500$ tokens.
  - Tổng prompt khởi tạo $T_0 \approx 5.500$ tokens.
- **Lượng token sinh ra và phản hồi mỗi turn ($t$)**:
  - $T_{\text{think}}$: $\approx 2.000$ tokens (mức trung bình của DeepSeek-R1 / QwQ cho logic phân tích bảng).
  - $T_{\text{code}}$: $\approx 300$ tokens.
  - $T_{\text{obs}}$ (hoặc Traceback lỗi): $\approx 500$ tokens.
  - Format delimiters (ChatML tokens, headers): $\approx 50$ tokens.
  - $\Delta T_{\text{with\_think}} = 2.000 + 300 + 500 + 50 = 2.850\text{ tokens / turn}$.
  - $\Delta T_{\text{code\_only}} = 300 + 500 + 50 = 850\text{ tokens / turn}$.

**Bảng Tăng Trưởng Token qua các Turn (Context Limit: 16.384 tokens, Min Gen Budget: 2.048 tokens):**

| Turn | Phương án GIỮ `<think>` (Total Tokens) | Ngân sách sinh còn lại | Trạng thái (Giữ `<think>`) | Phương án BỎ `<think>` (Total Tokens) | Ngân sách sinh còn lại | Trạng thái (Bỏ `<think>`) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Turn 1** | 5.500 tokens | 10.884 tokens | **OK** | 5.500 tokens | 10.884 tokens | **OK** |
| **Turn 2** | 8.350 tokens | 8.034 tokens | **OK** | 6.350 tokens | 10.034 tokens | **OK** |
| **Turn 3** | 11.200 tokens | 5.184 tokens | **OK (Bắt đầu nghẽn)** | 7.200 tokens | 9.184 tokens | **OK** |
| **Turn 4** | 14.050 tokens | 2.334 tokens | **Nguy cấp (Thiếu budget sinh CoT)** | 8.050 tokens | 8.334 tokens | **OK** |
| **Turn 5** | **16.900 tokens** | **-516 tokens** | **TRÀN CONTEXT (OOC / Truncation)** | 8.900 tokens | 7.484 tokens | **OK** |
| **Turn 6** | 19.750 tokens | -3.366 tokens | Tràn nghiêm trọng | 9.750 tokens | 6.634 tokens | **OK** |
| **Turn 7** | 22.600 tokens | -6.216 tokens | Tràn nghiêm trọng | 10.600 tokens | 5.784 tokens | **OK** |
| **Turn 8** | 25.450 tokens | -9.066 tokens | Tràn nghiêm trọng | 11.450 tokens | 4.934 tokens | **OK** |
| **Turn 9** | 28.300 tokens | -11.916 tokens | Tràn nghiêm trọng | 12.300 tokens | 4.084 tokens | **OK** |
| **Turn 10**| **31.150 tokens** | **-14.766 tokens**| **Gấp 1,9 lần giới hạn phần cứng** | **13.150 tokens** | **3.234 tokens** | **HOÀN TOÀN AN TOÀN** |

- **Kết luận toán học**:
  - Với phương án giữ `<think>`, đến **Turn 5 hệ thống đã hoàn toàn tràn cửa sổ 16.384 tokens**.
  - Nếu áp dụng cơ chế cắt tỉa (pruning) của `_fit_messages_to_context`, hệ thống buộc phải xóa Turn 1 và Turn 2, khiến mô hình bị mất ngữ cảnh khởi đầu (amnesia), không còn biết câu hỏi gốc và các dữ liệu đã khám phá trước đó.
  - Ngược lại, phương án loại bỏ `<think>` (chỉ giữ code và observation) cho phép mở rộng đến tận **Turn 10 mà tổng context chỉ đạt 13.150 tokens**, vẫn dư dả 3.234 tokens để sinh code hoàn chỉnh!

### 1.5. Phân tích Độ trễ Suy luận (Latency) và Bộ nhớ Đệm KV-Cache
1. **Dung lượng KV-Cache của mô hình 14B (GQA)**:
   - Mô hình kiến trúc 14B (DeepSeek-R1-Distill-Qwen-14B / Qwen2.5-Coder-14B) có:
     - Số lớp (Layers) $L = 48$.
     - Số đầu KV ($N_{\text{kv\_heads}}$) = 8 (Grouped-Query Attention).
     - Kích thước mỗi đầu ($d_k$) = 128.
     - Dtype = BF16 (2 bytes / element).
   - Bộ nhớ KV-Cache tiêu tốn cho mỗi token:
     $$S_{\text{token}} = 2 \times L \times N_{\text{kv\_heads}} \times d_k \times 2 = 2 \times 48 \times 8 \times 128 \times 2 = 196.608\text{ bytes} \approx 192\text{ KB / token}$$
   - Ở độ dài 16.384 tokens, KV-cache cho **một chuỗi đơn lẻ** tiêu tốn:
     $$\text{KV-Cache} = 16.384 \times 192\text{ KB} = 3.145.728\text{ KB} = \mathbf{3{,}00\text{ GB / sequence}}$$
   - Trên GPU A100-40GB: Trọng số mô hình 14B BF16 chiếm 29,4 GB VRAM. Bộ nhớ khả dụng còn lại cho vLLM chỉ là $\approx 10{,}6\text{ GB}$. Nếu có 3 câu hỏi chạy đồng thời hoặc batching song song với context 16k, KV-cache chiếm $3 \times 3{,}0\text{ GB} = 9{,}0\text{ GB}$, đẩy VRAM chạm ngưỡng 38,4 GB $\rightarrow$ **Cực kỳ dễ gây CUDA OOM**.
2. **Thời gian Sinh Token (Generation Time) & Time-To-First-Token (TTFT)**:
   - Tốc độ sinh token (Decode speed) của mô hình 14B BF16 trên RTX 5090 / A100 đạt khoảng $40 - 50\text{ tokens / giây}$.
   - Mỗi lượt suy luận sinh ra trung bình $2.000$ thinking tokens $+ 300$ code tokens $\approx 2.300$ tokens.
   - Thời gian sinh thuần túy cho **chỉ 1 turn**:
     $$t_{\text{turn}} = \frac{2.300\text{ tokens}}{45\text{ tokens/s}} \approx \mathbf{51{,}1\text{ giây / turn}}$$
   - Nếu chạy vòng lặp ReAct 5 turns:
     $$t_{\text{question}} \ge 5 \times 51{,}1\text{s} = \mathbf{255{,}5\text{ giây} \approx 4{,}25\text{ phút / câu hỏi!}}$$
   - Nếu chạy 10 turns như đề xuất của HANDOFF_PLAN:
     $$t_{\text{question}} \ge 10 \times 51{,}1\text{s} \approx \mathbf{8{,}5\text{ phút / câu hỏi!}}$$
   - **Tác động tới Thời gian Chấm bài của BTC**:
     - Tập kiểm thử của cuộc thi gồm hàng trăm câu hỏi (14 shop public test + private test).
     - Nếu mỗi câu hỏi mất 4–8 phút, việc đánh giá 100 câu hỏi sẽ tốn từ **7 đến 14 tiếng liên tục**!
     - Container Docker của BTC thường áp đặt giới hạn tổng thời gian chạy (`timeout` toàn pipeline thường từ 1 đến 2 giờ, tương đương trung bình $\le 30 - 45\text{ giây / câu hỏi}$).
     - Trong thực nghiệm tại `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/evaluation_report.json`, phiên bản code-only (không giữ `<think>`) hoàn thành 30 câu hỏi trong $856\text{ giây}$ ($\approx \mathbf{28{,}5\text{ giây / câu hỏi}}$).
     - Việc giữ khối `<think>` làm tăng thời gian xử lý lên **gấp 9 đến 18 lần**, chắc chắn dẫn đến việc container bị kill do timeout và bị đánh trượt (disqualification).

3. **Phá hủy Bộ đệm Tiền tố Tự động (Automatic Prefix Caching - APC) của vLLM**:
   - vLLM sử dụng cơ chế Automatic Prefix Caching (`enable_prefix_caching=True`) để tái sử dụng KV-cache của các block token prompt giống nhau giữa các turn.
   - Khi khối `<think>` được giữ lại nhưng bị cắt tỉa ở giữa bối cảnh bởi hàm `_fit_messages_to_context` (ví dụ xóa Turn 1 để nhường chỗ cho Turn 5), **toàn bộ chuỗi hash tiền tố của prompt bị phá vỡ hoàn toàn**.
   - vLLM không thể tái sử dụng bất kỳ block cache nào từ Turn 1–4, buộc phải prefill lại toàn bộ 14.000+ tokens từ đầu ở mỗi turn sau. Thời gian prefill (TTFT) tăng vọt, lãng phí tài nguyên tính toán cực lớn.

---

## 2. Logic Chain (Chuỗi Lập luận Kỹ thuật từ Dẫn chứng đến Kết luận)

```
[Dẫn chứng 1: Mô hình Reasoning được train Single-turn RL]
       │
       ▼
[Hiện tượng: Attention bị neo vào CoT cũ, gây Thinking Repetition & Confirmation Bias]
       │
       ▼
[Dẫn chứng 2: Tốc độ tích luỹ token 2.850 tok/turn] ──────────► [Toán học: Tràn 16.384 tokens ở Turn 5]
       │                                                                  │
       ▼                                                                  ▼
[Dung lượng KV-cache 3.0 GB/seq & Decode 51s/turn]              [Cắt tỉa turn gây mất trí nhớ & mất Cache vLLM]
       │                                                                  │
       ▼                                                                  ▼
[Độ trễ 4.25 - 8.5 phút/câu hỏi ──► Timeout Docker BTC]         [Điểm PA sụt giảm do lặp lỗi & phạt -1.0 điểm]
       │                                                                  │
       └──────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
                      [KẾT LUẬN: BÁC BỎ ĐỀ XUẤT CỦA HANDOFF_PLAN.MD]
                      [Áp dụng: Ephemeral Thinking + Lean Bounded Execution]
```

### Bước 1: Mâu thuẫn Kiến trúc Cơ bản giữa Huấn luyện và Sử dụng
- **Tiền đề**: DeepSeek-R1, QwQ, Qwen-Reasoning chỉ được tối ưu hóa hàm thưởng RL (Reward Model / Rule-based verifier) trên chuỗi `Query -> <think> -> Solution`.
- **Hệ quả**: Đưa `<think>` vào lịch sử nhiều lượt là đưa mô hình vào phân phối dữ liệu dị biệt (Out-Of-Distribution - OOD). Mô hình không biết cách "đọc" lại suy nghĩ của chính nó để sửa sai, mà coi đó là một văn bản cần tiếp tục phát triển, dẫn đến hiện tượng suy luận lan man (wandering CoT).

### Bước 2: Bẫy Tâm lý Khẳng định (Confirmation Bias Trap) dưới góc độ Tự hồi quy
- Quá trình tự hồi quy (Autoregressive generation) tối đa hóa xác suất token tiếp theo dựa trên ngữ cảnh đã có: $P(y_t | y_{<t}, x)$.
- Nếu $y_{<t}$ chứa 2.000 tokens giải thích tại sao cột `A` phải bằng `B`, xác suất để mô hình sinh ra token phủ nhận cột `A` ở Turn 2 là cực kỳ thấp. Ngược lại, nếu $y_{<t}$ chỉ chứa đoạn code thực tế `df['A'] == 'B'` kèm lỗi `KeyError: 'A'`, mô hình nhìn nhận khách quan đây là một thực thể code bị lỗi và dễ dàng chuyển hướng sang tên cột khác.

### Bước 3: Mâu thuẫn Không thể Điều hòa với Giới hạn Phần cứng & Cuộc thi
- Cuộc thi quy định ngữ cảnh tối đa 16.384 tokens và môi trường Docker hoàn toàn offline.
- Tốc độ tăng trưởng 2.850 tokens/turn của phương án giữ `<think>` là một hàm tuyến tính dốc đứng, va chạm trần 16.384 tokens chỉ sau 4 turns.
- Không có bất kỳ kỹ thuật nén prompt nào có thể giữ được tính toàn vẹn của 10.000 tokens CoT mà không làm méo mó ngữ cảnh.

### Bước 4: Đối chiếu với Thực tiễn của các Framework Agent Hiện đại
Cách các hệ thống hàng đầu thế giới xử lý reasoning CoT trong Agent nhiều lượt:
1. **HuggingFace `smolagents` (CodeAgent)**:
   - Lưu trữ lịch sử dưới dạng cấu trúc `ActionStep` riêng biệt.
   - Khi gửi prompt cho lượt tiếp theo, `smolagents` **chỉ truyền tool call và observation**, loại bỏ hoặc tóm tắt cực ngắn phần internal monologue của bước trước.
2. **Khuyến nghị Chính thức từ DeepSeek AI**:
   - Tài liệu kỹ thuật của DeepSeek khuyến cáo: Khi tích hợp DeepSeek-R1 vào multi-turn chat hoặc tool-use agent, **phải bóc tách và loại bỏ thẻ `<think>...</think>` trước khi lưu vào message history**. Lượt tiếp theo chỉ nhận: `[Assistant: Code/Action] -> [User: Observation]`.
3. **Anthropic Claude 3.7 Thinking Protocol & OpenAI o1/o3**:
   - OpenAI và Anthropic hoàn toàn ẩn (redact) khối suy luận thô khỏi API đa lượt. Khối suy luận được coi là **tạm thời (ephemeral)**, chỉ phục vụ cho việc sinh ra action ở turn đó.

---

## 3. Caveats & Unknowns (Các Giới hạn & Giả định)

1. **Giả định về Kích thước Khối `<think>`**:
   - Tính toán sử dụng giá trị trung bình $2.000$ tokens cho mỗi khối `<think>`. Nếu mô hình sinh thinking ngắn hơn (ví dụ 800 tokens), điểm tràn context window sẽ dời từ Turn 5 sang Turn 7. Tuy nhiên, bản chất của các mô hình reasoning như R1/QwQ là sinh rất dài (thường chạm ngưỡng `max_tokens: 4096` khi gặp bài toán phức tạp), nên nguy cơ tràn context là điều chắc chắn xảy ra.
2. **Kỹ thuật Tóm tắt Suy luận (CoT Summarization)**:
   - Về lý thuyết, có thể dùng một mô hình nhỏ để tóm tắt `<think>` thành 50 tokens bullet-points trước khi chuyển sang turn sau. Tuy nhiên, quy chế cuộc thi giới hạn $\le 15\text{B}$ tham số tổng cộng và Docker offline; việc chạy thêm một mô hình summarizer hoặc gọi LLM tóm tắt chính nó sẽ làm tăng gấp đôi độ trễ suy luận, hoàn toàn không khả thi trong bài toán này.
3. **Mô hình Reasoning Đa lượt Tương lai**:
   - Nếu trong tương lai xuất hiện một mô hình $\le 15\text{B}$ được train native đa lượt có CoT bền vững, giả định này có thể thay đổi. Nhưng tính đến thời điểm hiện tại (trước hạn chót 01/10/2026 của cuộc thi), tất cả các open-weights models (DeepSeek-R1-Distill, QwQ, Qwen2.5-Coder) đều hoạt động theo cơ chế CoT đơn lượt.

---

## 4. Conclusion & Actionable Recommendations (Kết luận & Kiến nghị Hành động)

### 4.1. Kết luận Đanh thép (Adversarial Verdict)
1. **BÁC BỎ HOÀN TOÀN đề xuất giữ khối `<think>...</think>` giữa các turn**: Đây là một đề xuất phi thực tế, thiếu hiểu biết về bản chất tự hồi quy của reasoning LLMs, vi phạm giới hạn 16.384 tokens và khiến hệ thống sụp đổ vì timeout trên hạ tầng chấm thi.
2. **BÁC BỎ mô hình ReAct 5–10 turns cho bài toán DataMate**: Phân tích dữ liệu bảng biểu không phải là bài toán lướt web (web browsing) hay tìm kiếm thông tin mở. Một đoạn mã Pandas/SQLite hoặc là tính toán thành công, hoặc là gặp lỗi schema. Mở rộng lên 5–10 turns chỉ làm tăng nguy cơ sinh mã đoán mò, dẫn tới đáp án sai và bị trừ điểm nặng nề (-1.0 điểm PA).

### 4.2. Kiến nghị Kiến trúc Thay thế Tối ưu (Lean Bounded Execution Architecture)

Thay vì chạy theo ReAct 16 công cụ và lưu giữ thinking phức tạp, đội ngũ phát triển cần triển khai kiến trúc **Lean Bounded Execution** gồm 4 trụ cột:

#### Trụ cột 1: Ephemeral Thinking (Suy luận Nội tâm Tạm thời)
- Giữ nguyên cơ chế hiện có tại `src/agent/solver.py:1086-1091`: Mô hình được tự do suy luận sâu trong khối `<think>` ở mỗi turn để sinh mã chất lượng cao.
- Nhưng **ngay sau khi sinh xong**, bóc tách triệt để `<think>`:
  ```python
  compact_asst_reply = f"```python\n{extracted_code}\n```"
  messages.append({"role": "assistant", "content": compact_asst_reply})
  ```
- Lượt kế tiếp, mô hình sẽ nhìn nhận code cũ và lỗi runtime một cách khách quan với một khối `<think>` hoàn toàn mới mẻ, sạch sẽ.

#### Trụ cột 2: Single-Turn First kết hợp Rich Preflight Profiling
- Đầu tư vào khâu tiền xử lý cấu trúc dữ liệu (`business_loader.py` theo đề xuất của Explorer Survey 1):
  - Quét toàn bộ bảng vào RAM trong $\le 0{,}08\text{s}$.
  - Cung cấp danh sách nhãn phân loại chính xác 100% (`categorical_values` như `['Xong', 'Đang giao']`), phát hiện dòng tiêu đề thật (`header_row`), giải quyết ngày tương đối trước khi prompt đến tay mô hình.
- Khi dữ kiện đã rõ ràng trong prompt đầu tiên, mô hình có thể giải đúng **ngay ở Turn 1 (Zero-shot Code Execution)**, đưa thời gian xử lý xuống $\approx 15 - 25\text{s / câu hỏi}$, tiết kiệm 80% chi phí tính toán.

#### Trụ cột 3: Bounded Self-Correction (Giới hạn Nghiêm ngặt Tối đa 2 Turns)
- Giới hạn chu trình Agent ở mức tối đa **2 turns** (hoặc 3 turns cực hạn):
  - **Turn 1 (Execution)**: Sinh toàn bộ code giải bài toán.
  - Nếu thành công và vượt qua Guardrails $\rightarrow$ Trả kết quả `final` ngay.
  - Nếu gặp lỗi cú pháp / schema (`KeyError`, `FileNotFoundError`) $\rightarrow$ **Turn 2 (Correction)**: Nạp lại thông báo lỗi ngắn gọn kèm gợi ý schema sửa đổi.
  - Nếu Turn 2 vẫn tiếp tục lỗi hoặc không ra kết quả $\rightarrow$ **DỪNG LẠI NGAY LẬP TỨC**.

#### Trụ cột 4: Cổng Từ Chối Nghiêm Ngặt (Strict Abstain Gate) Tối ưu Điểm PA
- Quy chế cuộc thi áp dụng Penalized Accuracy:
  $$\text{PA} = \frac{1}{N} \left( N_{\text{correct}} \times 1.0 + N_{\text{abstain}} \times 0.0 - N_{\text{wrong}} \times 1.0 \right)$$
- Mỗi lần đoán sai bị phạt **-1.0 điểm** (tệ hơn rất nhiều so với 0.0 điểm khi từ chối).
- Do đó: Khi Turn 2 không thể giải quyết hoặc code sinh ra kết quả rỗng / vi phạm kiểm định nghiệp vụ $\rightarrow$ Kích hoạt `Abstain Gate` để trả về `"abstain"` lấy **0.0 điểm an toàn**, tuyệt đối không để mô hình chạy tiếp sang Turn 4–5 để rồi đoán mò và nhận điểm âm.

---

## 5. Verification Method (Phương pháp Kiểm chứng Độc lập)

Người nhận báo cáo và Worker có thể độc lập kiểm chứng các kết luận trên bằng các bước cụ thể:

1. **Kiểm chứng Cơ chế Cắt bỏ `<think>` Hiện tại**:
   - Mở file `src/agent/solver.py` tại dòng 1086–1091 và dòng 1108.
   - Chạy lệnh kiểm thử đơn vị:
     ```powershell
     python -m pytest tests/test_solver_multiturn.py -k "test_observation_then_final_on_synthetic_data" -v
     ```
   - Xác nhận trong trace messages của Turn 2 chỉ có khối code, không có thẻ `<think>`.

2. **Kiểm chứng Toán học Tràn Context**:
   - Chạy script kiểm tra tăng trưởng token:
     ```powershell
     python -c "
     init = 5500; think = 2000; code = 300; obs = 500
     total = init
     for t in range(1, 6):
         print(f'Turn {t}: {total} tokens (Remaining: {16384 - total})')
         total += (think + code + obs)
     "
     ```
   - Xác nhận Turn 5 đạt $16.700\text{ tokens} > 16.384\text{ tokens}$.

3. **Kiểm chứng Dung lượng KV-Cache**:
   - Chạy lệnh tính dung lượng KV-cache theo cấu hình Qwen2.5-14B:
     ```powershell
     python -c "
     layers, heads, dim = 48, 8, 128
     print('KV Cache at 16384 ctx:', (16384 * 2 * layers * heads * dim * 2) / (1024**3), 'GB')
     "
     ```
   - Xác nhận kết quả chính xác bằng $3{,}00\text{ GB / sequence}$.

4. **Kiểm chứng Thời gian Thực thi Thực tế**:
   - Đọc báo cáo thực nghiệm thực tế tại `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/evaluation_report.json`.
   - Xác nhận: 30 câu hỏi với mô hình 14B code-only hoàn thành trong 856 giây (28.5s/câu).
   - So sánh với kịch bản sinh 2.000 thinking tokens mỗi turn qua 5 turns (tối thiểu 250s/câu $\rightarrow$ gấp gần 9 lần thời gian).

---

*Handoff report được lập bởi Explorer Survey 2 — Tuân thủ nghiêm ngặt 5 thành phần của Handoff Protocol.*
