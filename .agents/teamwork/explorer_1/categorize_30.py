import json

with open(".agents/teamwork/explorer_1/cases_dump.json", "r", encoding="utf-8") as f:
    cases = json.load(f)

# Categories:
# A: Fully Solved by 3 steps
# B: Partially Solved / Potential improvement
# C: Unsolved (fundamentally requires other mechanisms: calendar, rulebook §1/§4/§8, merged cells)
# D: Worsened / New Risk Introduced

mapping = {
    # 7 status label failure cases
    "q_20aa992c0d3f": ("A", "Step 1, Step 3", "Lọc nhãn 'hoàn thành' làm rỗng data biz_101 ('Xong'). Step 1 cung cấp nhãn 'Xong', Step 3 chặn rỗng -> Tái tính đúng ngày 2026-05-09."),
    "q_554d736852a5": ("B", "Step 1, Step 3", "Nhãn 'completed' không khớp 'hoàn thành'. Step 1 sửa được nhãn completed, Step 3 tránh unanswerable. Nhưng cần thêm Rulebook §1 (doanh thu theo dòng vs Tổng bill) để khớp 70017."),
    "q_7428165a9e0a": ("B", "Step 1, Step 3", "Nhãn 'completed' biz_129. Step 1 cung cấp đúng nhãn completed, Step 3 chặn 0. Nhưng cần lấy Tiền bán chi tiết thay vì Phải thu để khớp 22.740.500."),
    "q_e0aef192cb11": ("A", "Step 1, Step 3", "Nhãn 'hoàn thành' làm rỗng data biz_101. Step 1 đưa nhãn 'Xong', Step 3 chặn unanswerable -> Tái tính đúng ngày 2026-06-01."),
    "q_e311e396f7f0": ("B", "Step 1, Step 3", "Nhãn 'completed' biz_127. Step 1 sửa nhãn, Step 3 chặn 0. Nhưng cần tính doanh thu theo dòng thay vì Tổng đơn để khớp 1.098.707.000."),
    "q_132add5002d2": ("B", "Step 1, Step 3", "Nhãn 'completed' biz_127 làm rỗng -> NaN. Step 1 sửa nhãn, dữ liệu có 2017 đơn không rỗng, giải quyết lỗi NaN. Nhưng cần tính doanh thu theo dòng."),
    "q_21c12147e6d6": ("B", "Step 1, Step 2", "Lọc sai nhãn + sai tên cột khi join (Mã KH vs Customer ID). Step 1 đưa nhãn completed và schema Customer ID, Step 2 probe cột join."),

    # Merged cells (2 cases)
    "q_e7837d5638fb": ("C", "None", "Merged cells biz_122 (2654 dòng con trống trạng thái/ngày/mã). 3 bước không tự ffill/unmerge. Cần tiền xử lý merged cells hoặc Rulebook §8."),
    "q_5c5ff524d0d9": ("B", "Step 2, Step 3", "Merged cells biz_121 + so mã đơn với SKU thuốc ra 0. Step 3 chặn kết quả 0 (tránh -1 điểm, ép abstain), Step 2 probe SKU -> tên thuốc."),

    # Aggregation level (2 cases)
    "q_02a70ea566f1": ("B", "Step 2, Step 3", "sort_values().head(3) trên dòng hàng ra 3 dòng Croissant. Step 3 nếu check trùng lặp trong top-k list sẽ chặn. Step 2 probe group by."),
    "q_67297f4bdfc2": ("C", "None", "Chia nhầm số mã huỷ cho số dòng sau lọc (0.52%) thay vì số đơn mọi trạng thái (0.98%). Lỗi hiểu sai Rulebook §1 về công thức mẫu số."),

    # Date parsing / Period (2 cases)
    "q_2ea34572153a": ("A", "Step 1, Step 2, Step 3", "So chuỗi ngày ISO trong SQLite làm rỗng -> []. Step 1 đưa sample date format, Step 2 probe format ngày, Step 3 chặn [] cho câu top-k."),
    "q_d401c0884402": ("B", "Step 3", "Dựng kỳ trước sai (01/07-30/06) -> mẫu số 0 -> unanswerable. Step 3 / Abstain Gate chặn unanswerable thành abstain (0đ thay vì -1đ). Để ra đúng cần time resolver."),

    # Snapshot vs Ledger Debt (3 cases)
    "q_43df08e6cce8": ("B", "Step 3", "Dùng snapshot Đã trả -> [0, 0]. Step 3 chặn kết quả [0, 0] đáng ngờ, ép abstain (0đ thay vì -1đ). Để ra đúng cần code đọc sổ quỹ theo Rulebook §4."),
    "q_3b5c9002b013": ("B", "Step 3", "Lọc nhóm COD + dùng snapshot -> 0 khách nợ. Step 3 chặn kết quả count=0, ép abstain (0đ thay vì -1đ). Để ra đúng cần Rulebook §4 bỏ COD."),
    "q_9b1dce77c710": ("B", "Step 3", "Dùng snapshot -> amount_due toàn 0. Step 3 chặn bảng toàn nợ 0, ép abstain. Để ra đúng cần đọc sổ quỹ Rulebook §4."),

    # Hallucinating missing columns / Gold Unanswerable (3 cases)
    "q_22f59bab1075": ("B", "Step 1, Step 2, Step 3", "Shop không có thẻ kho croissant, model lấy Tồn lớn nhất = 999.999.999 chia 6. Step 1 & 2 xác nhận thiếu bảng kho, Step 3 chặn số vô lý."),
    "q_95099c4916a8": ("A", "Step 1, Step 3", "Dùng Loại hình khách (Cá nhân) làm nữ -> 0 dòng -> 0%. Step 1 đưa nhãn 'Cá nhân'/'Doanh nghiệp', Step 3 chặn rows_after_filter==0 -> ra unanswerable."),
    "q_fcafb39ec35f": ("A", "Step 1, Step 3", "Tìm tên đường trong tên khách -> 2 tập rỗng -> kết luận 'bằng nhau'. Step 1 xác nhận thiếu cột địa chỉ, Step 3 chặn so sánh 2 tập rỗng -> unanswerable."),

    # Join & column suffix / runtime error leading to Abstain (4 cases)
    "q_019ec94d9799": ("A", "Step 1, Step 2", "Join 2 bảng cùng có 'Tên hàng' -> KeyError 'Tên hàng' sau join. Step 1 rõ schema, Step 2 probe thấy hậu tố _x/_y -> tính đúng top 3."),
    "q_aacf9543a235": ("A", "Step 1, Step 2", "KeyError amount_x và lỗi kiểu chuỗi/số sau join. Step 1 & Step 2 probe schema và parse đúng kiểu dữ liệu -> ra đúng Vương Phương Loan."),
    "q_e9930d87abdd": ("B", "Step 1, Step 2", "KeyError 'Thời gian' sau join hoá đơn và sổ quỹ. Step 1 tách rõ cột, Step 2 probe join. Cần thêm logic sổ quỹ Rulebook §4 để ra đúng top 5."),
    "q_583e4896e764": ("A", "Step 1, Step 2", "Đọc Thời gian từ bảng chi tiết không có cột này. Step 1 chỉ rõ Thời gian nằm ở bảng Hoá đơn -> model join đúng bảng -> tính đúng 5.79%."),

    # Fuzzy / Vietnamese string (1 case)
    "q_01a28f2233bd": ("A", "Step 2", "So không dấu 'Soda chanh day (M)' làm rỗng data. Step 2 targeted exploration probe tìm thấy 'Soda chanh dây (M)' -> ra đúng 37000."),

    # Regex hoàn trả (1 case)
    "q_2a0e86444947": ("A", "Step 1", "Regex 'trả hàng' bỏ sót nhãn 'Hoàn trả' -> 510 đơn thay vì 507. Step 1 cung cấp đầy đủ nhãn trạng thái có 'Hoàn trả' -> model bắt đủ -> đúng 507."),

    # Prompt ignored (1 case)
    "q_338ae382671b": ("B", "Step 1, Step 2", "Bỏ qua điều kiện tuần trước và lọc sai nhãn. Step 1 giúp đúng nhãn. Nhưng model cần đọc kỹ điều kiện tuần trước."),

    # 4 Correct cases (Baseline already correct)
    "q_1b119bdd5d28": ("A", "None (Baseline)", "Đã đúng từ baseline (2025-08). Không bị ảnh hưởng tiêu cực nếu giữ nguyên logic."),
    "q_725f54f95253": ("A", "None (Baseline)", "Đã đúng từ baseline (2026-07-30). Không bị ảnh hưởng tiêu cực."),
    "q_a264d94a0492": ("A", "None (Baseline)", "Đã đúng từ baseline ('Snack Oishi tôm cay 40g'). Không bị ảnh hưởng tiêu cực."),
    "q_a569fbc6b9fc": ("A", "None (Baseline)", "Đã đúng từ baseline (False). Không bị ảnh hưởng tiêu cực."),
}

stats = {"A": 0, "B": 0, "C": 0, "D": 0}
for qid, (cat, steps, expl) in mapping.items():
    stats[cat] += 1

print(f"Total: {len(mapping)}")
print(f"Category A (Fully Solved / Maintained Correct): {stats['A']}")
print(f"Category B (Partially Solved / Improved / Risk Mitigated): {stats['B']}")
print(f"Category C (Unsolved - requires other mechanisms): {stats['C']}")
print(f"Category D (Worsened / New Risk): {stats['D']}")
