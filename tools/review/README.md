# Xem trực tiếp bản dựng 3D và render (`tools/review/`)

Web app tự host trên máy chủ lab: xem **từ bất cứ đâu** (URL công khai qua ngrok, Tailscale Funnel hoặc cloudflared, không
đăng nhập) trạng thái và tiến độ các bản dựng model 3D, các job render Blender/ComfyUI, các job tạo ảnh; xoay xem model;
duyệt video trên dòng thời gian kiểu CapCut; xem và chọn ảnh trong thư viện ảnh.
Chạy trong Docker (`python:3.13-alpine`, chỉ thư viện chuẩn, không pip/npm/CDN), dữ liệu là SQLite trong một volume
Docker trên máy chủ lab.

> **Bảo mật — lựa chọn của chủ lab:** URL công khai **không có đăng nhập**. Ai có link là xem được **mọi thứ đã
> publish** (tên build, tiến độ, model GLB, video, ảnh, prompt của ảnh). Chỉ file trong thư mục media được phục vụ (mount
> chỉ đọc); cổng công khai 8790 chỉ đọc (GET/HEAD, mọi phương thức khác bị 405); cổng ghi 8791 chỉ nghe trên 127.0.0.1,
> không bao giờ qua tunnel, chỉ nhận `Host` là `127.0.0.1|localhost|[::1]:8791` và POST có header `X-Film-Review: 1`
> (chặn DNS rebinding; `client.py` tự gửi). Mọi chữ được lọc: đường dẫn tuyệt đối thành tên file; lỗi của
> `blender.py`/`comfy.py`/watcher chỉ là loại lỗi cố định (chi tiết ở ledger, stderr, log). Tag chỉ là slug `[a-z0-9._-]`.
> Đừng publish thứ không muốn người có link thấy; tắt link khi không dùng (`review.py down`).

| File | Chạy ở đâu | Việc |
|---|---|---|
| `server.py` | trong container | cổng 8790 (chỉ đọc): web app, `/api/*`, `/api/stream` (SSE), `/media/<đường dẫn>` có Range; cổng 8791: `POST /ingest/event` |
| `client.py` | máy chủ lab và Python 3.13 trong Blender | `Review(build, title, kind, project, expected_steps, tags=…)`: `.step()`, `.progress()`, `.render()`, `.job()`, `.done()`, `.fail()`; `JobHook` (`.image()` cho ảnh của job); chép/hard-link file vào `<media>/<build>/`; không bao giờ làm hỏng hay làm chậm lệnh gọi |
| `tags.json` | client, server, web | bộ chip: nhóm (màu, nhãn) và giá trị (nhãn tiếng Việt); thêm giá trị/nhóm ở đây, không sửa code |
| `review.py` | máy chủ lab | CLI: `up`, `down`, `url`, `status`, `monitor`, `watch`, `publish-video`, `publish-model` |
| `monitor.py` | máy chủ lab | mỗi 2 giây gửi số đo máy (CPU, RAM, GPU, VRAM, nhiệt độ, công suất, ổ đĩa, tên job nặng, người giữ GPU) và tiến độ ComfyUI (đọc log tqdm) tới cổng ghi; chỉ thư viện chuẩn |
| `watch.py` | máy chủ lab | theo dõi `out/<project>/`: ảnh WIP thành bước, mp4 thành render, `<slug>.blend` vừa lưu thành GLB (`review.py watch`) |
| `preview.py` | máy chủ lab | ảnh lớn → JPEG 1280 px q82 (cần Pillow; thiếu thì gửi ảnh gốc) |
| `bpy_snapshot.py` | trong Blender | `snapshot(review, label)`: xuất GLB `step_<NN>.glb`, đếm đỉnh/mặt, ảnh nhỏ Workbench (JPEG), gửi một bước |
| `bpy_export_glb.py` | trong Blender (`-b`, CPU) | watcher gọi: xuất `.blend` đang mở thành GLB, `--decimate R` tuỳ chọn, không lưu `.blend` |
| `demo_build_giot.py` | trong Blender | dựng lại linh vật Giọt từng bước (thân → chỏm → mắt → má → miệng → tay → bàn tay → chân → giày → vật liệu) |
| `vendor_three.py` | máy chủ lab | chép three.js 0.186.1 (đúng bản ghim của `tools/toon/three.lock`) + 4 file example vào `web/vendor/three/` (git bỏ qua), kiểm sha256 với `three-examples.lock` |
| `web/` | trình duyệt | bảng theo dõi (+ thẻ **Máy** và **ComfyUI**, chip lọc/gom nhóm), bản vẽ dựng, xem model, dòng thời gian, thư viện ảnh (ES module, import map, không build, không framework) |

