# Model BytePlus Ark – đối chiếu và lựa chọn

Kiểm tra ngày 2026-11-10 trên tài khoản Ark của Film Lab. Model trong Console phải ở trạng thái **Activated**.

## Model đã kích hoạt

| Tên trên Console | ID trong API | Dùng cho | Đo được (qua proxy cloud) |
|---|---|---|---|
| Dola-Seedream-5.0-lite | `seedream-5-0-lite-260128` | **Ảnh mặc định** (`tools/ark.py image`) | 2K: ~25–26 s ✅ · 4K: bị cắt ở 30 s ❌ |
| Dola-Seedream-5.0-flash | `dola-seedream-5-0-flash-260915` | Ảnh nhanh, nháp (`--fast`) | 1024²: ~11 s ✅ · 2K: chưa đo |
| Dola-Seedream-5.0-pro | `dola-seedream-5-0-pro-260628` | Ảnh chất lượng cao – **chỉ qua Lambda** (`ark.py lambda-job`, `lambda/README.md`) | 1024² và 2K: luôn > 30 s → 502 ❌ · qua Lambda: chưa đo (đã triển khai, chờ khóa Ark) |
| ByteDance-Seedream-4.5 | `seedream-4-5-251128` | Ảnh dự phòng | 2K ✅ |
| ByteDance-Seedream-4.0 | `seedream-4-0-250828`, `seedream-4-0-20260415` | Ảnh dự phòng | 1024²: 7–9 s ✅ |
| Dreamina-Seedance-2.5 | `dreamina-seedance-2-5-260628` | **Video mặc định** | 5 s 720p: ~2,5 phút ✅ (task bất đồng bộ); `ark.py video` mặc định `--resolution 720p` (1080p chưa đo) |

## Lưu ý
- `seedream-5-0-lite-260128` hoạt động nhưng **không xuất hiện** trong `GET /models`.
- `seedream-5-0-260128` và `dreamina-seedance-2-0-*` (mặc định cũ của ark.py) **không có** trong danh sách kích hoạt được
  → lỗi `ModelNotOpen`.
- Không có model LLM/VLM nào được kích hoạt (deepseek, glm, seed-2-x đều `ModelNotOpen`).
- Seedream trả ảnh JPEG; `ark.py` tự chuyển sang PNG khi tên file đuôi `.png`.
- Seedance 2.5 tự thêm âm thanh; `--no-audio` gửi `generate_audio=false` (đã xác minh).
- Có `--image` mà không có `--ratio` → gửi `ratio=adaptive` (video theo tỉ lệ ảnh; ảnh vuông 720p → 960×960).
- Link video (`*.tos-ap-southeast-1.volces.com`) có hạn dùng → tải về ngay (ark.py đã làm).

## Kiểm tra miễn phí
- Video: gửi tham số sai (vd. `resolution: "9999p"`) → `InvalidParameter` = đã kích hoạt, `ModelNotOpen` = chưa.
- Ảnh: **không kiểm miễn phí được** – API ảnh kiểm tham số trước khi kiểm kích hoạt; muốn chắc phải gen 1 ảnh nhỏ.
