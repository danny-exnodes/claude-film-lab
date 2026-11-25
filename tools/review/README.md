# Xem trực tiếp bản dựng 3D và render (`tools/review/`)

Web app tự host trên máy chủ lab: xem **từ bất cứ đâu** (URL công khai của ngrok, không đăng nhập) trạng thái và tiến độ
các bản dựng model 3D, các job render Blender/ComfyUI; xoay xem model; duyệt video trên dòng thời gian kiểu CapCut.
Chạy trong Docker (`python:3.13-alpine`, chỉ thư viện chuẩn, không pip/npm/CDN), dữ liệu là SQLite trong một volume
Docker trên máy chủ lab.

> **Bảo mật — lựa chọn của chủ lab:** URL công khai **không có đăng nhập**. Ai có link là xem được **mọi thứ đã
> publish** (tên build, tiến độ, model GLB, video, ảnh). Chỉ file trong `out/_review/media/` được phục vụ (mount chỉ
> đọc); cổng công khai 8790 chỉ đọc (GET/HEAD, mọi phương thức khác bị 405); cổng ghi 8791 chỉ nghe trên 127.0.0.1,
> không bao giờ qua ngrok. Đừng publish thứ không muốn người có link thấy; tắt link khi không dùng (`review.py down`).

| File | Chạy ở đâu | Việc |
|---|---|---|
| `server.py` | trong container | cổng 8790 (chỉ đọc): web app, `/api/*`, `/api/stream` (SSE), `/media/<đường dẫn>` có Range; cổng 8791: `POST /ingest/event` |
| `client.py` | máy chủ lab và Python 3.13 trong Blender | `Review(build, title, kind, project, expected_steps)`: `.step()`, `.progress()`, `.render()`, `.job()`, `.done()`, `.fail()`; chép/hard-link file vào `out/_review/media/<build>/`; không bao giờ làm hỏng hay làm chậm lệnh gọi |
| `review.py` | máy chủ lab | CLI: `up`, `down`, `url`, `status`, `publish-video`, `publish-model` |
| `bpy_snapshot.py` | trong Blender | `snapshot(review, label)`: xuất GLB `step_<NN>.glb`, đếm đỉnh/mặt, ảnh nhỏ Workbench, gửi một bước |
| `demo_build_giot.py` | trong Blender | dựng lại linh vật Giọt từng bước (thân → chỏm → mắt → má → miệng → tay → bàn tay → chân → giày → vật liệu) |
| `vendor_three.py` | máy chủ lab | chép three.js 0.186.1 (đúng bản ghim của `tools/toon/three.lock`) + 4 file example vào `web/vendor/three/` (git bỏ qua), kiểm sha256 với `three-examples.lock` |
| `web/` | trình duyệt | bảng theo dõi, bản vẽ dựng, xem model, dòng thời gian (ES module, import map, không build, không framework) |

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
`<build>/` bị từ chối (400).

## Test

`tests/test_review.py` (WSL, chỉ thư viện chuẩn, không cần Docker): API và SSE trên DB tạm, Range 206/416, chặn
path traversal, cổng công khai từ chối POST/PUT/DELETE, MIME, CSP; client không có server vẫn nhanh và không lỗi; kiểm
hash của `vendor_three.py`; `review.py up --no-ngrok --dry-run`; hook của `blender.py`/`comfy.py` với server ingest giả.
