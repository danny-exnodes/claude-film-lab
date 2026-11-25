# Xem trực tiếp bản dựng 3D và render (`tools/review/`)

Web app tự host trên máy chủ lab: xem **từ bất cứ đâu** (URL công khai của ngrok, không đăng nhập) trạng thái và tiến độ
các bản dựng model 3D, các job render Blender/ComfyUI; xoay xem model; duyệt video trên dòng thời gian kiểu CapCut.
Chạy trong Docker (`python:3.13-alpine`, chỉ thư viện chuẩn, không pip/npm/CDN), dữ liệu là SQLite trong một volume
Docker trên máy chủ lab.

> **Bảo mật — lựa chọn của chủ lab:** URL công khai **không có đăng nhập**. Ai có link là xem được **mọi thứ đã
> publish** (tên build, tiến độ, model GLB, video, ảnh). Chỉ file trong `out/_review/media/` được phục vụ (mount chỉ
> đọc); cổng công khai 8790 chỉ đọc (GET/HEAD, mọi phương thức khác bị 405); cổng ghi 8791 chỉ nghe trên 127.0.0.1,
> không bao giờ qua ngrok, chỉ nhận `Host` là `127.0.0.1|localhost|[::1]:8791` và POST có header `X-Film-Review: 1`
> (chặn DNS rebinding; `client.py` tự gửi). Mọi chữ được lọc: đường dẫn tuyệt đối thành tên file; lỗi của
> `blender.py`/`comfy.py` chỉ là loại lỗi cố định (chi tiết ở ledger, stderr). Đừng publish thứ không muốn người có link
> thấy; tắt link khi không dùng (`review.py down`).

| File | Chạy ở đâu | Việc |
|---|---|---|
| `server.py` | trong container | cổng 8790 (chỉ đọc): web app, `/api/*`, `/api/stream` (SSE), `/media/<đường dẫn>` có Range; cổng 8791: `POST /ingest/event` |
| `client.py` | máy chủ lab và Python 3.13 trong Blender | `Review(build, title, kind, project, expected_steps)`: `.step()`, `.progress()`, `.render()`, `.job()`, `.done()`, `.fail()`; chép/hard-link file vào `out/_review/media/<build>/`; không bao giờ làm hỏng hay làm chậm lệnh gọi |
| `review.py` | máy chủ lab | CLI: `up`, `down`, `url`, `status`, `monitor`, `publish-video`, `publish-model` |
| `monitor.py` | máy chủ lab | mỗi 2 giây gửi số đo máy (CPU, RAM, GPU, VRAM, nhiệt độ, công suất, ổ đĩa, tên job nặng) và tiến độ ComfyUI (đọc log tqdm) tới cổng ghi; chỉ thư viện chuẩn |
| `bpy_snapshot.py` | trong Blender | `snapshot(review, label)`: xuất GLB `step_<NN>.glb`, đếm đỉnh/mặt, ảnh nhỏ Workbench, gửi một bước |
| `demo_build_giot.py` | trong Blender | dựng lại linh vật Giọt từng bước (thân → chỏm → mắt → má → miệng → tay → bàn tay → chân → giày → vật liệu) |
| `vendor_three.py` | máy chủ lab | chép three.js 0.186.1 (đúng bản ghim của `tools/toon/three.lock`) + 4 file example vào `web/vendor/three/` (git bỏ qua), kiểm sha256 với `three-examples.lock` |
| `web/` | trình duyệt | bảng theo dõi (+ thẻ **Máy** và **ComfyUI**), bản vẽ dựng, xem model, dòng thời gian (ES module, import map, không build, không framework) |

## Chạy

```bash
python tools/review/vendor_three.py --from <thư mục gói three>      # một lần (vd. node_modules/three của một dự án đã cài 0.186.1)
python tools/review/review.py up                 # docker compose up -d --build + ngrok, in URL công khai
python tools/review/review.py up --no-ngrok      # chỉ xem tại máy: http://127.0.0.1:8790
python tools/review/review.py url                # URL công khai đang chạy (đọc từ API cục bộ của ngrok, cổng 4040)
python tools/review/review.py status             # các build trên server
python tools/review/review.py down               # dừng container (volume dữ liệu giữ nguyên) + ngrok do `up` mở
```

- `up` từ chối (mã 2) khi thiếu file three.js hoặc sai sha256; `up --dry-run` chỉ in lệnh. `review.py` không bao giờ
  đọc hay in cấu hình/authtoken của ngrok; ngrok phải được chủ lab đăng nhập sẵn.
- Container `film-lab-review` khởi động lại tự động (`restart: unless-stopped`) khi Docker Desktop chạy.
- Xoá hết dữ liệu (cẩn thận, không lấy lại được): `docker compose -f tools/review/docker-compose.yml down -v`.

## Máy và ComfyUI (`monitor.py`)

