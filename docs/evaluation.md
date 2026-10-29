# Zalo AI Challenge — DataMate: Cách thức đánh giá (Evaluation)

## 1. Chấm điểm từng câu hỏi (Per-question scoring)

Mỗi câu trả lời được chấm theo một trong 3 trạng thái: **đúng (`correct`)**, **sai (`wrong`)** hoặc **từ chối trả lời (`abstain`)**.
- Một câu trả lời có kiểu (`type`) là `abstain` (hoặc câu trả lời bị khuyết/thiếu — *missing answer*) được tính là `abstain`.
- Bất kỳ câu trả lời nào khác chỉ được tính là **đúng (`correct`)** khi `type` của nó trùng khớp với `type` của đáp án chuẩn (*reference type*) **và** giá trị (`value`) của nó khớp với đáp án chuẩn (*reference*) theo quy tắc dưới đây; ngược lại sẽ bị tính là **sai (`wrong`)**. Không có điểm thành phần (*no partial credit*).

### Bảng quy tắc so khớp theo kiểu dữ liệu (Matching Rules)

| `Type` | Nội dung câu trả lời (*Answer content*) | Ví dụ (*Example*) | Quy tắc so khớp (*Matching rule*) |
| :--- | :--- | :--- | :--- |
| `number` | Một giá trị số (số tiền VNĐ, số đếm, số lượng/khối lượng) | `48250000` | **Khớp chính xác (*Exact match*).** Các giá trị chuẩn (*reference values*) là số nguyên (đối với số tiền VNĐ, số đếm, số lượng) hoặc được làm tròn đến 2 chữ số thập phân (*rounded to 2 decimals*). |
| `percent` | Một giá trị phần trăm (tính theo đơn vị %) | `-12.45` | **Khớp chính xác (*Exact match*)** sau khi làm tròn đến 2 chữ số thập phân (*2 decimal places*); dấu âm/dương (*sign*) phải chính xác. |
| `string` | Một tên gọi (sản phẩm, khách hàng, chi nhánh, thứ trong tuần, ...) | `"Sting dâu 330ml"` | Cả câu trả lời và mỗi dạng được chấp nhận (*accepted form*) của đáp án chuẩn đều được **chuẩn hóa (*normalized*)**, sau đó so sánh bằng chính xác (*exact equality*).<br><br>**Quy trình chuẩn hóa (*Normalization*):**<br>(1) Chuẩn hóa mã `Unicode NFC`;<br>(2) Chuyển toàn bộ về chữ thường (*lowercase*);<br>(3) Mọi ký tự không phải chữ cái (*letter*), chữ số (*digit*) hoặc khoảng trắng (*whitespace*) được thay thế bằng một dấu cách (*space*);<br>(4) Xóa khoảng trắng ở đầu/cuối (*leading/trailing whitespace*) và gộp các khoảng trắng liên tiếp thành một dấu cách duy nhất.<br>**Lưu ý:** Dấu tiếng Việt **không** bị lược bỏ (*diacritics are not removed*).<br><br>Mỗi đáp án chuẩn liệt kê tất cả các dạng được chấp nhận của nó: bao gồm mọi cách viết của tên đó xuất hiện trong dữ liệu của doanh nghiệp, cộng với mã (*code*) của nó — sau khi đã chuẩn hóa, ví dụ: `sting dâu 330ml`, `sp0042`. |
| `date` | Ngày tháng theo định dạng chuẩn ISO (*ISO format*) | `"2026-08-15"`, `"2025-09"` | **Khớp chính xác (*Exact match*).** Định dạng `yyyy-mm-dd`; đối với câu hỏi về một tháng: `yyyy-mm` (ví dụ: `"2025-09"`). |
| `boolean` | `true` / `false` | `true` | **Khớp chính xác (*Exact match*).** |
| `list` | Một danh sách có thứ tự gồm các tên hoặc các con số, theo đúng thứ tự mà câu hỏi yêu cầu (hoặc theo mặc định trong `rulebook`) | `["Cà phê sữa", "Bạc xỉu", "Trà đào"]` | Luôn xét thứ tự (*always ordered*), và được so khớp theo từng vị trí một (*matched position by position*). Thứ tự là thứ tự được yêu cầu trong câu hỏi, hoặc theo mặc định của `rulebook` khi câu hỏi không nêu rõ (xem phần **Câu hỏi xếp hạng (*Ranking questions*)** bên dưới). Từng phần tử được so khớp theo quy tắc của `string` hoặc `number`. |
| `table` | Một bảng dữ liệu nhỏ: gồm tên các cột (`columns`) và các hàng (`rows`) | `{"columns": [...], "rows": [[...], ...]}` | Các cột (`columns`) được so khớp theo tên đã chuẩn hóa (*normalized name*); nếu tên cột không khớp thì sẽ so khớp theo vị trí (*by position*). Các hàng (`rows`) được so khớp như một tập hợp (*matched as a set* — không phụ thuộc thứ tự hàng); các ô chứa tên được so khớp theo quy tắc `string`, các ô chứa số được so khớp theo quy tắc `number`. |
| `unanswerable` | Dữ liệu không chứa những thông tin cần thiết để trả lời câu hỏi | — | Được tính là đúng (`correct`) **khi và chỉ khi** đáp án chuẩn (*reference*) cũng là `unanswerable`. |
| `abstain` | Agent chủ động lựa chọn không trả lời | — | Luôn được chấm là `abstain` bất kể đáp án chuẩn (*reference*) là gì. |

