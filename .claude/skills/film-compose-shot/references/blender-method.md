# Phương pháp `blender`: model 3D render bằng Blender trên máy của chủ lab

Đọc file này khi `EPISODE.md` của tập ghi `method: blender`. Không gọi model tạo ảnh nào: `budget.yaml` có `images: 0`;
`video_seconds: 0` trừ khi tập ghi `video_engine: seedance` và có shot `ai_motion` (clip Seedance trả tiền). Không
`prompts.csv`, không `plates/`. Mỗi shot là một file `shot3d.json`; Blender render ra chuỗi PNG + mp4 + các lớp điều
khiển (độ sâu, pháp tuyến, nét, mặt nạ). Render miễn phí, chỉ tốn thời gian GPU.

**Chỉ chạy được trong phiên local trên máy của chủ lab** (Windows, RTX, Blender 5.3). Phiên cloud không có GPU, không có
Blender: ở đó chỉ làm việc chữ (kịch bản, shot list, `shots3d/*.json`, `ASSETS.md`) và kiểm tra (`check_episode.py` báo
WARN khi tập `blender` mở trong phiên cloud). `tools/doctor.sh` dòng `blender`: `n/a` ở cloud, `OK` khi tìm thấy Blender.

## 1. Công cụ (`tools/blender/`, chi tiết `tools/blender/README.md`)

```
python tools/blender/blender.py find                                  # đường dẫn + phiên bản (mã 1 = không thấy, 3 = thấy mà hỏng)
python tools/blender/blender.py check <shot3d.json>                   # chỉ kiểm spec, không mở Blender
python tools/blender/blender.py render <shot3d.json> --out <dir> [--preview] [--frames A:B] [--engine eevee|cycles]
python tools/blender/blender.py still <shot3d.json> --frame N --out <png>
python tools/blender/blender.py turntable <asset.glb|preset:id> --out <dir> [--look L]
python tools/blender/blender.py keyframes <shot3d.json> --out <dir>   # khung đầu + khung cuối → clip H3 nối hai khung
python tools/blender/blender.py lookbook --out <dir>                  # một khung mỗi look
```
- `--out` phải chưa có hoặc rỗng: không ghi đè. Render lại = thư mục mới `_v<NN>` (§3).
- `--preview` = 960×540, 12 hình/s, ít sample: dùng cho shot mẫu G2 và thử bố cục.
- Blender tìm theo `FILM_BLENDER`, rồi PATH, rồi thư mục cài mặc định. Chạy Blender: `-b --factory-startup`, mã thoát
  khác 0 khi script lỗi.
- Một việc GPU một lúc: không render Blender cùng lúc với một clip ComfyUI (16 GB VRAM).

## 2. `shot3d.json` (`<tập>/shots3d/s<NN>.json`)

Dữ liệu dự án (chữ, đẩy Drive như `shots.csv`). Schema phiên bản 1, kiểm bằng `tools/blender/spec.py`
(`blender.py check`; `check_episode.py` gọi cùng module khi nó có trong repo). Mẫu: `templates/episode/shot3d.json`.

| Khóa | Ý nghĩa |
|---|---|
| `version`, `size`, `fps`, `seconds`, `seed` | `1`; `[1920, 1080]`; 24; **bằng độ dài shot trong `shots.csv`** (lệch → WARN); seed cố định |
| `look`, `engine` | look của style (`render.look`), `eevee` (mặc định) hoặc `cycles` |
| `world` | `paper` (màu giấy/trời), `mist` (0–1), `sun` `[độ cao, hướng]`; look `realistic`: `hdri`, `hdri_strength`, `hdri_rot`, `sun_strength` |
| `asset_root`, `materials` | look `realistic`: thư mục asset CC0 (`out/<project>/assets/`: `hdri/`, `textures/<id>/`, `models/`) và bộ texture PBR theo vai trò preset (`mountain`, `rock`, `ground`, `water`, `trunk`, `foliage`, `prim`) |
| `assets[]` | `id` (= mã lớp `A-<id>`), `src` (`preset:<id>`, `prim:<cube\|sphere\|...>`, đường dẫn `.glb/.gltf` hoặc `<file>.blend[#Collection]` tính từ file spec; `.blend` giữ hair curves và geometry nodes), `at`, `rot`, `scale`, `anim` (`action`, `path` `[[giây, [x, y, z]], ...]`) |
| `camera` | `move` (**bằng cột `camera` của `shots.csv`**, lệch → WARN), `from`, `to`, `target` (id asset), `lens`, `ease` |
| `passes`, `depth_range` | `depth`, `normal`, `line`, `mask`; khoảng độ sâu cố định cho cả shot (gần = trắng, không chuẩn hoá từng khung) |

Preset thủ tục: `mountains`, `rocks`, `pines`, `water`, `ground`, `giot` (linh vật của lab). Model GLB ghi nguồn và
giấy phép trong `ASSETS.md`; file GLB là media: `out/<project>/characters/<c>/` hoặc `out/<project>/locations/<l>/` (Drive
`02_KinhThu/NhanVat/<c>/`, `02_KinhThu/BoiCanh/<l>/`), `src` trỏ tới nó bằng đường dẫn tương đối từ file spec.

## 3. Đặt tên đầu ra (`out/<project>/<id>/renders3d/`)

