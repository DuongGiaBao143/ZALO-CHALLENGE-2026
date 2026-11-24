## 2026-11-13T05:03:26Z
Bạn là subagent teamwork_explorer được giao nhiệm vụ khảo sát kiến trúc mã nguồn sandbox và solver của dự án DataMate (Zalo AI Challenge 2026).

Đọc tài liệu yêu cầu gốc tại: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\ORIGINAL_REQUEST.md
Thư mục làm việc: d:\PROJECT\ZALO-AI-CHALLENGE-2026
Thư mục trạng thái của bạn: d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_1

Nhiệm vụ cụ thể:
1. Khảo sát cấu trúc thực thi sandbox hiện tại trong `src/agent/sandbox.py`, `src/time_resolver/`, `src/profiler/`, `src/postprocess/`:
   - Môi trường thực thi code (globals, builtins, timeout, error capture).
   - Các hàm helper hiện có: có đang bị cồng kềnh, phân tán hoặc gán cứng logic theo ngành nghề (hardcoded domain logic) không?
   - Cần thiết kế lại 6 helper tinh gọn phi ngành nghề (Domain-Agnostic Lean Helpers):
     + `explore_data(file, column=None, keyword=None, n=5)`
     + `fuzzy_find(df_or_file, column, query, top_k=5)`
     + `load_clean_df(file, sheet=0, dedup_order=True, as_of_date=None)`
     + `resolve_date(expr, as_of_date)`
     + `emit_obs(data, msg)`
     + `emit_final(answer, type, evidence, check=None, reason=None)`
   - Phân tích chi tiết cách cài đặt từng helper này vào `sandbox.py` với generic tabular/text primitives (pandas, difflib, unidecode, sqlite3...).
2. Khảo sát luồng suy luận ReAct trong `src/agent/solver.py`:
   - Cách quản lý multi-turn loop, prompt template, history context.
   - Vấn đề phình to context window với mô hình Qwen/Qwen2.5-14B-Instruct-1M (giới hạn 16,384 tokens).
   - Cơ chế Ephemeral Thinking: làm thế nào để lược bỏ các block `<think>` thô của các turn trước, chỉ giữ tóm tắt 3-5 dòng kế hoạch/trạng thái + code + observation khi build prompt cho turn tiếp theo?
3. Xuất báo cáo chi tiết kèm chữ ký hàm, cấu trúc dữ liệu, và pseudo-code vào:
   `d:\PROJECT\ZALO-AI-CHALLENGE-2026\.agents\teamwork\explorer_1\report.md`
   và tạo file `handoff.md` theo Handoff Protocol.
4. Gửi tin nhắn hoàn thành về cho orchestrator qua send_message.
LƯU Ý: Tuyệt đối CHỈ ĐỌC, KHÔNG chỉnh sửa bất kỳ file mã nguồn nào trong `src/` hay `notebooks/`!
