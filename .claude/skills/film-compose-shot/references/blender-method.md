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
- Một việc GPU một lúc: không render Blender cùng lúc với một clip ComfyUI (16 GB VRAM). `render|still|turntable|keyframes`
  tự giữ khoá GPU của lab (chờ khi agent khác đang giữ; `FILM_GPU_QUEUE=0` tắt); lệnh GPU khác (script Blender tự viết,
  `blender -b … --python`): `python tools/gpu_run.py --label <agent> -- <lệnh>`; xem ai giữ: `python tools/gpu_run.py status`.
- Blender chỉ có trên Windows: gọi bằng Python/Blender của Windows (`python tools/blender/blender.py …` từ PowerShell
  hoặc Git Bash), **không qua `bash` của WSL** (WSL không thấy Blender, không thấy GPU).

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
| 3a | sinh vật chính: cổng thiết kế (`film-pipeline` mục 2.2): ảnh sách của chủ dự án → `ICONOGRAPHY.md` → 2–3 concept Qwen-Image local → **người dùng chọn** → `CHARACTER.md` `## Concept đã duyệt`. Chưa duyệt thì không dựng model của sinh vật đó |
| 3 | `film-3d-artist`: model (preset, GLB có giấy phép, hoặc `.blend` tự dựng theo concept đã duyệt) + `ASSETS.md` + bản nháp `shots3d/s<NN>.json` (`blender.py check` sạch); nhiều nhóm sinh vật: đội song song theo `templates/episode/TEAM-3d.md` |
| 4 | `film-3d-artist`: `turntable` mỗi model chính + một shot mẫu `render --preview` → **G2** (`status.py --gate G2`: turntable, shot mẫu, không vượt trần); duyệt xong: `bundle.py … --shot <shot mẫu> --with-turntables` (§3) |
| 5 | `film-3d-artist`: `render` mọi shot không dùng lại (`renders3d/s<NN>/`); Nhật ký ghi phút GPU; mỗi shot duyệt: `bundle.py … --shot s<NN>` (§3) |
| 6 | chỉ khi có `ai_motion`: `video_engine: comfy` → `film-animator` chạy `comfy.py run h3-i2v` với khung `keyframes` (`local-video.md`); `seedance` → như tập `seedance`; không có thì bỏ qua (Nhật ký: `khâu 6 bỏ qua`) |
| 7–10 | `film-compositor`: style có khối `grade:` (vd. `chan-thuc-blender`) thì grade mỗi render trước (§7), rồi dùng chuỗi đã grade (hoặc `beauty/`, `beauty.mp4`) như một clip; sương, nắng, chữ bằng compose kit; âm thanh như mọi tập |

## 5. `shots.csv` của tập `blender`

- `layers`: `A-<asset>` (model 3D: preset hoặc GLB, id trong `shot3d.json`), `E-<bối cảnh>`, `FX` hoặc `FX-<hiệu ứng>`,
  `T` (chữ trên hình). Không `L1–L4`/`P`/`C-`.
- `camera`: đúng một tên chuyển động của `shot3d.json`: `static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track`.
- `code_motion`: hiệu ứng compose phủ lên render (`mist-bands`, `embers`, `sun-glow`…); id rig lớp tranh (`cloth`,
  `strip-warp`…) và hành động TOON là WARN.
- `ai_motion`: chỉ khi `EPISODE.md` ghi `video_engine:` (thiếu → ERROR); mô tả **một** cử động mà Blender không làm
  được (con thú bước, quay đầu).

## 6. Kiểm trước G2 và G3 (thêm vào danh sách chung)

- [ ] Mọi sinh vật chính của bảng `## Sinh vật của tập` có concept duyệt (`status.py --gate G2`: `approved concept for
      every main creature`); model khớp concept (silhouette, tỉ lệ, chi), không phải con thú nuôi ngoài đời.
- [ ] `check_episode.py` sạch (kể cả `shots3d/`, `ASSETS.md`); `status.py` FORECAST: 0 ảnh, giây video đúng dự kiến,
      phút GPU local (ước lượng).
- [ ] Model trong turntable đúng `ASSETS.md` (nguồn, giấy phép); tỉ lệ giữa các model hợp lý (linh vật `giot` cao 1.0).
- [ ] Không vật nào xuyên đất, không trượt (model có chân đi bằng `anim.action`; preset không chân chỉ trôi/bay/đứng).
- [ ] Mọi shot có render bản dùng; cùng look, cùng engine, cùng `seed` như shot mẫu đã duyệt.
- [ ] Style có `grade:`: mọi shot grade cùng tham số như shot mẫu đã duyệt (cùng `--params`), chủ thể có mask.

## 7. Grade thuỷ mặc hai lớp (`tools/compose/grade.py`, khâu 7–10)

Hình chân thực (`chan-thuc-blender`) thành thuỷ mặc: **cảnh nhạt, sương, hư ảo; chủ thể đậm và tươi hơn để nổi giữa bối
cảnh**, giữ một phần sương và một vành sương mỏng ở mép mask nên vẫn nằm trong không khí. Miễn phí, chạy CPU (numpy +
Pillow, không GPU, không mạng): chạy được cả ở phiên cloud khi đã có render. Khoảng 0,6 s mỗi khung 1080p.