| Thư mục | Lệnh |
|---|---|
| `s<NN>/` (render lại: `s<NN>_v02/`…) | `render shots3d/s<NN>.json --out ...` – bản dùng để dựng |
| `s<NN>_preview/` (`_preview_v02/`…) | `render ... --preview` – shot mẫu, thử bố cục |
| `s<NN>_keys/` | `keyframes` – khung đầu/cuối cho clip H3 |
| `turntable-<asset>/` | `turntable` – duyệt model ở G2 |

Trong mỗi thư mục: `beauty/0001.png…`, `depth/`, `normal/`, `line/`, `mask/<asset>/`, `beauty.mp4` (khi có ffmpeg),
`render.json` (mã băm spec, phiên bản Blender, engine, thiết bị, giây mỗi khung). `check_episode.py` WARN khi tên lạ và
ERROR từ khâu 7 khi một shot không dùng lại (`reuse_of` trống) chưa có render bản dùng (`s<NN>/` hay `s<NN>_v<NN>/`).
Lần chạy Blender ghi vào ledger như mọi lần tạo (model `blender:*`, không tính vào trần nào).

**Lưu Drive (gói shot).** `python3 tools/bundle.py out/<project>/<id> --shot s<NN>` gói mọi thư mục
`renders3d/s<NN>[_v<NN>|_preview|_keys]/` của shot, chỉ file cấp đầu: `beauty.mp4` (bản compositor dựng), `render.json`,
và với `_keys`: `first.png`, `last.png`, `keyframes.json`. Thư mục khung PNG (`beauty/`, `depth/`, `normal/`, `line/`,
`mask/`) không vào gói: ~3 MB mỗi khung 1080p, vài trăm MB mỗi shot, compositor chỉ cần `beauty.mp4`, và render lại từ
`shots3d/s<NN>.json` cho cùng khung (cùng spec, cùng máy → cùng byte). Ngoại lệ: render `--no-mp4` thì `beauty/` vào gói
(đó là hình duy nhất); cần đủ khung thì thêm `--with-frames`. Ở G2 thêm `--with-turntables` vào gói của shot mẫu để
kèm `renders3d/turntable-<asset>/`. Khôi phục (container mới, `check_episode` báo thiếu render): kéo gói từ Drive, giải
nén ngay trong `out/<project>/<id>/` → file về đúng `renders3d/<thư mục>/` và shot được tính là đã render.

## 4. Khâu theo phương pháp `blender`

| Khâu | Việc |
|---|---|
| 0 | người dùng chọn `method: blender` và một style `engine: blender` (`thuy-mac-blender`, `toon-3d-blender`, `chan-thuc-blender` cho hình chân thực); có cử động khó thì chọn thêm `video_engine: comfy` (clip H3 local, miễn phí) hoặc `seedance` (trả tiền); `budget.yaml`: `images: 0` |
| 2 | `film-writer` viết `shots.csv` theo §5 |
| 3 | `film-3d-artist`: model (preset hoặc GLB có giấy phép) + `ASSETS.md` + bản nháp `shots3d/s<NN>.json` (`blender.py check` sạch) |
| 4 | `film-3d-artist`: `turntable` mỗi model chính + một shot mẫu `render --preview` → **G2** (`status.py --gate G2`: turntable, shot mẫu, không vượt trần); duyệt xong: `bundle.py … --shot <shot mẫu> --with-turntables` (§3) |
| 5 | `film-3d-artist`: `render` mọi shot không dùng lại (`renders3d/s<NN>/`); Nhật ký ghi phút GPU; mỗi shot duyệt: `bundle.py … --shot s<NN>` (§3) |
| 6 | chỉ khi có `ai_motion`: `video_engine: comfy` → `film-animator` chạy `comfy.py run h3-i2v` với khung `keyframes` (`local-video.md`); `seedance` → như tập `seedance`; không có thì bỏ qua (Nhật ký: `khâu 6 bỏ qua`) |
| 7–10 | `film-compositor` dùng `beauty/` (chuỗi PNG) hoặc `beauty.mp4` như một clip; sương, nắng, chữ bằng compose kit; âm thanh như mọi tập |

## 5. `shots.csv` của tập `blender`

- `layers`: `A-<asset>` (model 3D: preset hoặc GLB, id trong `shot3d.json`), `E-<bối cảnh>`, `FX` hoặc `FX-<hiệu ứng>`,
  `T` (chữ trên hình). Không `L1–L4`/`P`/`C-`.
- `camera`: đúng một tên chuyển động của `shot3d.json`: `static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track`.
- `code_motion`: hiệu ứng compose phủ lên render (`mist-bands`, `embers`, `sun-glow`…); id rig lớp tranh (`cloth`,
  `strip-warp`…) và hành động TOON là WARN.
- `ai_motion`: chỉ khi `EPISODE.md` ghi `video_engine:` (thiếu → ERROR); mô tả **một** cử động mà Blender không làm
  được (con thú bước, quay đầu).

## 6. Kiểm trước G2 và G3 (thêm vào danh sách chung)

- [ ] `check_episode.py` sạch (kể cả `shots3d/`, `ASSETS.md`); `status.py` FORECAST: 0 ảnh, giây video đúng dự kiến,
      phút GPU local (ước lượng).
- [ ] Model trong turntable đúng `ASSETS.md` (nguồn, giấy phép); tỉ lệ giữa các model hợp lý (linh vật `giot` cao 1.0).
- [ ] Không vật nào xuyên đất, không trượt (model có chân đi bằng `anim.action`; preset không chân chỉ trôi/bay/đứng).
- [ ] Mọi shot có render bản dùng; cùng look, cùng engine, cùng `seed` như shot mẫu đã duyệt.
