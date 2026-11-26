# Render 3D tại chỗ bằng Blender (`tools/blender/`)

Dựng shot từ model 3D và render bằng **Blender 5.x chạy nền (headless)** trên máy của chủ dự án: cảnh mô tả trong một
file `shot3d.json` (asset, chuyển động máy, look, ánh sáng) → chuỗi PNG + `beauty.mp4` + các pass điều khiển (depth,
normal, line, mask) + `render.json`. **Miễn phí, local**: không API, không mạng, không tính vào trần ngân sách. Thiết kế:
`docs/superpowers/specs/2026-11-25-local-engines-design.md` §4.3; nghiên cứu: `docs/superpowers/research/2026-11-25-blender-comfyui.md` §B.

| File | Chạy ở đâu | Việc |
|---|---|---|
| `blender.py` | Python ngoài Blender (Windows 3.12–3.14, Linux 3.12; chỉ thư viện chuẩn) | CLI: `find`, `check`, `render`, `still`, `turntable`, `keyframes`, `lookbook` |
| `spec.py` | cả hai phía (Python của Blender là 3.13) | kiểm `shot3d.json` (lỗi dạng `đường dẫn: lý do`), giá trị mặc định, số khung, toán đường máy quay |
| `scene.py` | trong Blender | dựng cảnh từ spec, đặt máy quay từng khung, compositor, render, ghi `render.json` |
| `looks.py` + `looks.json` | trong Blender | vật liệu, world, mặt trời, quản lý màu, nét mực Freestyle theo look |
| `presets.py` | trong Blender | asset thủ tục: `mountains`, `rocks`, `pines`, `water`, `ground`, `giot` |
| `demo/*.json` | | ba shot mẫu nhỏ (xem dưới) |

## Chạy ở đâu

- Chỉ trên **máy Windows của chủ dự án** trong phiên Claude Code local (RTX 5070 Ti). Phiên cloud không có Blender:
  `blender.py find` thoát 1, các test render thật tự bỏ qua.
- Tìm Blender theo thứ tự: `$FILM_BLENDER` (đặt mà sai đường dẫn là lỗi, không tìm tiếp) → `blender` trên PATH → bản mới
  nhất `C:\Program Files\Blender Foundation\Blender */blender.exe` → `/Applications/Blender.app/Contents/MacOS/Blender`
  → `/usr/bin/blender`.
- Blender luôn chạy đúng một kiểu: `blender -b --factory-startup --python-exit-code 1 -P tools/blender/scene.py -- --spec S --out D [...]`
  (`--factory-startup`: không đọc cài đặt người dùng, kết quả lặp lại được; lỗi Python → mã thoát 1).
- **EEVEE** (mặc định) cần GPU trong phiên desktop đang đăng nhập. Nếu EEVEE hỏng sau khi cảnh đã dựng mà chưa ra khung
  nào, `blender.py` tự render lại bằng **Cycles** (OptiX → CUDA → CPU) và ghi `fallback` vào `render.json`.
  `--engine cycles` chọn Cycles ngay; `FILM_BLENDER_DEVICE=CPU|OPTIX|CUDA` ép thiết bị của Cycles.
- Đừng chạy Blender GPU cùng lúc với một job ComfyUI (16 GB VRAM dùng chung).

## Lệnh

```bash
python tools/blender/blender.py find                                    # đường dẫn + phiên bản (thoát 1 khi không có, 3 khi hỏng)
python tools/blender/blender.py check tools/blender/demo/ink-wash-mountains.json   # chỉ kiểm spec, không cần Blender
python tools/blender/blender.py render <shot3d.json> --out <thư mục> --preview      # bản nháp 960 ngang, 12 fps, ít sample
python tools/blender/blender.py render <shot3d.json> --out <thư mục>               # bản cuối theo spec (1920x1080, 24 fps)
python tools/blender/blender.py render <shot3d.json> --out <thư mục> --frames 1:24 --engine cycles --passes depth mask
python tools/blender/blender.py still <shot3d.json> --frame 60 --out <file>.png [--size 1344x768] [--look clay]
python tools/blender/blender.py keyframes <shot3d.json> --out <thư mục> [--size 864x480]   # first.png + last.png + keyframes.json
python tools/blender/blender.py turntable preset:giot --out <thư mục> --look clay [--seconds 4] [--preview]
python tools/blender/blender.py turntable <model>.glb --out <thư mục>
python tools/blender/blender.py lookbook --out <thư mục> [--spec S] [--frame N] [--size 960x540]
```

- Mã thoát: **0** xong · **1** không tìm thấy Blender hoặc render lỗi (in 15 dòng cuối của Blender) · **2** bị từ chối
  trước khi render (spec sai, tham số sai, `--out` không trống) — chưa chạy gì · **3** (chỉ `find`) thấy Blender nhưng
  `--version` lỗi hoặc không in phiên bản (bản cài hỏng; `doctor.sh` báo WARN).
