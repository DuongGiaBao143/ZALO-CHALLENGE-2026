# Zalo AI Challenge — DataMate: Hướng dẫn nộp bài (Submission Guidance)

## I. Vòng Kiểm tra Công khai — Public Test Round (26/10 – 16/11)

- Các đội dự thi tự xây dựng giải pháp của mình, chạy giải pháp trên tập kiểm tra công khai (*public test set*) của Ban Tổ chức và nộp file kết quả định dạng `JSONL` thông qua mục **Submission** trên cổng thông tin Zalo AI Challenge.
  - Mỗi đội được phép nộp tối đa **5 lần/ngày**, và hạn mức (*quota*) sẽ được đặt lại (*reset*) vào cuối mỗi ngày.
  - Điểm số và thứ hạng sẽ được hiển thị trực tiếp trên bảng xếp hạng công khai (*public leaderboard*).
- Vào ngày **16/11**, các đội dự thi bắt buộc phải nộp **toàn bộ giải pháp hoàn chỉnh** — bao gồm mã nguồn huấn luyện (*training code*), mã nguồn suy luận (*inference code*) và dữ liệu (*data*) — được đóng gói dưới dạng một **Docker package** gửi tới Ban Tổ chức thông qua biểu mẫu **“Solution Submission”** trên cổng thông tin Zalo AI Challenge.
  - Do file Docker thường có dung lượng khá lớn, các đội cần cung cấp mã kiểm tra toàn vẹn (**`checksum`**) cùng với một đường dẫn **Google Drive công khai (*public Google Drive link*)** để Ban Tổ chức có thể tải về.
  - Mỗi đội được phép gửi biểu mẫu tối đa **2 lần**. Ban Tổ chức sẽ chỉ đánh giá bản nộp cuối cùng (*last submission*).
  - **Hạn chót nộp giải pháp (*Submission deadline*):** `23:59 (GMT+7)` ngày **16/11**.

---

## II. Vòng Kiểm tra Riêng tư — Private Test Round (20/11 – 23/11)

- Vào lúc **`09:00` sáng ngày 20/11**, Ban Tổ chức sẽ công bố tập kiểm tra riêng tư (*private test set*).
- Các đội dự thi chạy giải pháp đã nộp của mình trên tập dữ liệu này và nộp file kết quả (`JSONL`) qua mục **Submission** trên cổng thông tin Zalo AI Challenge, với **hạn chót là `23:59 (GMT+7)` ngày 23/11**.
- Bảng xếp hạng riêng tư (*private leaderboard*) sẽ hiển thị danh sách theo trình tự thời gian (*chronological order* — dựa trên thời điểm nộp bài).
- Ban Tổ chức sẽ tiến hành đánh giá các giải pháp đã nộp để xác minh kết quả (*verify results*), rà soát mã nguồn (*review source code*) và phát hiện mọi hành vi gian lận (*cheating*).
- **2 đội xuất sắc nhất (*Top 2 teams*)** sẽ được công bố vào ngày **02/12**.