## Chạy

```bash
python tools/review/vendor_three.py --from <thư mục gói three>      # một lần (vd. node_modules/three của một dự án đã cài 0.186.1)
python tools/review/review.py up                 # docker compose up -d --build + monitor + ngrok, in URL công khai
python tools/review/review.py up --tunnel tailscale     # hoặc --tunnel cloudflared
python tools/review/review.py up --no-ngrok      # không tunnel, chỉ xem tại máy: http://127.0.0.1:8790
python tools/review/review.py url                # URL công khai đang chạy
python tools/review/review.py status             # build, thư mục media (client ghi / container mount), monitor, watcher, tunnel
python tools/review/review.py down               # dừng container (volume dữ liệu giữ nguyên), monitor, tunnel do `up` mở
```

- **Thư mục media** = `FILM_REVIEW_MEDIA`, nếu không có thì `out/_review/media` của **checkout chính** của repo (tính từ
  `git rev-parse --git-common-dir`; client đọc file `.git` của worktree). Client ghi vào đó và `up` mount đúng thư mục đó
  (biến `FILM_REVIEW_MEDIA_MOUNT` cho compose), chạy từ worktree nào cũng vậy. `status` in thư mục client ghi và thư mục
  container đang mount (`docker inspect`), cảnh báo `WARNING media` khi khác nhau. File pid/log (`monitor.pid`,
  `ngrok.pid`, `watch-<project>.pid`…) cũng ở `out/_review/` của checkout chính.
- `up` từ chối (mã 2) khi thiếu file three.js hoặc sai sha256; `docker compose build` (kể cả chạy compose trực tiếp) cũng
  dừng ngay ở bước `RUN` kiểm `web/vendor/three/`. `up --dry-run` chỉ in lệnh.
- **Tunnel** (`--tunnel`, mặc định `ngrok`): `review.py` không bao giờ cài, đăng nhập, đọc hay in cấu hình/token của tunnel.
  Thiếu chương trình trên PATH hoặc chưa đăng nhập → mã 2 trước khi dựng container.

  | `--tunnel` | Lệnh | Cần | URL |
  |---|---|---|---|
  | `ngrok` | `ngrok http 127.0.0.1:8790` (chạy nền) | chủ lab đã đăng nhập ngrok; gói free giới hạn băng thông | API cục bộ `127.0.0.1:4040` |
  | `tailscale` | `tailscale funnel --bg 8790`; `down`: `tailscale funnel --https=443 off` | Tailscale đã đăng nhập, Funnel bật cho máy trong admin console | `https://<tên máy>.<tailnet>.ts.net/` cố định |
  | `cloudflared` | `cloudflared tunnel --url http://127.0.0.1:8790` (quick tunnel, chạy nền) | chỉ cần chương trình, không tài khoản | `https://<ngẫu nhiên>.trycloudflare.com`, đổi mỗi lần `up` |

- Container `film-lab-review` khởi động lại tự động (`restart: unless-stopped`) khi Docker Desktop chạy.
- Xoá hết dữ liệu (cẩn thận, không lấy lại được): `docker compose -f tools/review/docker-compose.yml down -v`.

## Chip (tag)

Mỗi build mang **tag** `{nhóm: [giá trị]}`; web vẽ thành chip có màu theo nhóm trên thẻ, trang build và thư viện ảnh.
Tiêu đề chỉ còn tên ("Phượng hoàng 鳳皇"); phần chú giải cũ trong tiêu đề ("(Blender, realistic)", " · Q1·T3") được bỏ
khi hiển thị nếu mọi phần của nó là chip (`name` trong API; `title` gốc giữ nguyên).

