# Clip Seedance thành một lớp

Dùng khi shot cần cử động mà code không làm được trên ảnh phẳng (quay đầu, đứng dậy, vỗ cánh, bước đi). Mỗi clip
**tính phí**: chỉ tạo khi shot cần (cột `ai_motion` của `shots.csv` không trống) và trong ngân sách của tập.

## 1. Khung đầu (miễn phí)

Ai làm: người đã chốt `place` của shot (compositor ở lượt bố cục, hoặc đạo diễn).

Nhân vật trên **nền key phẳng**, đúng vị trí và cỡ trên sân khấu 1920x1080 như trong phim (máy quay ở trạng thái nghỉ):

```bash
python3 tools/compose/keyframe.py out/<p>/ep<NN>/plates/ep<NN>_s<NN>_L4_<chu-the>_v<NN>.png \
    out/<p>/ep<NN>/clips/ep<NN>_s<NN>_start_v<NN>.png \
    --x <place.x> --y <place.y> --h <place.h> --pivot feet --anchors projects/<p>/ep<NN>-<slug>/anchors.json --key "<matte.key_bg>"
```
- Một màu key cho cả ba bước: giá trị đưa vào `keyframe.py --key` (mặc định `style.yaml matte.key_bg`; đổi sang màu
  còn lại trong `#00FF00`/`#FF00FF` khi `keyframe.py` báo `WARN KEY NEAR SUBJECT`) cũng là màu ghi trong prompt và là
  màu `matte_seq.py` tự dò ra (`--key auto`). Khung ra 16:9 nên clip ra 16:9 (ảnh vuông cho clip vuông, ví dụ 960×960 ở 720p).
- Kiểm tra miễn phí trước khi giao clip: `python3 tools/compose/keyframe.py --check <khung đầu> --key "<màu key>"`
  (thoát 1 nếu không phải 1920x1080, có alpha, viền không phải màu key, hoặc khung không có nhân vật).
- Phương án khác khi shot không cần parallax: chạy Seedance trên **cảnh đã ghép** (một khung `make.py stills` full size),
  clip thành lớp phủ toàn khung (`seq`, depth 1.0, cover: true: cả khung zoom và rung như một bức ảnh; ở depth 0 chỉ còn rung và nghiêng).

## 2. Tạo clip (tính phí; tác vụ bất đồng bộ ~2,5 phút cho 5 s 720p)

Ai làm: film-animator (chạy `keyframe.py --check` trước mỗi lệnh tính phí).

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
  Dòng `failed` có `task_id`: lấy clip về bằng `python3 tools/ark.py video --resume-task <id> --ledger <ledger>` (miễn phí).
  Bị từ chối vì ngân sách (thoát mã 3): báo phiên chính, không tự nâng `budget.yaml`.
- Link video (`*.tos-ap-southeast-1.volces.com`) có hạn: `ark.py` đã tải về ngay.

## 3. Tách nền từng khung

Ai làm: film-animator, ngay sau khi tải clip về (khung đã tách nền + báo cáo); đạo diễn đọc báo cáo và quyết định.

```bash
python3 tools/layers/matte_seq.py out/<p>/ep<NN>/clips/ep<NN>_s<NN>_seedance25_v01.mp4 \
  --start-frame out/<p>/ep<NN>/clips/ep<NN>_s<NN>_start_v01.png --strict \
  --strip /tmp/ep<NN>_s<NN>_strip.png      # ảnh xem thử: để ngoài clips/ (check_episode chỉ nhận tên theo quy ước ở đó)
```
- Một lệnh, một tiến trình: ffmpeg tách khung vào `<tên clip>/raw/`, tách nền chroma (`--key auto`, `--low 40 --high 200`,
  có despill) vào `<tên clip>/000001.png ...`, in các số đo (`bg_dirty`, `flicker`, `area_jitter`, `start IoU`...), các dòng
  WARN (HAZE, FLICKER, CROPPED, EMPTY, BACKGROUND NOT FLAT, REFRAMED, NOT 16:9) và dòng `L4b: ...` để dán vào `PLATES`.
  `--strict`: thoát 4 khi có WARN (khung vẫn được ghi). Ngưỡng WARN mới đo trên khung giả lập: đọc số, đừng chỉ đọc WARN.
- **Không dùng `tools/layers/matte.py` cho khung clip, không `--style/--layer`** (L4 trong style là `rembg`, và không
  có `low/high` thì cả khung phủ một lớp sương nhấp nháy).
- **Chroma key + despill** ổn định theo thời gian; `rembg` từng khung làm viền nhấp nháy giữa các khung, chỉ dùng
  khi nền không phẳng (`WARN BACKGROUND NOT FLAT`): chạy lại với `--method rembg` vào **thư mục khác** rồi so `flicker`
  và `area_jitter` của hai lần chạy.
- Kết quả: `out/<p>/ep<NN>/clips/<tên clip không đuôi>/000001.png ...` (RGBA, cỡ gốc của clip, ví dụ 1280x720: lớp `seq` không `place` tự co phủ sân khấu). Xem ảnh `--strip` (khung đầu, giữa,
  cuối trên nền ca-rô và nền giấy) trước khi dùng.

## 4. Đưa vào phim

Ai làm: compositor (dán dòng `L4b: ...` mà `matte_seq.py` in ra, điền `at`).

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
