# Zalo AI Challenge 2026 — DataMate: Thể lệ & Yêu cầu kỹ thuật (Rules)

## 1. Các vòng thi (Competition rounds)

Cuộc thi diễn ra trên bảng xếp hạng (*leaderboard*) với lộ trình gồm hai vòng:

- **Vòng 1 — Kiểm tra công khai (*Round 1 — Public test*):** Các đội phát triển giải pháp, chạy thử nghiệm trên tập dữ liệu kiểm tra công khai (*public test set*) và tải lên file kết quả `submission.jsonl`. Điểm số hiển thị trên bảng xếp hạng công khai (*public leaderboard*) chỉ mang tính chất tham khảo trong quá trình phát triển.
- **Nộp giải pháp cuối cùng (*Final solution submission*):** Trước thời hạn đóng cổng nộp giải pháp (*solution deadline*), giải pháp cuối cùng phải được đóng gói và nộp dưới dạng một **Docker image**, tuân thủ hướng dẫn riêng về Docker (*Docker guideline*) của Ban Tổ chức. Khi chấm điểm, Ban Tổ chức sẽ gắn (*mount*) tập dữ liệu kiểm tra vào bên trong *container* tại đường dẫn `/data` và thu thập kết quả tại `/result/submission.jsonl`.
- **Vòng 2 — Kiểm tra riêng tư (*Round 2 — Private test*):** Sau khi các đội đã nộp và đóng băng (*freeze*) giải pháp của mình, Ban Tổ chức sẽ công bố tập dữ liệu kiểm tra riêng tư (*private test set*). Các đội chạy giải pháp đã đóng băng trên tập dữ liệu này và tải lên file `submission.jsonl`. Thứ hạng chung cuộc (*final ranking*) được quyết định dựa trên kết quả chạy lại (*re-run*) các *Docker image* đã nộp do chính Ban Tổ chức thực hiện (xem Quy định 8).

---

## 2. Yêu cầu kỹ thuật (Technical requirements)

Mọi giải pháp dự thi bắt buộc phải đáp ứng đầy đủ tất cả các yêu cầu dưới đây:

1. **Đội thi và tư cách hợp lệ (*Teams and eligibility*):** Tuân thủ quy chế chung của cuộc thi **Zalo AI Challenge 2026**.

2. **Mô hình sử dụng (*Models*):**
   - Bạn được phép sử dụng bất kỳ mô hình nào có trọng số (*weights*) được công bố công khai trước ngày **01/10/2026** dưới giấy phép (*licence*) cho phép mục đích sử dụng này, và bạn được tự do tinh chỉnh (*fine-tune*) mô hình đó.
   - Tính tổng cộng trên **tất cả các mô hình** được sử dụng ở bước suy luận (*inference*) trong giải pháp của bạn (bao gồm *language models*, *embedding models*, *rerankers*, *classifiers*), bất kể chúng có được nạp (*load*) cùng một lúc hay không, **tổng số lượng tham số (*total number of parameters*) không được vượt quá 15 tỷ (15B)** — đối với các mô hình *Mixture-of-Experts (MoE)*, con số này tính trên **toàn bộ tham số** của mô hình.
   - Cho phép sử dụng mọi kỹ thuật lượng tử hóa (*quantization*).
   - Tất cả các mô hình được sử dụng bắt buộc phải được kê khai rõ ràng trong file `README` của giải pháp.

3. **Không sử dụng dịch vụ bên ngoài (*No external services*):**
   - Quá trình suy luận (*inference*) phải chạy **hoàn toàn ngoại tuyến (*fully offline*)** bên trong *Docker image* của bạn: không được gọi tới các *commercial LLM APIs*, không tải thêm dữ liệu/mô hình, và không truy cập mạng dưới bất kỳ hình thức nào.
   - *Docker image* sẽ được khởi chạy ở chế độ vô hiệu hóa hoàn toàn kết nối mạng (*networking disabled*).

