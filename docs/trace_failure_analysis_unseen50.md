# Phân tích trace eval unseen_50 (Ornith + opencode, Kaggle 2xT4)

Nguồn: `traces/*.json` (43 file, 2 file rỗng, 9/50 câu không có trace) đối chiếu `eval_gold/unseen_gold_50.jsonl`.

## Điểm
- 41 câu có trace: đúng 10 (+10), sai 4 (-4), abstain 27 (0) -> PA = 6/41 = 0.146
- Abstain theo lý do: question_timeout 19, unparseable_final 7, empty_final 2, ambiguous_type 1

## 4 nhóm lỗi chính
1. **Hết giờ 600s (19 câu).** Mỗi lượt model nghĩ 30-110s, 151/294 lần run_python lỗi (51%): KeyError tên cột, AttributeError, import module bịa (`tools.parse`, `helpers.emit`), SyntaxError, NameError. Hết ngân sách trước khi emit_final.
2. **Final bị bỏ oan (3 câu đúng bị abstain).** 22f5, 725f, a264 có `tool_rescue_prediction` đúng gold nhưng bị gate `unparseable_final` ép abstain vì final text không phải JSON.
3. **Final text rác (3 câu).** 21c1 (text là bản tóm tắt compaction "Do not use tools..."), 132a (text tiếng Trung bịa "đã hết bước"), c0c5 (answer bọc JSON trong string). 
4. **Logic sai nhưng vẫn emit (4 câu, -4).** Xem bảng.

## Câu sai (bị -1)
| id | Câu | Pred / Gold | Nguyên nhân |
|---|---|---|---|
| 0c20 (biz_127) | Ngày doanh thu cao nhất T12/2025 | "{'answer':'2025-12-20',...}" (string) / 2025-12-07 | Lần chạy cuối tính ĐÚNG (stdout `Top date: 2025-12-07`) nhưng emit_final hard-code '2025-12-20' lấy từ output cũ. Output cũ sai vì `drop_duplicates('Mã đơn hàng')` chỉ giữ 1 dòng/đơn. Answer còn bị bọc dict, type=string thay vì date. |
| 5ade (biz_117) | Doanh thu Thép Pomina D10 T6/2025 | 13085600 / 17566000 | Cộng cả 53 dòng, không lọc trạng thái (có Hủy/hủy/trả lại/Đã trả hàng). Parse "1tr150" thành 1150 thay vì 1.150.000. Evidence ghi "tất cả đã hoàn thành", sai. Không dùng load_clean_df. |
| 5c5f (biz_121) | Doanh thu thuốc hoạt chất Povidon iod T10/2025 | 0 / 8253000 | Ngày dạng DD/MM/YYYY nhưng lọc `str[:7]=="2025-10"` nên luôn rỗng. Trạng thái "Đang giao dịch" không khớp "Đang giao". Kết quả 0 lọt qua abstain gate. |
| 6a54 (biz_102) | Bán bao nhiêu kg nếp cái hoa vàng T6/2025 | 28 / 59 | Không dùng DanhSachQuyDoi để quy về kg, không lọc trạng thái. emit_final 2 lần (179 rồi 28), lần cuối thắng. |

## Abstain do final bị hỏng
| id | Gold | Cái model có | Ghi chú |
|---|---|---|---|
| 22f5 | unanswerable | emit_final unanswerable (đúng) | Bị gate chặn, lẽ ra +1 |
| 725f | 2026-07-30 | rescue "2026-07-30" (đúng) | Raw final "30/07/2026" sai format nên bị chặn, lẽ ra +1 |
| a264 | Snack Oishi tôm cay 40g | rescue đúng | Lẽ ra +1 |
| c0c5 | Cty Tăng Giang | rescue = chuỗi JSON `{"type":"string","answer":...}` | Model tự bọc answer, nên abstain là đúng |
| 21c1 | Thân Hồng Nhung (KH0170) | tính ra KH0170 đúng trong obs | Final text là bản tóm tắt, mất đáp án |
| 132a | 535722 | ra 546028 / 800719 / 356938, không ổn định | Final text bịa, abstain đúng |
| 02a7 | sữa, trà, đen | rescue [đen, sữa, trà] | Chỉ lọc "Đã hoàn thành" (bỏ đơn đang giao), thứ tự sai. Abstain cứu được -1 |
| 338a, 3b5c | -16.41 / 121 | không có | finish_reason=length, final rỗng sau 3 tool call. Chưa rõ nguyên nhân (nghi hết max output/context) |

## Timeout (19 câu)
| id | Câu | calls / py lỗi | Ghi chú |
|---|---|---|---|
| 019e | Top 3 hàng bán chạy tuần này | 12 / 6 lỗi | Mỗi lượt ~100s, lỗi KeyError/SyntaxError liên tục |
| 01a2 | Giá soda chanh dây 01/12/2025 | 17 / 9 | Usecols/SyntaxError |
| 153f, 9b1d | Top 3 khách nợ nhiều nhất | 11 / 5, 15 / 5 | Công nợ nặng, file 78k dòng |
| 1b11 | Doanh thu T7-T9/2025 | 12 / 6 | Đáp án đúng đã xuất hiện trong output, nhưng không kịp emit |
| 1f99, 43df, 9737 | Nợ / mua chịu / trả nợ | 9-17 | Công nợ §4 phức tạp |
| 2dc1, 8576 | Hiệu ứng tăng giá | 16 / 8, 14 / 7 | Luật §5 nhiều bước |
| 2ea3 | Top 3 khách tuần rồi | 14 / 4 | Tính ra KH0192, KH0022, KH0255 đúng cửa sổ, chưa kịp map sang tên |
| 360f | Hàng hết hạn trong 120 ngày (gold unanswerable) | 8 / 2 | Model đang dò file, không kịp kết luận |
| 583e, 8c43 | % nhóm sữa / tăng giảm % | 11, 16 | |
| 77de | Ngày doanh thu cao nhất T4/2025 | 11 / 6 | |
| 80f4 | Doanh thu 3 tháng có tăng liên tục không | 14 / 7 | Đã tính đúng (338M, 323M... không tăng liên tục) nhưng timeout trước emit, gold false |
| a569 | Tương tự 80f4 | 18 / 12 lỗi | 0 lần chạy thành công: dùng `load_clean_df` rồi rename cột 'date' không tồn tại |
| aacf | Khách mua nhiều nhất T3/2026 | 13 / 7 | Cột Thời gian lẫn chuỗi dd/mm/yyyy và serial Excel (45689), tốn hết thời gian vào ngày |

## Gợi ý sửa (theo độ ưu tiên)
1. Dùng `tool_rescue_prediction` / kết quả emit_final khi raw final không parse được, thay vì abstain. Gain chắc chắn +3 trên mẫu này.
2. Khi sắp hết 600s mà obs gần nhất đã có đáp án (80f4, 1b11), tự emit thay vì để timeout.
3. emit_final nên từ chối answer là dict/list lồng sai type, và chỉ chấp nhận lần emit đầu hoặc cuối có kiểm tra, tránh hard-code số từ output cũ.
4. Ép dùng `load_clean_df` + helper quy đổi đơn vị/chuẩn hoá trạng thái/ngày (DD/MM/YYYY, serial Excel, "1tr150") thay vì pd.read_excel thô.
5. Giảm tỉ lệ lỗi run_python 51%: cho model xem danh sách cột thật sau mỗi KeyError, chặn import không tồn tại.