| Nhóm | Màu | Giá trị (`tags.json`) |
|---|---|---|
| `kind` Loại | cyan | `model`, `render`, `clip`, `image`, `concept`, `turntable`, `audio`, `demo` |
| `engine` Engine | tím | `blender`, `comfy-h3`, `comfy-qwen`, `seedance`, `seedream`, `three`, `toon`, `tts` |
| `look` Look | vàng | `realistic`, `ink-wash`, `toon-ink`, `clay`, `grey-layout` |
| `project` Dự án | xám | mở (mọi slug), vd. `son-hai-kinh` |
| `episode` Tập | xanh lá | mẫu `q01t03`, `ep01` (nhãn `Q1·T3`, `Tập 1`) |
| `subject` Sinh vật / bối cảnh | cam | mở; nhãn tên riêng của dự án đặt trong `<media>/_tags.json` (ngoài repo) |
| `shot` Shot | xanh dương | mẫu `s21` |
| `stage` Khâu | hồng | `lookdev`, `layout`, `g2`, `g3`, `final` |

- Client: `Review(build, title, kind, tags={"engine": "blender", "look": "realistic", "episode": "q01t03",
  "subject": "phuong-hoang"})`; `publish-video|publish-model --tag engine=blender --tag episode=q01t03`. Giá trị được
  chuẩn hoá thành slug (`"Q01T03"` → `q01t03`, `"Phượng hoàng"` → `phuong-hoang`). Nhóm hoặc giá trị lạ chỉ in `WARN` (không
  bao giờ lỗi); giá trị không thành slug được bỏ. Nhóm đã gửi thay nhóm cũ của build, `[]` xoá nhóm, nhóm khác giữ nguyên.
- Server: tối đa 16 nhóm × 8 giá trị, nhóm `[a-z][a-z0-9_]{0,23}`, giá trị `[a-z0-9][a-z0-9._-]{0,47}` (sai → 400). Build
  không có tag (build cũ, lệnh gọi cũ) được **suy tag** từ id, tiêu đề, kind, project: engine, look, khâu, tập, shot,
  dự án, sinh vật có trong registry. `kind`/`project` luôn có chip (lấy từ cột khi tag không nêu).
- `<media>/_tags.json` (cùng dạng `tags.json`, ghi đè/bổ sung nhãn): nhãn sinh vật/bối cảnh của dự án. Nhãn hiện trên
  trang công khai.
- **Lọc**: thanh chip trên bảng theo dõi (chỉ giá trị đang có, kèm số build). **AND giữa các nhóm, OR trong một nhóm**
  ("Q1·T3 hoặc Q1·T4, và Blender"). **Gom theo** một nhóm (build có nhiều giá trị nằm ở giá trị đầu). Bộ lọc nằm trên URL
  (`#/?st=active&t=engine:blender,episode:q01t03&g=episode`): gửi link là gửi cả bộ lọc.

## Thư viện ảnh (job tạo ảnh ComfyUI)

Build `kind: image` (hoặc `concept`) mở **thư viện ảnh** (`#/images/<id>`, không cần three.js; build nào có bước kèm ảnh
cũng có link "Ảnh (N)"): lưới ảnh, mở lớn (←/→, Esc), so sánh 2–4 ảnh cạnh nhau, đánh dấu **được chọn** (★, phím C;
lưu trong trình duyệt vì trang công khai chỉ đọc; **Tải danh sách chọn** ra `chosen-<build>-<ngày>.json`), lọc chỉ ảnh được
chọn. Thanh tiến độ: ảnh k/N của lô và bước i/n của ảnh đang chạy, ETA, giây trung bình mỗi ảnh. Thẻ ComfyUI trên bảng
hiện build, workflow và ảnh k/N của job đang chạy (job ảnh lẫn video), link tới thư viện ảnh hoặc dòng thời gian.

| Sự kiện | Trường thêm (tuỳ chọn) | Giới hạn |
|---|---|---|
| `step` | `prompt` (≤ 2000 ký tự, lọc đường dẫn), `seed`, `model` (≤ 120), `sampler_steps`, `seconds` (giây làm ảnh), `width`, `height`, `workflow` (≤ 60), `item`/`items` (ảnh k/N), `chosen` | seed 0..2⁶⁴−1, bước 1..10000, cỡ 1..65535, item ≤ items |
| `job` | `label` (workflow), `step`/`steps` (bước i/n), `item`/`items`, `eta` (giây) | step ≤ steps; trường không gửi thì giữ giá trị cũ |

Client: `rv.step(label, image=…, meta={"prompt": …, "seed": …})`, `rv.job(tool, status, …, label=…, step=…, steps=…,
item=…, items=…, eta=…)`, `job_hook(build, "comfy", "image", title=…, tags=…, label="qwen-t2i")` rồi `hook.update(x, msg,
step=…, steps=…, item=…, items=…)` và `hook.image(path, label, seed=…, seconds=…, item=…, items=…)`. Trường sai kiểu hoặc
ngoài giới hạn bị client bỏ kèm `WARN` (server sẽ từ chối cả sự kiện).