```bash
python tools/review/review.py up --no-ngrok      # dựng lại container + bật monitor (không đụng ngrok đang chạy)
python tools/review/review.py monitor [--restart] [--comfy-log PATH] [--interval 2]   # chỉ monitor, chạy nền
python tools/review/review.py monitor --stop
python tools/review/monitor.py --once --print    # đo một lần, in hai sự kiện, không gửi gì (kiểm tra riêng tư)
```

- Chạy nền tách khỏi cửa sổ (Windows: `DETACHED_PROCESS`), PID ở `out/_review/monitor.pid`, log ở
  `out/_review/monitor.log`. Trước khi dừng, `review.py` kiểm pid: `monitor.pid` phải là python chạy
  `tools/review/monitor.py`, `ngrok.pid` phải là ngrok (Windows: PowerShell `Get-CimInstance`); không đúng thì xoá file pid
  và không giết gì. `up` bật monitor (trừ `--no-monitor`), `down` tắt, `status` in trạng thái + số đo mới nhất.
- **Máy**: CPU % (`GetSystemTimes`), RAM (`GlobalMemoryStatusEx`), GPU %, VRAM, nhiệt độ, công suất (`nvidia-smi`; không có
  thì bỏ GPU, thử lại mỗi phút), dung lượng trống mọi ổ cố định (C:, D:…), job nặng. Linux: đọc `/proc`. Biểu đồ vùng
  (canvas) 10 phút (mẫu 2 giây) hoặc 24 giờ (trung bình 1 phút). Màu cảnh báo: VRAM > 90 %, GPU > 83 °C, ổ còn < 10 GB
  (vàng khi < 20 GB, > 80 % VRAM, > 76 °C).
- **Riêng tư** (trang công khai, không đăng nhập): job nặng chỉ là **nhãn trong danh sách cho phép** kèm số lượng
  (`blender ×2`, `ComfyUI (python)`, `ComfyUI Desktop`, `ffmpeg`, `DaVinci Resolve`…), không bao giờ có dòng lệnh, đường
  dẫn, tiêu đề cửa sổ, biến môi trường hay tên người dùng. Server chỉ nhận đúng các nhãn đó (`PROC_LABELS`, test giữ hai
  danh sách bằng nhau), tên ổ chỉ dạng `C:`. Python được tính là `ComfyUI (python)` khi nó nghe cổng ComfyUI (Windows) hoặc
  chạy `main.py` của ComfyUI (Linux, đọc tại chỗ, không gửi). Log ComfyUI chỉ được đọc lấy số.
- **ComfyUI**: bật/tắt và số job đang chạy/chờ từ `GET <FILM_COMFY_URL>/queue`; bước i/n, s/bước, đã chạy, còn lại, %
  của job hiện tại và 10 lượt gần nhất (thời gian, số bước, s/bước) từ dòng tqdm trong log (`\r` hay `\n`, cả dòng
  `Prompt executed in 138.35 seconds` lẫn `00:11:52`). Mọi job đều thấy, kể cả job xếp từ cửa sổ ComfyUI. Log mặc định
  là log của `comfy.py start` (`FILM_COMFY_LOG`, else `$FILM_COMFY_WORK/server.log`, else `out/_comfy/server.log`); với
  Comfy Desktop: `--comfy-log %LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI\logs\comfyui.log` và
  `FILM_COMFY_URL` trỏ cổng của Desktop. Job do `comfy.py run --review B` chạy được nối với build `B` (job review tên
  `comfy-<prompt id>`) và có link trên thẻ.
- Server không có (chưa `up`) hoặc trả 5xx: monitor vẫn đo, thử gửi lại với khoảng chờ 2 → 60 giây, không bao giờ thoát
  vì lỗi. Số đo được kẹp vào khoảng server nhận; server trả 4xx thì ghi log một lần và gửi bản rút gọn, không lùi.
- SSE: tối đa một sự kiện `metrics` và một `comfy` mỗi 2 giây (bản mới nhất thắng), không vào bộ đệm phát lại.
- Giới hạn chống DoS: tối đa 64 luồng SSE (quá thì 503), mỗi luồng sống 10 phút (trình duyệt tự nối lại); đọc request
  timeout 15 giây, cả phần đầu request phải tới trong 20 giây; mỗi khối file gửi đi 60 giây.

## Publish

```bash
python tools/review/review.py publish-video <clip>.mp4 --build demo-s01 --label "H3 s01" [--title T] [--project P] [--open]
python tools/review/review.py publish-model <model>.glb --build thuyen --label "vỏ" [--open]
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
- File được hard-link (khác ổ thì chép) vào `out/_review/media/<build>/`, **không bao giờ ghi đè**: file khác nội dung
  cùng tên thành `<tên>-2`, `-3`… Chạy lại cùng build id với `restart` (bản demo làm vậy) thì các bước cũ bị thay.
- Env: `FILM_REVIEW_URL` (mặc định `http://127.0.0.1:8791`), `FILM_REVIEW_MEDIA` (mặc định `out/_review/media` của lab),
  `FILM_REVIEW_BUILD`.

