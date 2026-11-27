# Model 3D của tập – nguồn và giấy phép

<!-- Mẫu cho method: blender (khâu 3). Chép vào projects/<project>/<thư mục tập>/ASSETS.md (hoặc projects/<project>/
     ASSETS.md cho cả dự án) và điền. check_episode.py: thiếu file là WARN ở khâu 3, ERROR từ khâu 4 (G2).
     Mỗi model một dòng: preset thủ tục của tools/blender/ (giấy phép của repo) hoặc file GLB/glTF. GLB nằm ở
     out/<project>/characters/<c>/ hoặc out/<project>/locations/<l>/ (git bỏ qua; Drive 02_KinhThu/NhanVat|BoiCanh/).
     Không dùng model không rõ giấy phép; giấy phép "không thương mại" thì hỏi người dùng trước.
     Model dựng từ phôi Hunyuan3D 2.1 (comfy.py run hunyuan3d → blender.py mesh-prep, blender-method.md §8): Nguồn =
     file phôi <c>_raw_v<NN>.glb + seed + concept đã duyệt; Tác giả = "Tencent Hunyuan3D 2.1 (phôi) + lab (điêu khắc)";
     Giấy phép = "Tencent Hunyuan 3D 2.1 Community (không áp dụng EU/Anh/Hàn Quốc; thương mại có điều kiện)". -->

| id (mã lớp `A-<id>`) | Nguồn (`preset:<id>` hoặc file GLB) | Tác giả / link | Giấy phép | Ghi chú (sửa gì, tỉ lệ) |
|---|---|---|---|---|
| giot | `preset:giot` | AI Film Lab | theo repo | linh vật, cao 1.0 |

## Asset CC0 (HDRI, texture PBR, model scan) theo shot

<!-- Look realistic: asset trong out/<project>/assets/ (asset_root của shots3d/*.json), tải bằng tools/assets.py
     (plan → người dùng đồng ý → fetch --yes); nguồn, giấy phép, file, dung lượng nằm trong
     out/<project>/assets/ASSETS_MANIFEST.csv. Bảng này chỉ ghi asset nào dùng ở shot nào. -->

| id (trong `ASSETS_MANIFEST.csv`) | Loại (`hdri` / `texture` / `model`) | Nguồn | Shot | Dùng cho (vai trò `materials`, `world.hdri`, asset) |
|---|---|---|---|---|