## Băng thông

Tunnel free hết băng thông vì PNG 1–3 MB, GLB và mp4. Client gửi ảnh PNG/WebP/TIFF/BMP ≥ 256 KB dưới dạng **JPEG 1280 px
q82** (`preview.py`, cần Pillow; không có thì gửi ảnh gốc và in một dòng). `FILM_REVIEW_PREVIEW=off` hoặc
`step(..., preview=False)` để gửi ảnh gốc. Ảnh nhỏ của `bpy_snapshot` là JPEG. Video có Range (trình duyệt chỉ tải đoạn
cần xem). GLB của watcher quá `--max-glb-mb` (mặc định 60) được xuất lại có Decimate.

## Máy và ComfyUI (`monitor.py`)

```bash
python tools/review/review.py up --no-ngrok      # dựng lại container + bật monitor (không đụng tunnel đang chạy)
python tools/review/review.py monitor [--restart] [--comfy-log PATH] [--interval 2]   # chỉ monitor, chạy nền
python tools/review/review.py monitor --stop
python tools/review/monitor.py --once --print    # đo một lần, in hai sự kiện, không gửi gì (kiểm tra riêng tư)
```

- Chạy nền tách khỏi cửa sổ (Windows: `DETACHED_PROCESS`), PID ở `out/_review/monitor.pid`, log ở
  `out/_review/monitor.log`. Trước khi dừng, `review.py` kiểm pid: `monitor.pid` phải là python chạy
  `tools/review/monitor.py`, `watch-<project>.pid` là python chạy `tools/review/watch.py`, `ngrok.pid`/`cloudflared.pid`
  phải là đúng chương trình đó (Windows: PowerShell `Get-CimInstance`); không đúng thì xoá file pid và không giết gì. `up`
  bật monitor (trừ `--no-monitor`), `down` tắt, `status` in trạng thái + số đo mới nhất.
- **Máy**: CPU % (`GetSystemTimes`), RAM (`GlobalMemoryStatusEx`), GPU %, VRAM, nhiệt độ, công suất (`nvidia-smi`; không có
  thì bỏ GPU, thử lại mỗi phút), dung lượng trống mọi ổ cố định (C:, D:…), job nặng. Linux: đọc `/proc`. Biểu đồ vùng
  (canvas) 10 phút (mẫu 2 giây) hoặc 24 giờ (trung bình 1 phút). Màu cảnh báo: VRAM > 90 %, GPU > 83 °C, ổ còn < 10 GB
  (vàng khi < 20 GB, > 80 % VRAM, > 76 °C).
- **Giữ GPU**: khoá GPU của hàng đợi GPU (`FILM_GPU_LOCK`, mặc định `out/_gpu/gpu.lock` của checkout chính); file
  `gpu.owner` cạnh nó (`{"label", "pid", "since"}`, `since` ISO-8601 UTC) cho biết ai giữ. Không có file hoặc pid đã chết =
  rảnh. Nhãn là chữ tự do nên được lọc trước khi lên trang công khai: đường dẫn thành tên file, bỏ dấu, chỉ còn
  `[A-Za-z0-9 _.:/-]`, ≤ 60 ký tự (server kiểm lại); pid không được gửi.
- **Riêng tư** (trang công khai, không đăng nhập): job nặng chỉ là **nhãn trong danh sách cho phép** kèm số lượng
  (`blender ×2`, `ComfyUI (python)`, `ComfyUI Desktop`, `ffmpeg`, `DaVinci Resolve`…), không bao giờ có dòng lệnh, đường
  dẫn, tiêu đề cửa sổ, biến môi trường hay tên người dùng. Server chỉ nhận đúng các nhãn đó (`PROC_LABELS`, test giữ hai
  danh sách bằng nhau), tên ổ chỉ dạng `C:`. Python được tính là `ComfyUI (python)` khi nó nghe cổng ComfyUI (Windows) hoặc
  chạy `main.py` của ComfyUI (Linux, đọc tại chỗ, không gửi). Log ComfyUI chỉ được đọc lấy số.
