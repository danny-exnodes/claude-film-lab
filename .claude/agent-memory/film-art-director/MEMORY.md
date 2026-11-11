# Bộ nhớ film-art-director

Bài học về prompt và lớp tranh, theo style. Mỗi mục: ngày · bài học · cách áp dụng. Giữ dưới 200 dòng; gộp mục trùng.

## Model và giới hạn (2026-11-10, từ docs/MODELS.md, docs/RUNBOOK.md)
- `seedream-5-0-260128` và `dreamina-seedance-2-0-*` → `ModelNotOpen` (chưa kích hoạt). Dùng ID trong `style.yaml` → `models`.
- Proxy cắt request đồng bộ > ~30 s (502). 2K của `seedream-5-0-lite-260128` ~25 s là sát ngưỡng; pro và 4K luôn bị cắt
  → chỉ qua Lambda (đã triển khai 2026-11-10), ở phiên chính: `ark.py lambda-job prepare` → Invoke → `finish`.
  Lớp do plate-maker tạo vẫn viết cho 2K; ảnh cần pro/4K thì ghi rõ trong prompt pack để đạo diễn chạy.
- Seedream không xuất nền trong suốt, trả JPEG (ark.py đổi sang PNG khi tên file `.png`): lớp cần alpha phải vẽ trên nền
  phẳng đúng mã màu của `matte` rồi tách.
- Ảnh đầu vào vuông → video vuông. Khung đầu cho Seedance phải 16:9 (vd. 1280x720); `--ratio` cùng `--image` bị Seedance 2.5 từ chối (HTTP 400).
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

## Bài học G3 v01 Nam Sơn Kinh (2026-11-11)
- Người dùng loại: thú trượt/xoay cắt dán, bộ phận P hiện rời (cánh, đuôi trôi một mình), thú nhỏ chìm cùng tông mực.
  → Thú di chuyển = Seedance; shot bộ phận = zoom code trên L4 thân đầy đủ (ghi điểm x,y, phóng ≤ 2,2×); P chỉ chồng
  khít lên L4. Thú giới thiệu ≥ 40 % cao khung, nền L1/L2 nhạt 40–60 % + mờ, chân chạm L3.
- Seedance (lục) tự cho cánh mọc từ vai, dựng trên lưng, đuôi có chùm lông → prompt: "wings grow from the flanks below
  the ribs, low along the belly, never rise above the back, never from the shoulders; thin scaly snake tail, no tuft".
- Seedance (tinh tinh) "rise and run" → nhảy chồm bốn chân ra khỏi khung: ghi "never leaps, never on all fours, stays
  inside the frame". Thêm "Keep the pale background unchanged", "--no-audio", khung đầu 16:9.
- Clip 5 s + giữ khung tĩnh 6 s bị chê "đứng yên": đặt thời lượng clip ≈ thời lượng shot (≤ 1 s giữ).
- Plate L4 có thể nướng sẵn vầng cam `sun-glow` (toàn quy, lục): thêm "no glow, no sunlight halo" vào prompt L4.

## Ngân sách lớp (2026-11-10, ep01 Nam Sơn Kinh, 87 shot → 58 ảnh lần đầu)
- Một bộ L1/L2/L3 cho mỗi núi, dùng lại 3–7 shot; thẻ chữ và cận bàn viết chung một L1 giấy; bản đồ L1+L2 cho 10 shot.
- Đàn thú phụ = 1 con, nhân bản bằng code (mẫu `character.txt` chỉ cho "one single figure").
- Khung đầu Seedance ghép bằng code từ lớp, không tạo ảnh riêng. P chỉ khi bộ phận đổi tư thế; lay nhẹ = strip-warp trên L4.
