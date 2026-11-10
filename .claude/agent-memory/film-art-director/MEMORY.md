# Bộ nhớ film-art-director

Bài học về prompt và lớp tranh, theo style. Mỗi mục: ngày · bài học · cách áp dụng. Giữ dưới 200 dòng; gộp mục trùng.

## Model và giới hạn (2026-11-10, từ docs/MODELS.md, docs/RUNBOOK.md)
- `seedream-5-0-260128` và `dreamina-seedance-2-0-*` → `ModelNotOpen` (chưa kích hoạt). Dùng ID trong `style.yaml` → `models`.
- Proxy cắt request đồng bộ > ~30 s (502). 2K của `seedream-5-0-lite-260128` ~25 s là sát ngưỡng; pro và 4K luôn bị cắt
  → chỉ qua Lambda (đã triển khai 2026-11-10), ở phiên chính: `ark.py lambda-job prepare` → Invoke → `finish`.
  Lớp do plate-maker tạo vẫn viết cho 2K; ảnh cần pro/4K thì ghi rõ trong prompt pack để đạo diễn chạy.
- Seedream không xuất nền trong suốt, trả JPEG (ark.py đổi sang PNG khi tên file `.png`): lớp cần alpha phải vẽ trên nền
  phẳng đúng mã màu của `matte` rồi tách.
- Ảnh đầu vào vuông + `ratio=adaptive` → video vuông. Khung đầu cho Seedance nên 16:9.
- `rembg` cắt mất vệt mực loang và gradient nhạt: lớp mực (L2/L3 thủy mặc) dùng `luminance`, chỉ L4/P dùng `rembg`.

## Prompt
- Đặc điểm từ nguồn viết HOA, có số bằng chữ (NINE TAILS, FOUR EARS); thêm phủ định cho lỗi hay gặp (NO EYES ON THE FACE).
- Không vẽ sương, khói, tàn lửa vào tranh; ghi rõ "no mist or halo around the outline".
- 2026-11-10 · Vật trắng (băng, chiếu cỏ, hoa, cuộn giấy) trên lớp `luminance` (L2/L3) sẽ trong suốt → luôn viết
  "toned light grey, never pure white". Thân trắng trên L4 `rembg` (đầu, tai, vượn trắng) → phủ xám nhạt + viền đậm.
- 2026-11-10 · Thủy mặc chưa có mẫu cận cảnh/nội thất/bản đồ: `character.txt` ("Full body") cho close-up và `bg.txt`
  ("landscape") cho phòng/giấy là mâu thuẫn → ghi ràng buộc "close-up of the same creature… only the head" /
  "an interior scene, not a landscape", nháp `--fast` trước; đề nghị đạo diễn thêm `closeup.txt` vào style pack.
- 2026-11-10 · `mid.txt` có "no animals": lớp bóng thú (rùa dưới nước) gọi là "dark soft oval shadows shaped like…".

## Ngân sách lớp (2026-11-10, ep01 Nam Sơn Kinh, 87 shot → 58 ảnh lần đầu)
- Một bộ L1/L2/L3 cho mỗi núi, dùng lại 3–7 shot; thẻ chữ và cận bàn viết chung một L1 giấy; bản đồ L1+L2 cho 10 shot.
- Đàn thú phụ = 1 con, nhân bản bằng code (mẫu `character.txt` chỉ cho "one single figure").
- Khung đầu Seedance ghép bằng code từ lớp, không tạo ảnh riêng. P chỉ khi bộ phận đổi tư thế; lay nhẹ = strip-warp trên L4.
