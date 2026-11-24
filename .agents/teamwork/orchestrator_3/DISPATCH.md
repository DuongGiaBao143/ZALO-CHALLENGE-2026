## 2026-11-13T04:04:40Z
Thực hiện phản biện toàn diện (adversarial review / critique) đối với kế hoạch bàn giao kỹ thuật (HANDOFF_PLAN.md) gồm đặc tả 16 công cụ cho Agent, quy trình suy luận ReAct và hướng dẫn cập nhật notebook sang baseline Qwen3.5-9B trong dự án DataMate (Zalo AI Challenge 2026).

Integrity mode: demo
The team must NOT: Đề xuất giải pháp vi phạm quy chế Zalo AI Challenge 2026 (sử dụng mô hình tổng số tham số >15B, kết nối Internet hoặc gọi API bên ngoài, không tương thích môi trường Docker offline, hoặc vượt quá cấu hình phần cứng thẩm định 64GB VRAM).

## Requirements

### R1. Phản biện Toàn diện Kế hoạch Bàn giao Kỹ thuật
Phân tích và phản biện chi tiết, đa chiều toàn bộ các nội dung trong kế hoạch kỹ thuật đã đề xuất:
1. Đánh giá tính khả thi, độ phức tạp và rủi ro của việc xây dựng và tích hợp 16 công cụ (tools) thuộc 6 nhóm chức năng (Data Discovery, Entity Search & VN Normalization, Tabular Cleaning, Time & Coverage, Query & Business Rules, Verification & Protocol); phân tích nguy cơ gây loãng ngữ cảnh, làm bùng nổ số lượt gọi tool (turns) và chi phí tính toán.
2. Phân tích luồng suy luận ReAct và cơ chế lưu giữ khối `<think>...</think>` giữa các turn: đánh giá tính tương thích với cơ chế reasoning của mô hình, nguy cơ tràn context window (16384 tokens) và độ trễ suy luận.
3. Đánh giá tính khả thi và rủi ro của việc chuyển đổi sang baseline `Qwen3.5-9B`: đối chiếu với thông số VRAM (2x RTX 5090 / A100-40GB), format prompt template, khả năng sinh code chính xác và tính tương thích với hạ tầng đánh giá.
4. Đối chiếu trực tiếp với kết quả thực nghiệm trên tập Dev (Base PA -0.1667 với 7 đúng / 12 sai / 11 abstain / 62 turns; Base+LoRA PA -0.0667 với 7 đúng / 9 sai / 14 abstain / 59 turns) và công thức tính điểm Penalized Accuracy (PA: đúng +1.0, abstain 0.0, sai -1.0) để chỉ ra nguyên nhân gốc rễ và đề xuất giải pháp cải thiện điểm số cụ thể.

### R2. Hình thức và Nội dung Báo cáo Phản biện
Trình bày kết quả phản biện trực tiếp dưới dạng văn bản báo cáo có cấu trúc rõ ràng:
- Tóm tắt các phát hiện cốt lõi và mức độ rủi ro của từng phần trong kế hoạch.
- Phân tích chi tiết từng luận điểm phản biện kèm lập luận kỹ thuật và số liệu minh chứng.
- Đề xuất các giải pháp khắc phục, tinh gọn hoặc phương án thay thế khả thi cho từng hạn chế được chỉ ra.

## Acceptance Criteria

### Tính Đầy đủ và Khách quan của Phản biện
- [ ] Báo cáo phản biện bao quát đầy đủ 3 thành phần chính của kế hoạch: đặc tả 16 công cụ (6 nhóm chức năng), luồng suy luận ReAct (giữ khối `<think>`), và việc chuyển đổi notebook sang baseline Qwen3.5-9B.
- [ ] Báo cáo phân tích rõ mối liên hệ giữa các điểm nghẽn trong kế hoạch với kết quả thực nghiệm trên 30 câu Dev (PA âm, tỷ lệ sai cao, số lượt turns lớn, số lần kích hoạt observation thấp).
- [ ] Mọi lập luận phản biện và giải pháp đề xuất tuân thủ nghiêm ngặt các quy định trong `docs/rule.md`, `docs/evaluation.md`, `docs/description.md` (giới hạn 15B params, Docker offline hoàn toàn `--network none`, thẩm định trên 2x RTX 5090 64GB VRAM, công thức Penalized Accuracy).
- [ ] Với mỗi điểm hạn chế hoặc rủi ro được chỉ ra, báo cáo cung cấp phương án điều chỉnh hoặc giải pháp thay thế cụ thể.
