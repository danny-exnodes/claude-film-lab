# Model BytePlus Ark – đối chiếu và lựa chọn

Kiểm tra ngày 2026-11-10 trên tài khoản Ark của Film Lab. Model trong Console phải ở trạng thái **Activated**.

## Model đã kích hoạt

| Tên trên Console | ID trong API | Dùng cho | Đo được (qua proxy cloud) |
|---|---|---|---|
| Dola-Seedream-5.0-lite | `seedream-5-0-lite-260128` | **Ảnh mặc định** (`tools/ark.py image`), chỉ khi **không** `--ref` | 2K: ~25–26 s ✅ · 2K + `--ref`: 502 ở 31 s ❌ · 4K: bị cắt ở 30 s ❌ |
| Dola-Seedream-5.0-flash | `dola-seedream-5-0-flash-260915` | **Lớp tranh sản xuất** (`--fast`), nhất là có `--ref` | 1024²: ~11 s ✅ · 2K/2560x1440 + `--ref`: ~75 ảnh, 0 lần 502 ✅ |
| Dola-Seedream-5.0-pro | `dola-seedream-5-0-pro-260628` | Ảnh chất lượng cao – **chỉ qua Lambda** | 1024² và 2K: luôn > 30 s → 502 ❌ |
| ByteDance-Seedream-4.5 | `seedream-4-5-251128` | Ảnh dự phòng | 2K ✅ |
| ByteDance-Seedream-4.0 | `seedream-4-0-250828`, `seedream-4-0-20260415` | Ảnh dự phòng | 1024²: 7–9 s ✅ |
| Dreamina-Seedance-2.5 | `dreamina-seedance-2-5-260628` | **Video mặc định** | 5 s 720p: ~2,5 phút ✅ (task bất đồng bộ) |

## Lưu ý
- `seedream-5-0-lite-260128` hoạt động nhưng **không xuất hiện** trong `GET /models`.
- `seedream-5-0-260128` và `dreamina-seedance-2-0-*` (mặc định cũ của ark.py) **không có** trong danh sách kích hoạt được
  → lỗi `ModelNotOpen`.
- Không có model LLM/VLM nào được kích hoạt (deepseek, glm, seed-2-x đều `ModelNotOpen`).
- Seedream trả ảnh JPEG; `ark.py` tự chuyển sang PNG khi tên file đuôi `.png`.
- Seedance 2.5 tự thêm âm thanh; `--no-audio` gửi `generate_audio=false` (đã xác minh).
- **Seedance 2.5 image-to-video từ chối `ratio`** (HTTP 400 khi có ảnh khung đầu; ảnh quyết định tỉ lệ, đã xác minh
  khi sản xuất q01t01). Từ nay `ark.py video --image` **không gửi** `ratio`; truyền `--ratio` cùng `--image` chỉ in
  cảnh báo và gửi đúng giá trị đó (API có thể trả 400). Muốn clip 16:9 thì tự làm khung đầu 16:9 (vd. 1280x720,
  `tools/compose/keyframe.py` ra 1920x1080); ảnh vuông cho clip vuông (720p → 960×960). Không có `--image` → `ratio=16:9`.
- Seedance 2.5 `duration`: API nhận **4–30 s** (API kiểm tham số, xác minh 2026-11-10); clip dài hơn 5–8 s chưa thử thực tế.
- Seedream có `--ref` chậm hơn: `seedream-5-0-lite` ở 2K **kèm `--ref`** vượt mốc cắt 30 s của proxy (502 ở 31 s, có thể
  vẫn tính phí); `dola-seedream-5-0-flash` ở 2K/2560x1440 kèm `--ref` chạy ~75 ảnh không một lần 502.
  → **Lớp tranh sản xuất dùng flash (`--fast`)**; lite chỉ dùng khi không có `--ref`.
- Link video (`*.tos-ap-southeast-1.volces.com`) có hạn dùng → tải về ngay (ark.py đã làm).

## Kiểm tra miễn phí
- Video: gửi tham số sai (vd. `resolution: "9999p"`) → `InvalidParameter` = đã kích hoạt, `ModelNotOpen` = chưa.
- Ảnh: **không kiểm miễn phí được** – API ảnh kiểm tham số trước khi kiểm kích hoạt; muốn chắc phải gen 1 ảnh nhỏ.