- **Không ghi đè**: `--out` phải chưa có hoặc là thư mục trống; `still --out` phải là file chưa có. Bản mới → thư mục/tên
  mới (`_v02`).
- Mọi lệnh render nhận `--engine eevee|cycles`, `--look <id>` (đè look của spec), `--dry-run` (in lệnh Blender, không
  render), `--timeout <giây>`. `render` nhận thêm `--frames A:B` hoặc `A,B,C`, `--passes ...|none`, `--samples N`, `--no-mp4`.
- `--size WxH` (still, keyframes, turntable, lookbook) đổi khung hình mà **giữ nguyên trường nhìn dọc** của spec (đổi
  sensor fit của máy quay, không cắt ảnh sau khi render). `keyframes` mặc định `1344x768` = khung của model video local
  (7:4, 24 fps; bản nháp `864x480`); `keyframes.json` ghi sha256 của spec, kích thước, số khung, thời điểm và độ dài shot.
- `beauty.mp4` (H.264): bằng `ffmpeg` nếu có trên PATH (hoặc `$FILM_FFMPEG`), không thì bằng bộ mã hoá FFmpeg có sẵn trong
  Blender; `--no-mp4` bỏ qua. Chỉ làm khi các khung liền nhau.

## Đầu ra (`--out`)

| Đường dẫn | Nội dung |
|---|---|
| `beauty/0001.png …` | khung đẹp, RGB 8-bit, số khung từ 1 |
| `depth/` | 16-bit xám: `depth_range` cố định của spec, **gần = trắng**, xa và trời = đen; không chuẩn hoá theo từng khung (tránh "thở") |
| `normal/` | 16-bit RGB, không gian máy quay kiểu OpenGL (x phải, y lên, z về phía người xem; `n·0.5+0.5`; trời = (0.5, 0.5, 1)) |
| `line/` | 8-bit xám: nét đen trên nền trắng, tách từ chỗ gãy của normal và chỗ nhảy của log-depth (cùng kiểu cho mọi look) |
| `mask/<asset>/` | 8-bit xám: phần nhìn thấy của từng asset (`"mask": false` để bỏ) |
| `beauty.mp4` | xem trên |
| `render.json` | sha256 spec, phiên bản Blender, engine, thiết bị, look, kích thước, fps, khung, sample, seed, pass, giây/khung |

Pass là dữ liệu thô (không view transform, không đường cong sRGB). Cùng spec + cùng máy → cùng byte (seed và số sample cố
định; test `test_blender_render` kiểm điều này).

## `shot3d.json` (version 1)

Toạ độ của Blender: mét, **Z hướng lên**, mặt đất là mặt XY; máy quay ở `y < 0` nhìn về `+y` thấy cảnh từ phía trước.
Góc theo độ. Ví dụ đầy đủ: `tools/blender/demo/ink-wash-mountains.json`.

- Gốc: `version` (= 1), `size` [w, h] (chẵn), `fps`, `seconds`, `seed`, `look`, `engine` (`eevee|cycles`), `world`,
  `assets`, `camera`, `passes` (`depth, normal, line, mask`), `depth_range` [gần, xa], tuỳ chọn `samples`, `title`, `note`,
  `asset_root` (thư mục asset CC0, tương đối với file spec: `hdri/`, `textures/<id>/`, `models/`; vd.
  `out/<project>/assets/`), `materials` (look `realistic`: vai trò preset `mountain, rock, ground, water, trunk, foliage,
  prim` → id bộ texture trong `asset_root/textures/` hoặc thư mục, hoặc `{tex, scale, displace}`: `scale` mét mỗi ô lặp,
  mặc định 4; `displace` mét, Cycles).
- `world`: `paper`, `ink` (màu `#rrggbb`, đè màu của look), `mist` (0–1), `mist_range` [bắt đầu, hết] mét, `sun`
  [độ cao, phương vị] (phương vị 0 = từ phía sau cảnh, 90 = từ bên phải, 180 = từ phía máy quay, 270 = từ bên trái);
  look `realistic`: `hdri` (id trong `asset_root/hdri/` hoặc đường dẫn `.hdr/.exr`; không có = trời vật lý theo `sun`),
  `hdri_strength` (0–20, mặc định 1), `hdri_rot` (độ, xoay trời quanh Z), `sun_strength` (0–50; 0 = không đèn mặt trời).
- `assets[]`: `id`, `src` = `preset:<id>` | `prim:<cube|sphere|ico|cylinder|cone|plane|torus>` | đường dẫn `.glb/.gltf`
  | `<file>.blend` hoặc `<file>.blend#<Collection>` (append mọi object hoặc một collection, giữ vật liệu, modifier,
  geometry nodes, hair curves; tương đối với file spec), `at`, `rot`, `scale`, `fit` (co asset cho cạnh lớn nhất bằng `fit` mét, đặt đứng trên z = 0),
  `color`, `ink` (0–1, độ đậm mực ở look ink-wash), `lines` (false = không nét mực), `mask`, `params` (tham số preset),
  `anim`: `action` (preset: `giot` có `idle, hop, walk, wave`; `pines` có `sway`; `.glb`: tên action trong file; không ghi `action` thì model `.glb` đứng yên),
  `path` [[t, [dx, dy, dz]], …] (độ lệch so với `at`), `ease`, `face_path` (quay mặt theo hướng đi, mặc định bật), `speed`.