- **ComfyUI**: bật/tắt và số job đang chạy/chờ từ `GET <FILM_COMFY_URL>/queue`; bước i/n, s/bước, đã chạy, còn lại, %
  của job hiện tại và 10 lượt gần nhất (thời gian, số bước, s/bước) từ dòng tqdm trong log (`\r` hay `\n`, cả dòng
  `Prompt executed in 138.35 seconds` lẫn `00:11:52`). Mọi job đều thấy, kể cả job xếp từ cửa sổ ComfyUI. Log mặc định
  là log của `comfy.py start`: `FILM_COMFY_LOG`, else `$FILM_COMFY_WORK/server.log`, else `out/_comfy/server.log` của
  checkout chính hoặc của checkout đang chạy (cái nào có, mới hơn thì thắng; monitor chạy từ worktree vẫn thấy log của repo
  chính). Với Comfy Desktop: `--comfy-log %LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI\logs\comfyui.log` và
  `FILM_COMFY_URL` trỏ cổng của Desktop. Job do `comfy.py run --review B` chạy được nối với build `B` (job review tên
  `comfy-<prompt id>`) và có link trên thẻ.
- Server không có (chưa `up`) hoặc trả 5xx: monitor vẫn đo, thử gửi lại với khoảng chờ 2 → 60 giây, không bao giờ thoát
  vì lỗi. Số đo được kẹp vào khoảng server nhận; server trả 4xx thì ghi log một lần và gửi bản rút gọn, không lùi.
- SSE: tối đa một sự kiện `metrics` và một `comfy` mỗi 2 giây (bản mới nhất thắng), không vào bộ đệm phát lại.
- Giới hạn chống DoS: tối đa 64 luồng SSE (quá thì 503), mỗi luồng sống 10 phút (trình duyệt tự nối lại); đọc request
  timeout 15 giây, cả phần đầu request phải tới trong 20 giây; mỗi khối file gửi đi 60 giây.

## Theo dõi thư mục làm việc (`watch`)

Agent chỉ ghi file ra đĩa; watcher đăng tiến trình lên bảng mà không cần agent gọi client.

```bash
python tools/review/review.py watch son-hai-kinh --episode q01t03    # chạy nền, pid out/_review/watch-son-hai-kinh.pid
python tools/review/review.py watch son-hai-kinh --once              # quét một lần ở cửa sổ này
python tools/review/review.py watch son-hai-kinh --restart --dir characters --max-glb-mb 40
python tools/review/review.py watch son-hai-kinh --stop
```

- Quét `out/<project>/` của checkout chính mỗi `--interval` giây (5). Mặc định `characters/`, `locations/` và
  `<episode>/renders3d/` (không có `--episode`: mọi `*/renders3d/`); `--dir` (lặp lại được) thay danh sách.
- `characters|locations/<slug>/` → build `<project>-<slug>` (kind `model`, tag `engine: blender`, `subject: <slug>`,
  `stage: lookdev`, `project`, `episode`): ảnh mới hoặc đổi (png/jpg/webp, mọi cấp) thành bước (JPEG preview), mp4 thành
  render; `<slug>.blend` (hoặc `<slug>_vNN.blend` mới nhất) được lưu và để yên 20 giây → Blender headless (`-b`, CPU, không
  render) xuất GLB thẳng vào thư mục media → bước GLB, "Bản vẽ dựng"/"Xem model" chạy trực tiếp. GLB lớn hơn
  `--max-glb-mb` (60) được xuất lại với Decimate vừa cỡ (`--decimate R` ép tỉ lệ); không dùng Draco (web chưa có decoder).
- `<episode>/renders3d/<shot>…/` → build `<project>-<episode>-<shot>` (kind `render`, tag `shot`): ảnh thành bước, mp4 thành
  render.
- Bỏ qua chuỗi khung: thư mục `beauty`, `frames`, `passes`, `depth`, `normal(s)`, `mask(s)`, `control*`, `canny`, `pose`…
  và thư mục có từ 8 khung đánh số (`0001.png`).
- Trạng thái ở `out/_review/watch-<project>.json`: khởi động lại không đăng trùng. Lần đầu chỉ đăng file đổi trong
  `--since` giờ gần nhất (12), file cũ hơn chỉ đánh dấu đã thấy. Không có server: vẫn quét, đăng lại ở lần quét sau. Xuất
  GLB lỗi chỉ gửi loại lỗi cố định; chi tiết ở `out/_review/watch-<project>.log`.

