---
# Manifest dự án – docs/CONVENTIONS.md §11.2. Chép vào projects/<project>/PROJECT.md, điền, rồi đẩy lên
# ClaudeFilmLab/<ProjectName>/00_QuanLy/PROJECT.md (file chữ, không chuyển sang Google Doc).
# Claude dùng các ID này với connector Google Drive (create_file parentId=..., search_files parentId = '...'),
# không tìm thư mục theo tên. Tạo thư mục mới → ghi ID vào drive.folders và đẩy lại file này ngay.
project: <project>               # slug ASCII kebab-case: projects/<project>/, out/<project>/, series: trong SERIES.md
title: <Tên dự án>
style: <style-id>                # style mặc định, thư mục styles/<style-id>/ trong repo
drive:
  name: <ProjectName>            # tên thư mục trên Drive, PascalCase không dấu
  lab_root: 19yQarw7ATu90uzXjboGP4sy5FzlQhd0y   # ClaudeFilmLab
  root: <id>                     # ClaudeFilmLab/<ProjectName>
  folders:                       # đường dẫn logic tính từ thư mục dự án -> ID thư mục
    00_QuanLy: <id>
    01_TaiLieuGoc: <id>
    01_TaiLieuGoc/_ChoPhanLoai: <id>
    01_TaiLieuGoc/SachThamKhao: <id>
    01_TaiLieuGoc/NguyenVan: <id>
    01_TaiLieuGoc/HinhAnhThamKhao: <id>
    02_KinhThu: <id>
    02_KinhThu/NhanVat: <id>
    02_KinhThu/BoiCanh: <id>
    02_KinhThu/PhongCach: <id>
    03_KichBan: <id>
    04_SanXuat: <id>
    05_ThanhPham: <id>
    99_LuuTru: <id>
    # Mỗi tập thêm: 03_KichBan/<tập>, .../prompts, .../review, 04_SanXuat/<tập>, 04_SanXuat/<tập>/<YYYY-MM-DD>,
    # 05_ThanhPham/<tập>; <tập> = ep<NN>-<slug>, hoặc q<NN>-t<NN>-<slug> nếu dự án chia quyển (CONVENTIONS §2)
    # Mỗi nhân vật/bối cảnh thêm: 02_KinhThu/NhanVat/<slug>, 02_KinhThu/BoiCanh/<slug>
  files:                         # chỉ file Google cố định (file chữ đổi ID mỗi lần đẩy, §11.6)
    00_QuanLy/README_CauTruc: <id>
    00_QuanLy/TienDo_SanXuat: <id>
---

# <Tên dự án> – manifest

Thư mục Drive: `ClaudeFilmLab/<ProjectName>/` · bản làm việc: `projects/<project>/` (git bỏ qua) ·
media: `out/<project>/` (git bỏ qua). Cấu trúc, ánh xạ đường dẫn và quy tắc kéo/đẩy: `docs/CONVENTIONS.md` §11 trong repo
claude-film-lab.

## Ghi chú quản lý

<!-- Quyết định cấp dự án (đổi style mặc định, thêm thư mục, đổi tên) – mỗi dòng có ngày. -->