### Câu hỏi xếp hạng (Ranking questions)

Việc xếp hạng sử dụng tiêu chí (*criterion*) được nêu trực tiếp trong câu hỏi, hoặc tiêu chí mặc định của `rulebook` khi câu hỏi không nêu rõ, sắp xếp theo **thứ tự giảm dần (*descending order*)** của tiêu chí đó và **chỉ tính trên các đơn hàng hợp lệ (*valid orders only*)**; các phần tử có giá trị bằng nhau sẽ được sắp xếp theo mã (*code*) theo **thứ tự tăng dần (*ascending*)**.

Những câu hỏi mà bảng xếp hạng chuẩn (*reference ranking*) có sự đồng hạng (*tie*) tại ranh giới vị trí thứ $k$ (hoặc tại hạng 1 đối với các câu hỏi dạng *“… nhất”*) đã được loại trừ khỏi các tập kiểm tra (*test sets*). Khi có ít hơn $k$ ứng viên thỏa mãn, đáp án chuẩn (*reference answer*) sẽ là toàn bộ các ứng viên đó.

---

## 2. Điểm số tổng hợp (Score)

Chỉ số đánh giá trên bảng xếp hạng (*leaderboard metric*) là **Độ chính xác có phạt — Penalized Accuracy ($\text{PA}$)** tính trên tổng số $N$ câu hỏi của một tập kiểm tra (*test set*):

$$\text{PA} = \frac{1}{N} \sum_{i=1}^{N} s_i, \qquad s_i = \begin{cases} 1 & \text{nếu câu trả lời } i \text{ đúng (\texttt{correct})} \\ 0 & \text{nếu câu trả lời } i \text{ từ chối trả lời (\texttt{abstain})} \\ -1 & \text{nếu câu trả lời } i \text{ sai (\texttt{wrong})} \end{cases}$$

- Bất kỳ câu trả lời nào được đưa ra cho một câu hỏi không thể trả lời (`unanswerable`) — tức là trả lời một giá trị khác thay vì trả về `unanswerable` (hoặc `abstain`) — đều bị tính là **sai (`wrong`)**.
- Tất cả các câu hỏi đều có trọng số bằng nhau (*equal weight*).
- Trong trường hợp bằng điểm nhau trên bảng xếp hạng cuối cùng (*ties in the final ranking*), thứ hạng sẽ được phân định ưu tiên theo **tổng thời gian suy luận (*total inference time*)** trong lần chạy lại (*re-run*) của Ban Tổ chức, sau đó xét đến thời điểm nộp bài sớm hơn (*earlier submission*).