## Publish

```bash
python tools/review/review.py publish-video <clip>.mp4 --build demo-s01 --label "H3 s01" [--title T] [--project P] [--tag engine=comfy-h3] [--open]
python tools/review/review.py publish-model <model>.glb --build thuyen --label "vỏ" [--tag look=clay] [--open]
python tools/blender/blender.py render <shot3d.json> --out <thư mục> --review ep01-s03       # hoặc env FILM_REVIEW_BUILD
python tools/blender/blender.py turntable preset:giot --out <thư mục> --review giot-tt
python tools/comfy/comfy.py run h3-i2v --image <start>.png --prompt "..." --out <clip>.mp4 --ledger L --review ep01-s03
"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" -b --factory-startup --python-exit-code 1 -P tools/review/demo_build_giot.py -- --build giot-demo --step-delay 2
```

- `--review BUILD` (hoặc `FILM_REVIEW_BUILD`) trên `blender.py render|turntable|keyframes` và `comfy.py run`: báo job
  bắt đầu, tiến độ (tối đa một lần mỗi 2 giây: số khung của Blender, thời gian/ước tính của ComfyUI), kết thúc; mp4 (hoặc
  ảnh khung đầu/cuối của `keyframes`) thành một render của build. Mặc định tắt; `--dry-run` không gửi gì.
- Không có server (chưa `up`) thì mọi lệnh vẫn chạy như cũ: mỗi request chờ tối đa 2 giây; sau một lần quá giờ client
  im 15 giây (bỏ qua tiến độ, vẫn thử build/render/done/fail). `FILM_REVIEW_URL=off` tắt hẳn.
- File được hard-link (khác ổ thì chép) vào `<media>/<build>/`, **không bao giờ ghi đè**: file khác nội dung cùng tên
  thành `<tên>-2`, `-3`… Chạy lại cùng build id với `restart` (bản demo làm vậy) thì các bước cũ bị thay.
  `Review(..., append=True)`: bước không mang số, server đánh số tiếp (watcher).
- Env: `FILM_REVIEW_URL` (mặc định `http://127.0.0.1:8791`), `FILM_REVIEW_MEDIA` (mặc định `out/_review/media` của
  checkout chính), `FILM_REVIEW_BUILD`, `FILM_REVIEW_PREVIEW`.

## Web app

Mỗi trang vẽ vào một khung riêng (`web/route.js`): chuyển trang khi trang trước còn đang tải (vd. GLB 12 MB) thì trang
cũ bị huỷ ngay khi tải xong và không bao giờ hiện chồng lên trang mới.

- **Bảng theo dõi** (`#/`): mỗi build một thẻ: tên, chip, trạng thái, thanh tiến độ, bước hiện tại, thời gian chạy, ảnh nhỏ,
  job đang chạy (ảnh k/N, bước i/n); lọc theo trạng thái và chip, gom nhóm (mục "Chip"); cập nhật trực tiếp qua SSE. Dùng
  tốt trên điện thoại.
- **Bản vẽ dựng** (`#/build/<id>`): nền bản vẽ xanh navy có lưới và đường kích thước (m); phần hình mới của mỗi bước
  hiện ra bằng nét cyan phát sáng (EdgesGeometry, vẽ dần ~1 s) rồi chuyển thành khối có vật liệu; máy quay tự xoay chậm;
  nhật ký bước ("Bước 7/10 · arms · +64 đỉnh · 2.1 s"); **Trực tiếp** theo bước mới khi đang dựng; thanh kéo bước,
  **Phát lại** với tốc độ 0.5–4×.
- **Xem model** (`#/model/<id>`): GLB mới nhất (hoặc bước bất kỳ), xoay/phóng/dời (chuột hoặc cảm ứng), tự xoay, đặc /
  khung dây / pháp tuyến / đất sét, nền và ánh sáng, thống kê, phát hoạt hình có trong GLB.