- `camera`: `move` (`static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track` — cùng nghĩa với
  `tools/toon/project.js`), `from`, `target` (id asset hoặc [x, y, z]), `aim` (độ lệch điểm nhìn; mặc định nửa chiều cao
  của preset/asset `fit`), `to`, `lens` (mm, sensor 36 mm), `lens_to`, `roll`, `ease` (`linear, in, out, inout, sine`),
  `t` [bắt đầu, hết] giây (mặc định cả shot, kết thúc đúng ở khung cuối), và theo từng move: `amount` (push-in/pull-out,
  mặc định 0.3 quãng đường), `degrees` (pan 20, tilt 10, orbit 30; dương = sang trái / lên / ngược chiều kim đồng hồ),
  `target_to` (pan/tilt), `rise` (crane, mặc định 2 m). `dolly` cần `to`; `track` cần asset có `anim.path` hoặc `to`.

## Look (`looks.json`)

| id | Dùng cho |
|---|---|
| `grey-layout` | khối xám phẳng: bố cục, máy quay, chuyển động — đầu vào cho cầu nối AI (model video local) |
| `clay` | đất nặn có màu của asset, ánh sáng mềm: turntable, duyệt asset (G2) |
| `toon-ink` | tô phẳng ba tông + nét mực đặc trên giấy ấm |
| `ink-wash` | bản 3D của `styles/thuy-mac`: giấy dó `#EFE6D3`, mực phân tầng theo bóng, vệt bút (披麻皴 trên núi, 斧劈皴 trên đá), mép loang, nét mảnh vuốt hai đầu nhạt dần theo xa, sương theo độ sâu và dưới chân núi, vân giấy |
| `realistic` | chân thực (Cycles): trời HDRI (`world.hdri`) hoặc trời vật lý, đèn mặt trời ấm dần khi thấp, AgX Medium High Contrast, adaptive sampling 0,02, motion blur 0,5 khung; **giữ vật liệu của asset** (GLB quét, `.blend` có lông), preset nhận PBR theo `materials`; không nét. Style `chan-thuc-blender` |

EEVEE lấy độ sáng bằng Shader to RGB (có bóng đổ). Cycles không có Shader to RGB nên ở ba look tô phẳng ánh sáng là N·L
của mặt trời (không bóng đổ): bảng màu giữ nguyên, bóng đổ thì không.

## Asset thủ tục (`presets.py`)

`mountains` (`width, depth, height, peaks, sharp, detail, res, seed`: dãy núi dựng đứng kiểu sơn thuỷ, có vai núi chen
quanh đỉnh, nếp gấp toả xuống, chân chìm xuống đất; nét mực chỉ vẽ phần trên chân sương), `rocks` (`count, spread, size,
seed`: đá tảng mặt vát), `pines` (`count, spread, height, seed`: thông thủy mặc, thân cong, tán là các chùm kim xoè),
`water` (`width, depth`), `ground` (`width, depth, relief, seed`), `giot` (`body, cheek`: linh vật Giọt theo
`tools/toon/demo/giot.json`). Hình học là hàm thuần của tham số + seed.

## Shot mẫu (`demo/`)

- `ink-wash-mountains.json`: ink-wash, push-in về phía Giọt giữa núi xa núi gần, hồ, đá, thông, sương; đủ bốn pass.
- `giot-walk.json`: toon-ink, Giọt đi ngang (action `walk` + `path`), máy `track` theo.
- `lookbook.json`: khung tĩnh có mọi preset, dùng cho `blender.py lookbook`.

Look `realistic` không đổi vật liệu asset mang theo, chỉ thêm các AOV điều khiển (`film_normal`, `film_cover`,
`film_m<k>`) nên pass depth/normal/line/mask vẫn có như mọi look. Đo 2026-11-26: 1920x1080, Cycles OptiX, 256 sample
adaptive, núi + nước + đá quét GLB + thông `.blend` + HDRI ≈ 15 giây/khung.

## Thời gian đo được (RTX 5070 Ti, Blender 5.3, EEVEE)

Shot `ink-wash-mountains`: 1920x1080 ≈ 1.8 giây/khung (cả bốn pass), `--preview` 960x540 ≈ 1.5 giây/khung. Lần render đầu
sau khi đổi shader mất thêm 1–2 phút để EEVEE biên dịch shader (có cache cho các lần sau).

## Test

- `tests/test_blender.py` (WSL, không cần Blender/GPU): kiểm spec, toán máy quay, CLI với Blender giả ghi lại argv.
- `tests/test_blender_render.py`: render thật 64x36, 3 khung; tự bỏ qua khi không có Blender. Chạy trên Windows:
  `cd tests && python -m unittest test_blender_render -v`.
