# Bộ nhớ film-art-director

Bài học về prompt và lớp tranh, theo style. Mỗi mục: ngày · bài học · cách áp dụng. Giữ dưới 200 dòng; gộp mục trùng.

## Model và giới hạn (2026-11-10, từ docs/MODELS.md, docs/RUNBOOK.md)
- `seedream-5-0-260128` và `dreamina-seedance-2-0-*` → `ModelNotOpen` (chưa kích hoạt). Dùng ID trong `style.yaml` → `models`.
- Proxy cắt request đồng bộ > ~30 s (502). 2K của `seedream-5-0-lite-260128` ~25 s là sát ngưỡng; pro và 4K luôn bị cắt
  → chỉ qua Lambda (v1.0.0 chưa triển khai). Viết prompt cho 2K.
- Seedream không xuất nền trong suốt, trả JPEG (ark.py đổi sang PNG khi tên file `.png`): lớp cần alpha phải vẽ trên nền
  phẳng đúng mã màu của `matte` rồi tách.
- Ảnh đầu vào vuông + `ratio=adaptive` → video vuông. Khung đầu cho Seedance nên 16:9.
- `rembg` cắt mất vệt mực loang và gradient nhạt: lớp mực (L2/L3 thủy mặc) dùng `luminance`, chỉ L4/P dùng `rembg`.

## Prompt
- Đặc điểm từ nguồn viết HOA, có số bằng chữ (NINE TAILS, FOUR EARS); thêm phủ định cho lỗi hay gặp (NO EYES ON THE FACE).
- Không vẽ sương, khói, tàn lửa vào tranh; ghi rõ "no mist or halo around the outline".