- **Thư viện ảnh** (`#/images/<id>`): mục "Thư viện ảnh".
- **Dòng thời gian** (`#/timeline/<id>`): track video (clip nối nhau, kéo mép để cắt đầu/cuối, kéo thân để đổi thứ tự),
  track tiếng (dạng sóng giải mã bằng WebAudio), track đánh dấu (khung đầu/cuối của mỗi clip + đánh dấu của bạn), đầu
  phát kéo được, thu phóng, tốc độ, tắt tiếng, vùng lặp, so sánh **A/B** bằng vạch chia kéo được. Phím: Space phát/dừng,
  ←/→ một khung (Shift: 1 giây), I/O/L vùng lặp, M đánh dấu, B so sánh, +/− thu phóng. Chỉ để xem và duyệt: không sửa
  gì trên server; bản dựng lưu trong trình duyệt, **Xuất → Tải edit.json** (thứ tự clip, đầu/cuối, đánh dấu, ghi chú).

## Dữ liệu

SQLite `/data/review.db` trong volume `review-db` (chỉ container mở file này; đừng chia sẻ .db qua bind mount Windows).
Bảng `builds` (id, title, kind `model|render|clip|demo|image|concept` (kiểm ở server, không bằng CHECK của bảng), project,
status `queued|building|rendering|done|failed`, progress 0..1, expected_steps, current, message, thumb,
started/updated/finished, tags JSON), `steps` (build, n, label, stats JSON, glb, image, t, meta JSON), `renders` (build,
label, video, image, frames, fps, duration, engine, seconds_per_frame, t), `jobs` (build, job, tool `blender|comfy`, status
`queued|running|done|failed`, progress, gpu_s, message, started, t, label, step, steps, item, items, eta). Sự kiện ingest:
`build`, `step`, `progress`, `render`, `job`, `done`, `fail`; kiểu hay trường lạ, đường dẫn media ra ngoài `<build>/` bị
từ chối (400). Giữ có giới hạn: ≤ 500 build (build cập nhật lâu nhất bị xoá cùng bước/render/job; file media giữ nguyên),
≤ 2000 bước, ≤ 500 render, ≤ 200 job mỗi build. Sự kiện `metrics` và `comfy` (của `monitor.py`, không có build): 10 phút mẫu
2 giây nằm trong bộ nhớ; bảng `metrics_min` (t, JSON trung bình 1 phút) giữ 24 giờ, xoá dần khi ghi phút mới. API:
`/api/metrics?window=10m|24h`, `/api/comfy`, `/api/tags`.

**Nâng cấp DB cũ** (`PRAGMA user_version` 2, tự chạy một lần khi server mới khởi động, một transaction): dựng lại bảng
`builds` không còn CHECK trên kind và có cột `tags` (khoá ngoại tắt trong lúc dựng lại, bước/render/job giữ nguyên), suy tag
cho mọi build cũ (`infer_tags`), thêm `steps.meta` và các cột chi tiết của `jobs`. Tiêu đề cũ không bị sửa (tên hiển thị
tính lúc đọc).

## Test

`tests/test_review_monitor.py`: parser tqdm (dòng dở, `\r`, 100 %, dòng hỏng), đọc `/proc` giả, danh sách nhãn cho
phép (payload không có dòng lệnh/đường dẫn), monitor khi không có server, kiểm sự kiện, lịch sử 24 giờ và xoá dần, giới
hạn SSE, API, và chặn tranh chấp chuyển trang của web app (`web/route.js`, chạy bằng node).
`tests/test_review.py` (WSL, chỉ thư viện chuẩn, không cần Docker): API và SSE trên DB tạm, Range 206/416, chặn
path traversal, cổng công khai từ chối POST/PUT/DELETE, MIME, CSP; client không có server vẫn nhanh và không lỗi; kiểm
hash của `vendor_three.py`; `review.py up --no-ngrok --dry-run`; hook của `blender.py`/`comfy.py` với server ingest giả.
`tests/test_review_tags.py`: tag (API, gộp, suy tag, tên hiển thị, từ chối tag sai, registry + `_tags.json`), build ảnh
(meta, chi tiết job, nối ComfyUI), nâng cấp DB v1, client (chuẩn hoá tag chỉ cảnh báo, meta, `JobHook.image`, JPEG
preview), checkout chính từ worktree, mount của `up`/`status`, tunnel (thiếu chương trình/chưa đăng nhập → 2), người giữ
GPU, log ComfyUI từ worktree, `web/tags.js` (lọc AND/OR, gom nhóm, trạng thái trên hash) chạy bằng node.
`tests/test_review_watch.py`: watcher với thư mục giả, client giả và Blender giả (ảnh/mp4/GLB, bỏ chuỗi khung, Decimate,
trạng thái, lần đầu, thử lại), với client thật, `review.py watch`.