4. **Không có sự can thiệp của con người (*No human in the loop*):**
   - Câu trả lời phải được sinh ra hoàn toàn tự động bởi hệ thống của bạn mà không có bất kỳ sự can thiệp thủ công nào.
   - Nghiêm cấm việc gán cứng câu trả lời (*hard-coding answers*) hoặc viết logic xử lý dựa theo mã định danh của câu hỏi (`id`) hay mã doanh nghiệp (`business_id`).

5. **Thực thi mã nguồn (*Code execution*):**
   - *Agent* của bạn có thể tự sinh và thực thi code bên trong *container* (đây là hướng tiếp cận được kỳ vọng nhưng không bắt buộc).
   - Thư mục dữ liệu (`/data`) được gắn ở chế độ **chỉ đọc (*read-only*)**; mọi file tạm (*temporary files*) phải được ghi ở thư mục khác.

6. **Dữ liệu (*Data*):**
   - Bạn được phép sử dụng tập dữ liệu huấn luyện (*training data*) do Ban Tổ chức cung cấp, dữ liệu do bạn tự tổng hợp (*synthetic data*), cũng như các bộ dữ liệu và mô hình công khai hợp lệ.
   - **Nghiêm cấm** sử dụng dữ liệu *public test* hoặc *private test* để huấn luyện, cũng như không được thu thập đáp án của các câu hỏi kiểm tra dưới bất kỳ hình thức nào.

7. **Cấu hình phần cứng tham chiếu (*Compute reference*):**
   - Các giải pháp sẽ được kiểm thử và xác minh trên hệ thống máy chủ trang bị **2 × NVIDIA RTX 5090** (mỗi GPU có **32 GB VRAM**, tổng cộng **64 GB VRAM**) và **512 GB RAM**.
   - Giải pháp của bạn phải xử lý xong toàn bộ tập *private test set* trong vòng tối đa **6 giờ** tính theo thời gian thực (*wall-clock time*) trên cấu hình máy này (đã bao gồm cả thời gian nạp mô hình — *model loading*).
   - Dòng GPU kiến trúc **Blackwell** yêu cầu **CUDA ≥ 12.8** cùng bản dựng **PyTorch / vLLM** tương thích; tài liệu *Docker guideline* sẽ quy định cụ thể *base image* cần sử dụng.

8. **Điểm số cuối cùng và tính tái lập (*Final score and reproducibility*):**
   - Điểm số từ lần chạy lại (*re-run*) *Docker image* đã nộp trên tập *private test set* do Ban Tổ chức thực hiện sẽ là **điểm số chung cuộc (*final score*)** của bạn.
   - File `submission.jsonl` mà bạn tải lên trong giai đoạn *private test* chỉ dùng để xếp hạng tạm thời (*provisional leaderboard*) và xác định những đội nào sẽ được chọn để chạy lại (*re-run*).
   - Giải pháp của bạn phải đủ tính tất định (*deterministic*) để kết quả giữa hai lần chạy thống nhất với nhau: một giải pháp được coi là **có tính tái lập (*reproducible*)** nếu thỏa mãn:
     $$|\text{PA}_{\text{uploaded}} - \text{PA}_{\text{re-run}}| \le 0.03$$
   - Nếu độ lệch vượt quá `0.03`, Ban Tổ chức sẽ kiểm tra nhật ký (*logs*) được ghi lại bởi *Docker image* của bạn (xem phần *Submission format*, Mục *Data*), có thể chạy lại *image* thêm một lần nữa và yêu cầu đội thi giải trình thêm thông tin; nếu không thể giải thích hợp lý nguyên nhân sai lệch, bài dự thi sẽ bị **loại (*disqualified*)**.
   - Nếu quá trình chạy lại (*re-run*) vượt quá giới hạn thời gian 6 giờ nêu tại Quy định 7 hoặc bị dừng sớm (*terminates early*), chỉ những câu trả lời đã được ghi vào `/result/submission.jsonl` trước thời điểm dừng mới được chấm điểm; toàn bộ các câu hỏi còn lại sẽ được tính là `abstain`.
