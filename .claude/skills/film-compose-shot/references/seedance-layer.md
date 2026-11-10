# Clip Seedance thành một lớp

Dùng khi shot cần cử động mà code không làm được trên ảnh phẳng (quay đầu, đứng dậy, vỗ cánh, bước đi). Mỗi clip
**tính phí**: chỉ tạo khi shot cần (cột `ai_motion` của `shots.csv` không trống) và trong ngân sách của tập.

## 1. Khung đầu (miễn phí)

Nhân vật trên **nền key phẳng**, đúng vị trí và cỡ trên sân khấu 1920x1080 như trong phim (máy quay ở trạng thái nghỉ):

```bash
python3 tools/compose/keyframe.py out/<p>/ep<NN>/plates/ep<NN>_s<NN>_L4_<chu-the>_v<NN>.png \
    out/<p>/ep<NN>/clips/ep<NN>_s<NN>_start_v<NN>.png \
    --x <place.x> --y <place.y> --h <place.h> --pivot feet --anchors projects/<p>/ep<NN>-<slug>/anchors.json --key "<matte.key_bg>"
```
- `--key` lấy từ `style.yaml matte.key_bg`; chọn màu xa màu nhân vật (xanh lá cho mực đen/xám, magenta cho sinh vật
  xanh). Khung ra 16:9 nên clip ra 16:9 (ảnh vuông cho clip vuông, ví dụ 960×960 ở 720p).
- Phương án khác khi shot không cần parallax: chạy Seedance trên **cảnh đã ghép** (một khung `make.py stills` full size),
  clip thành lớp phủ toàn khung (`seq`, `depth` 0, máy quay chỉ còn zoom/rung 2D).

## 2. Tạo clip (tính phí; tác vụ bất đồng bộ ~2,5 phút cho 5 s 720p)

```bash
FILM_AGENT=<tên agent hoặc để trống> python3 tools/ark.py video \
  "<style_block>. <một chuyển động duy nhất, ví dụ: the beast slowly turns its head toward the camera>. Static camera, \
flat <key colour> background stays perfectly uniform, no new objects, same ink-wash style." \
  out/<p>/ep<NN>/clips/ep<NN>_s<NN>_seedance25_v01.mp4 \
  --image out/<p>/ep<NN>/clips/ep<NN>_s<NN>_start_v01.png --duration 5 --resolution 720p --ratio 16:9 --no-audio \
  --ledger out/<p>/ep<NN>/ledger.csv --budget projects/<p>/ep<NN>-<slug>/budget.yaml
```
- Model mặc định `dreamina-seedance-2-5-260628` (`docs/MODELS.md`). Chạy Bash `run_in_background` (hoặc timeout dài).
- Prompt: **một** chuyển động, giữ phong cách, **máy quay tĩnh**, nền key đồng nhất.
- `--no-audio` khi âm thanh do code làm (gần như luôn luôn trong bộ ghép này).
- Thử ở 720p; bản cuối 1080p chỉ khi người dùng duyệt chuyển động (thời gian 1080p chưa đo).
- Bị proxy cắt (502) hay lỗi: ledger ghi `cut-502` / `failed`, **không tự thử lại** (có thể vẫn bị tính phí).
  Bị từ chối vì ngân sách (thoát mã 3): báo phiên chính, không tự nâng `budget.yaml`.
- Link video (`*.tos-ap-southeast-1.volces.com`) có hạn: `ark.py` đã tải về ngay.

## 3. Tách nền từng khung

```bash
mkdir -p out/<p>/ep<NN>/clips/ep<NN>_s<NN>_seedance25_v01/raw
ffmpeg -i out/<p>/ep<NN>/clips/ep<NN>_s<NN>_seedance25_v01.mp4 \
  out/<p>/ep<NN>/clips/ep<NN>_s<NN>_seedance25_v01/raw/%06d.png
python3 tools/layers/matte.py chroma ...   # xem --help: key = matte.key_bg, có despill; ra PNG RGBA cùng tên
```
- **Chroma key + despill** ổn định theo thời gian; `rembg` từng khung làm viền nhấp nháy giữa các khung, chỉ dùng
  khi nền không phẳng.
- Kết quả: `out/<p>/ep<NN>/clips/<tên clip không đuôi>/000001.png ...` (RGBA, cỡ gốc của clip, ví dụ 1280x720: lớp `seq` không `place` tự co phủ sân khấu). Xem 3 khung (đầu, giữa,
  cuối) trước khi dùng: viền xanh còn sót → tăng despill.

## 4. Đưa vào phim

```js
L4b: { seq: { pattern: '../../clips/ep01_s03_seedance25_v01/{n}.png', digits: 6, start: 1, count: 120, fps: 24,
              at: 4.0, end: 'hold' }, depth: 1.0, cover: false },
```
- Không `place`: chuỗi phủ sân khấu đúng như khung đầu, nên khớp vị trí với L4.
- Trong hàm shot: `if (t < 4.0) st.plate('L4', {...}); else st.plate('L4b');`. Đưa rig của L4 về nghỉ trong 0,5 s
  trước điểm chuyển (SKILL.md §3). Khung đầu của clip gần như trùng L4 nên cú chuyển không lộ.
- Mọi khung được nạp và giải mã trước READY (120 khung 720p ≈ 450 MB bộ nhớ đã giải mã, 1080p ≈ 1 GB): clip dài hơn 5 s thì cắt ở
  đoạn cần dùng (`count` nhỏ lại) hoặc thu nhỏ khung khi tách nền.
- Ghi clip vào `prompts.csv` (CONVENTIONS §6: `file`, `shot`, `layer` = `L4`, `model`, `usage` nguyên văn).