Cần pass: `depth` (sương theo độ sâu) và `mask` (chủ thể). `shot3d.json` ghi `"passes": ["depth", "mask"]` hoặc
`blender.py render … --passes depth mask`; asset là chủ thể giữ `"mask"` mặc định (bật). Không có depth → không sương;
không có mask → chỉ một lớp cảnh (lệnh in `note`).

```
python3 tools/compose/grade.py --check --style styles/chan-thuc-blender [--params <tập>/grade.json]   # chỉ kiểm tham số
python3 tools/compose/grade.py out/<project>/<id>/renders3d/s03 --preview review/grade-s03.png \
    --style styles/chan-thuc-blender --subject <asset> [--frame 60]        # trước | sau, một khung: duyệt trước khi chạy cả shot
python3 tools/compose/grade.py out/<project>/<id>/renders3d/s03 out/<project>/<id>/graded/s03 \
    --style styles/chan-thuc-blender --subject <asset>                     # chuỗi PNG cùng tên (hoặc OUT graded/s03.mp4)
python3 tools/compose/grade.py <clip>.mp4 <clip>_grade.mp4 --style ... --depth <render>/depth --mask <render>/mask/<asset>
python3 tools/compose/grade.py --export-lut review/grade-scene.cube --style ... [--layer subject] [--lut-size 33]
```
- IN là thư mục render (`renders3d/s<NN>/`): khung lấy ở `beauty/`, depth ở `depth/`, `depth_range` và fps ở
  `render.json`; `--subject <asset>` (nhiều asset = hợp các mask) chọn `mask/<asset>/`. IN cũng có thể là một ảnh, thư mục
  PNG hoặc video (ffmpeg); pass truyền bằng `--depth`, `--mask` (file hoặc thư mục, khớp theo tên khung rồi theo thứ tự),
  `--depth-range NEAR FAR` khi không có `render.json`. Clip H3 nối từ render: cùng số khung thì dùng lại pass của render.
- Đầu ra: `out/<project>/<id>/graded/s<NN>[_v<NN>]/` (chuỗi PNG) hoặc `graded/s<NN>[_v<NN>].mp4`, không đặt trong
  `renders3d/` (tên lạ ở đó là WARN). Không vào gói shot: dựng lại được từ render + tham số grade. Không ghi đè: OUT đã có
  (thư mục không rỗng) → mã 2. Đầu ra PNG cùng đầu vào + cùng tham số → cùng byte (vân giấy theo `seed`, cố định trên mọi
  khung). Mã thoát: 0 xong, 1 ffmpeg/đọc file lỗi, 2 từ chối trước khi ghi (tham số sai, OUT đã có).
- Tham số: `style.yaml` khối `grade:` (`docs/CONVENTIONS.md` §3); chỉnh theo tập bằng `--params <tập>/grade.json` (cùng
  dạng, ghi đè từng khóa; dữ liệu dự án, đẩy Drive như `shots.csv`). Khóa sai hay ngoài khoảng → mã 2 với đường dẫn khóa;
  `check_episode.py style` báo ERROR tương tự.
- LUT `.cube` chỉ chứa **phần màu** (bão hoà theo dải màu, kéo màu, đường cong tông, tách tông) của một lớp; sương, lớp
  chủ thể, vân giấy, tối viền là phép theo không gian, trình dựng khác không làm được: bản cuối luôn qua `grade.py`.

| Khối | Khóa (mặc định = không đổi gì) |
|---|---|
| `seed` | số nguyên, vân giấy |
| `scene.saturation` | `global`, `red`, `orange`, `yellow`, `green`, `cyan`, `blue`, `purple`: hệ số bão hoà 0–3 theo dải màu |
| `scene.keep_red` | `amount` 0–1, `min_sat`, `gain`: đỏ son bão hoà không bị giảm (điểm nhấn) |
| `scene.hue_pull.<tên>` | `to` `#RRGGBB`, `amount` 0–1, `width` (độ, 25), `centre` (độ, mặc định màu của `to`) |
| `scene.tone` | `black` 0–0,5, `white` 0,5–1, `pivot`, `contrast` (< 1 mềm hơn), `gamma` |
| `scene.split` | `shadow`, `shadow_amount`, `highlight`, `highlight_amount`: bóng về màu mực, sáng về màu giấy |
| `scene.mist` | `color`, `amount`, `start` (m), `falloff` (m), `sky` (trời và xa hơn `depth_range`), `max`, `low`/`low_from` (dày hơn về đáy khung) |
| `scene.paper` | `amount`, `fibres` (số sợi ở 1080p), `fibre_amount`, `dark`, `tint`, `color` |
| `scene.vignette` | `amount`, `radius`, `color` |
| `subject.*` | như `scene` trừ `paper`, `vignette` (phủ một lần lên cả hai lớp); khóa thiếu lấy của `scene` |
| `subject.layer` | `opacity`, `mist_keep` (phần sương chủ thể giữ lại), `edge` (px mép mềm ở 1080p), `rim`, `rim_width` (vành sương quanh mép) |

Chủ thể chưa đủ nổi: tăng `subject.saturation.global`/`tone.contrast` hoặc giảm `layer.mist_keep`; mép cứng hay viền
trắng: tăng `layer.edge`, giảm `layer.rim`. Duyệt bằng `--preview` trước, rồi grade cả shot.
