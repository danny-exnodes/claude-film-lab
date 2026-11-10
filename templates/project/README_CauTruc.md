# <ProjectName> – cấu trúc thư mục dự án

<!-- Mẫu cho Google Doc 00_QuanLy/README_CauTruc: thay <ProjectName>, <Tên dự án>, rồi tải lên với
     contentMimeType text/markdown và để Drive chuyển sang Google Doc (docs/CONVENTIONS.md §11.5). -->

Thư mục này chứa **toàn bộ dữ liệu của dự án phim <Tên dự án>**: tài liệu gốc, kinh thư, kịch bản, sản phẩm.
Claude làm việc trên một bản sao tạm trong phiên và đẩy lại lên đây sau mỗi khâu; **bản trên Drive là bản chính**.
Kho mã (GitHub `claude-film-lab`) chỉ chứa công cụ và quy trình dùng chung, không chứa dữ liệu dự án.

## Các thư mục

| Thư mục | Chứa gì | Bạn làm gì |
|---|---|---|
| `00_QuanLy/` | `PROJECT.md` (sơ đồ ID cho Claude, đừng sửa tay), tài liệu này, bảng `TienDo_SanXuat` (mỗi tập một dòng) | xem tiến độ |
| `01_TaiLieuGoc/_ChoPhanLoai/` | hộp thư đến | **thả tài liệu mới vào đây**; Claude đặt tên và chuyển vào đúng chỗ |
| `01_TaiLieuGoc/SachThamKhao/` | ảnh chụp, scan sách, mỗi cuốn một thư mục | – |
| `01_TaiLieuGoc/NguyenVan/` | nguyên văn, chú giải, bản dịch (kèm link nguồn) | – |
| `01_TaiLieuGoc/HinhAnhThamKhao/` | ảnh tham khảo không khí – **không** dùng để tạo ảnh, không đưa vào phim | – |
| `02_KinhThu/` | `SERIES.md` (quy ước chung), `NhanVat/` và `BoiCanh/` (mô tả + ảnh khóa đã duyệt), `PhongCach/` | duyệt ảnh khóa |
| `03_KichBan/ep<NN>-<slug>/` | trạng thái tập `EPISODE.md`, ngân sách, nghiên cứu, kịch bản, shot list, prompt, kiểm tra | duyệt kịch bản (G1) |
| `04_SanXuat/ep<NN>-<slug>/<ngày>/` | gói ảnh/clip theo shot, bản nháp, sổ chi phí `ledger.csv` | duyệt shot mẫu (G2), bản nháp (G3) |
| `05_ThanhPham/ep<NN>-<slug>/` | bản cuối, thumbnail, nội dung đăng | duyệt bản cuối (G4), tự đăng |
| `99_LuuTru/` | bản cũ và thứ bỏ đi | không xoá gì: mọi thứ cũ nằm ở đây |

## Quy tắc

- **Không xoá** file nào: thứ không dùng nữa chuyển vào `99_LuuTru/`. Bản cũ của một file chữ được Claude chuyển vào
  đó với tên `<thư mục>__<tên>_<YYYYMMDD-HHMM>.<đuôi>` mỗi khi có bản mới.
- Tài liệu gốc đặt tên `<masach>_<noidung>_<NN>_<chitiet>.<đuôi>`, chữ thường không dấu
  (vd. `abc-banminhhoa_mucluc_03_tr002-003.jpg`). Không cần tự đặt: thả vào `_ChoPhanLoai/` là đủ.
- File chữ (`.md`, `.csv`, `.yaml`) để nguyên dạng, đừng mở bằng Google Docs rồi lưu đè: Claude cần đọc lại y nguyên.
  Muốn góp ý: viết vào chat, hoặc sửa trực tiếp rồi báo Claude ở phiên sau để gộp.
- Mỗi lần Claude tải file lên, bạn được hỏi duyệt.