## Web app

Mỗi trang vẽ vào một khung riêng (`web/route.js`): chuyển trang khi trang trước còn đang tải (vd. GLB 12 MB) thì trang
cũ bị huỷ ngay khi tải xong và không bao giờ hiện chồng lên trang mới.

- **Bảng theo dõi** (`#/`): mỗi build một thẻ: trạng thái, thanh tiến độ, bước hiện tại, thời gian chạy, ảnh nhỏ, job
  đang chạy; cập nhật trực tiếp qua SSE. Dùng tốt trên điện thoại.
- **Bản vẽ dựng** (`#/build/<id>`): nền bản vẽ xanh navy có lưới và đường kích thước (m); phần hình mới của mỗi bước
  hiện ra bằng nét cyan phát sáng (EdgesGeometry, vẽ dần ~1 s) rồi chuyển thành khối có vật liệu; máy quay tự xoay chậm;
  nhật ký bước ("Bước 7/10 · arms · +64 đỉnh · 2.1 s"); **Trực tiếp** theo bước mới khi đang dựng; thanh kéo bước,
  **Phát lại** với tốc độ 0.5–4×.
- **Xem model** (`#/model/<id>`): GLB mới nhất (hoặc bước bất kỳ), xoay/phóng/dời (chuột hoặc cảm ứng), tự xoay, đặc /
  khung dây / pháp tuyến / đất sét, nền và ánh sáng, thống kê, phát hoạt hình có trong GLB.
- **Dòng thời gian** (`#/timeline/<id>`): track video (clip nối nhau, kéo mép để cắt đầu/cuối, kéo thân để đổi thứ tự),
  track tiếng (dạng sóng giải mã bằng WebAudio), track đánh dấu (khung đầu/cuối của mỗi clip + đánh dấu của bạn), đầu
  phát kéo được, thu phóng, tốc độ, tắt tiếng, vùng lặp, so sánh **A/B** bằng vạch chia kéo được. Phím: Space phát/dừng,
  ←/→ một khung (Shift: 1 giây), I/O/L vùng lặp, M đánh dấu, B so sánh, +/− thu phóng. Chỉ để xem và duyệt: không sửa
  gì trên server; bản dựng lưu trong trình duyệt, **Xuất → Tải edit.json** (thứ tự clip, đầu/cuối, đánh dấu, ghi chú).

## Dữ liệu

SQLite `/data/review.db` trong volume `review-db` (chỉ container mở file này; đừng chia sẻ .db qua bind mount Windows).
Bảng `builds` (id, title, kind `model|render|clip|demo`, project, status `queued|building|rendering|done|failed`,
progress 0..1, expected_steps, current, message, thumb, started/updated/finished), `steps` (build, n, label, stats JSON,
glb, image, t), `renders` (build, label, video, image, frames, fps, duration, engine, seconds_per_frame, t), `jobs` (build,
job, tool `blender|comfy`, status `queued|running|done|failed`, progress, gpu_s, message, started, t). Sự kiện ingest:
`build`, `step`, `progress`, `render`, `job`, `done`, `fail`; kiểu hay trường lạ, đường dẫn media ra ngoài
`<build>/` bị từ chối (400). Giữ có giới hạn: ≤ 500 build (build cập nhật lâu nhất bị xoá cùng bước/render/job; file
media trong `out/_review/media/` giữ nguyên), ≤ 2000 bước, ≤ 500 render, ≤ 200 job mỗi build. Sự kiện `metrics` và `comfy` (của `monitor.py`, không có build): 10 phút mẫu 2 giây nằm trong
bộ nhớ; bảng `metrics_min` (t, JSON trung bình 1 phút) giữ 24 giờ, xoá dần khi ghi phút mới. API: `/api/metrics?window=10m|24h`,
`/api/comfy`.

## Test

`tests/test_review_monitor.py`: parser tqdm (dòng dở, `\r`, 100 %, dòng hỏng), đọc `/proc` giả, danh sách nhãn cho
phép (payload không có dòng lệnh/đường dẫn), monitor khi không có server, kiểm sự kiện, lịch sử 24 giờ và xoá dần, giới
hạn SSE, API, và chặn tranh chấp chuyển trang của web app (`web/route.js`, chạy bằng node).
`tests/test_review.py` (WSL, chỉ thư viện chuẩn, không cần Docker): API và SSE trên DB tạm, Range 206/416, chặn
path traversal, cổng công khai từ chối POST/PUT/DELETE, MIME, CSP; client không có server vẫn nhanh và không lỗi; kiểm
hash của `vendor_three.py`; `review.py up --no-ngrok --dry-run`; hook của `blender.py`/`comfy.py` với server ingest giả.
