# Video AI tại chỗ bằng ComfyUI (`tools/comfy/`)

Tạo clip có tiếng bằng model **MiniMax H3** chạy trong **ComfyUI trên máy của chủ dự án** (Windows, RTX 5070 Ti 16 GB),
**miễn phí**, ghi vào ledger của tập như một request Seedance nhưng **chi phí 0** (không trừ trần nào của
`budget.yaml`). Chỉ dùng được trong **phiên Claude Code local** trên máy đó; phiên cloud không có GPU, không có ComfyUI.
Cũng tạo **ảnh concept** bằng Qwen-Image 2512 (`qwen-t2i`, mục "Tạo ảnh concept") và **phôi 3D** của sinh vật bằng
Hunyuan3D 2.1 (`hunyuan3d`, mục "Tạo phôi 3D").

| File | Việc |
|---|---|
| `comfy.py` | CLI (chỉ thư viện chuẩn; Pillow để cắt khung hình): `ping`, `start`, `install`, `models`, `workflows`, `run`, `interrupt` |
| `mesh3d.py` | `run` của workflow ảnh → 3D (`hunyuan3d`): kiểm nền, vuông hoá ảnh vào, tải GLB (Pillow + numpy) |
| `comfy.lock.json` | ComfyUI portable ghim phiên bản (tuỳ chọn) + tên, thư mục, kích thước các file model H3 và Qwen-Image (sha256 chưa ghim: `null`) |
| `workflows/<id>.json` | graph ComfyUI dạng **API** (không subgraph, không node bị bypass), giá trị mặc định do lab đặt |
| `workflows/<id>.meta.json` | bản đồ tham số (node → input), luật khung hình/kích thước, phần tuỳ chọn, ref và guide |

## Cài đặt trên máy chủ dự án

- ComfyUI có sẵn: **Comfy Desktop** (ComfyUI v0.43.1, Python 3.13, torch cu130) ở
  `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI` (`ComfyUI\.venv\Scripts\python.exe` + `ComfyUI\main.py`; `standalone-env` chỉ là trình
  thông dịch gốc, không có torch). Đây là
  `FILM_COMFY_HOME` mặc định trên Windows. Bản portable (`python_embeded\python.exe` + `ComfyUI\main.py`) cũng dùng được
  khi trỏ `FILM_COMFY_HOME` vào nó.
- Model dùng chung của Desktop: `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\models` (= `FILM_COMFY_MODELS` mặc định).
- `install` **không bao giờ tải model**: chỉ kiểm và in file nào thiếu. `install --portable` tải và giải nén bản portable
  ghim trong lock (kiểm sha256) khi máy chưa có ComfyUI nào.

```bash
python tools/comfy/comfy.py install --dry-run          # ComfyUI ở đâu, layout, phiên bản; model đủ chưa
python tools/comfy/comfy.py models --verify            # có mặt / đúng kích thước / sha256 (chỉ khi lock ghim)
python tools/comfy/comfy.py start                      # chạy ComfyUI không giao diện; không làm gì nếu đã có server
python tools/comfy/comfy.py ping                       # phiên bản, torch, GPU, VRAM, có --offline không
python tools/comfy/comfy.py workflows                  # các workflow, tham số, ràng buộc
```

`start` chạy chính môi trường Python của Desktop, **không đụng tới cài đặt của Desktop**:
`<python> -s <home>\ComfyUI\main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --offline
--extra-model-paths-config <yaml instance của Desktop> --input/--output/--temp/--user-directory <FILM_COMFY_WORK>\...`,
chạy tách rời, log vào `<FILM_COMFY_WORK>\server.log`, chờ tối đa `--wait` giây. `FILM_COMFY_WORK` mặc định là
`out\_comfy\` của lab (git bỏ qua, trên ổ của lab): ảnh tải lên, clip, file tạm của lab không rơi vào thư mục
`ComfyUI-Shared\input|output` của Desktop (ổ C: ít chỗ, và đó là file riêng của chủ lab). Model vẫn đọc từ thư mục
model chung của Desktop. `--offline` chặn các
**node API trả phí** (partner nodes); nếu bản ComfyUI không có cờ đó thì `start` từ chối. Nếu đã có server trả lời ở
`FILM_COMFY_URL` (ví dụ app Desktop đang mở) thì `start` báo và không làm gì. `start --dry-run` chỉ in lệnh.

## Workflow

| id | ledger `model` | đầu vào | model |
|---|---|---|---|
| `h3-i2v` | `comfy:h3-i2v` | `--image` khung đầu, tuỳ chọn `--last` khung cuối (first-last frame); không `--image` = text-to-video | `minimax_h3_fl2va_pruned_int8_convrot` |
| `h3-r2v` | `comfy:h3-r2v` | `--ref` 1–9 ảnh tham chiếu (`<Picture 1..n>` trong prompt), tuỳ chọn `--guide GIÂY=ẢNH` neo hình theo thời gian | `minimax_h3_ref2va_pruned_int8_convrot` |
| `qwen-t2i` | `comfy:qwen-image` (kind `image`) | chỉ chữ: `--prompt`/`--prompt-file` (file chữ UTF-8), `--negative`, `--size WxH` | `qwen_image_2512_fp8_e4m3fn` (mục "Tạo ảnh concept") |
| `hunyuan3d` | `comfy:hunyuan3d` (kind `image`) | `--image` concept nền trắng, `--octree 256\|512`, `--steps`, `--cfg`, `--seed`, `--allow-bg` | `hunyuan_3d_v2.1` (mục "Tạo phôi 3D") |

Cả hai dùng chung text encoder `qwen3vl_32b_minimax_h3_nvfp4_awq` (`CLIPLoader` type `minimax`), VAE hình
`minimax_h3_video_vae_int8_convrot`, VAE tiếng `minimax_h3_audio_vae_fp32`; đầu ra mp4 H.264 có tiếng
(`VAEDecodeAudio` → `CreateVideo` → `SaveVideo`). Graph dựng lại từ template chính thức của ComfyUI
(`video_minimax_h3_i2v`, `video_minimax_h3_r2v`, `video_minimax_h3_multiframe_reference`): chỉ lấy lớp node, tên input và
cách nối; mọi giá trị (prompt, thời lượng, kích thước, seed, số bước, công tắc Lightning) là của lab.

Luật của H3 (comfy.py tự áp dụng):
- **24 fps**, độ dài khung là lưới **17k+5**: `--seconds` được làm tròn **lên** (5 s → 124 khung = 5,17 s; 10 s → 243;
  tối đa 362 khung ≈ 15 s; dưới 124 khung là ngoài khoảng đã huấn luyện, in cảnh báo). Ledger ghi độ dài thật của clip.
- Khung **768p = 1344×768** (khung huấn luyện, mặc định, bản chất lượng) · **480p = 864×480** (bản nháp).
- Node H3 **kéo giãn** khung đầu vào cho vừa khung: comfy.py **cắt giữa** ảnh theo đúng tỉ lệ khung rồi thu phóng
  **Lanczos** về đúng kích thước, vào một file tạm, trước khi tải lên (không bao giờ đụng file gốc, không bao giờ
  nearest-exact). Áp dụng cho `--image`, `--last`, `--guide`; ảnh `--ref` được tải lên nguyên trạng (node tự thu nhỏ theo
  `--ref-size match|max`).
- Checkpoint đã chưng cất CFG: `BasicGuider` (cfg 1), **không có prompt âm** (`--negative` bị từ chối).
- 20 bước mặc định. `--turbo` bật LoRA Lightning (h3-i2v 6 bước, h3-r2v 4 bước): **chỉ cho bản nháp**, không dùng cho
  cảnh có mặt người hay bản chất lượng (in cảnh báo).
- Tốc độ đo trên máy chủ dự án (2026-11-25): clip 5,17 s (124 khung) 1344×768, 20 bước = 713 s GPU, ~34 s mỗi bước
  (model 20 GB chạy từ RAM vì VRAM 16 GB); bản nháp 864×480 ~10 s mỗi bước (log Desktop) ≈ 4 phút cho 5 s.
  `run` in ước lượng theo số này.

### Prompt

`--prompt "..."` (nguyên văn) hoặc `--prompt-file F.json|F.yaml` với đúng các trường, comfy.py ghép thành các khối
`tên_trường:` + nội dung, cách nhau một dòng trống:
- `h3-i2v` có khung đầu: dòng đầu tiên là nguyên văn
  `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
  (comfy.py tự thêm nếu prompt chưa có), một dòng trống, rồi `integrated_multimodal_description`, `overall_soundscape`,
  `non_diegetic_music`.
- text-to-video (`h3-i2v` không `--image`): ba trường trên, không có dòng đầu.
- `h3-r2v`: `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`,
  `non_diegetic_music`; ảnh tham chiếu gọi là `<Picture 1>`, `<Picture 2>`… theo thứ tự `--ref`.

## Tạo clip

```bash
python tools/comfy/comfy.py run h3-i2v --image clips/ep01_s03_start_v01.png --prompt-file s03.json \
    --seconds 5 --out out/<project>/ep01/clips/ep01_s03_clip_v01.mp4 --ledger out/<project>/ep01/ledger.csv --dry-run
python tools/comfy/comfy.py run h3-i2v --image START.png --last END.png --prompt-file s03.json --res 480p --turbo \
    --out out/<project>/ep01/clips/ep01_s03_draft_v01.mp4 --ledger out/<project>/ep01/ledger.csv
python tools/comfy/comfy.py run h3-r2v --ref hero.png --ref place.png --guide 0=key1.png --guide 4.5=key2.png \
    --prompt-file s07.yaml --seconds 6 --out out/<project>/ep01/clips/ep01_s07_clip_v01.mp4 --ledger out/<project>/ep01/ledger.csv
python tools/comfy/comfy.py interrupt --ledger out/<project>/ep01/ledger.csv      # dừng job của mình đang chạy
```

- `--dry-run`: kiểm hết, in tóm tắt graph (số node, kích thước, khung, seed, cách cắt ảnh, model, prompt đã ghép, ước
  tính thời gian GPU), không liên lạc server, không ghi ledger. Luôn chạy trước.
- Luồng: kiểm tại chỗ → `/system_stats` + `/object_info` (node và model có trên server không) → cắt/thu phóng khung
  → tải ảnh lên (`/upload/image`, tên duy nhất theo request) → dòng ledger `pending` (đã có `task_id` = prompt id) →
  `POST /prompt` → hỏi `/history/<id>` mỗi 2 s, in dòng `step <trạng thái> elapsed <s>s` → tải mp4 qua `/view`, ghi
  nguyên tử → sidecar `<out>.json` → dòng ledger cuối.
- Sidecar `<out>.json`: workflow, sha256 của file workflow và của graph đã điền (graph cũng được lưu), prompt id, seed,
  prompt, kích thước, số khung, fps, bước, turbo, guide, ảnh vào (sha256 gốc và bản đã tải lên), file model, phiên bản
  ComfyUI/torch/GPU, giây GPU (từ mốc `execution_start` → `execution_success`).
- `--keep-frames`: tách thêm khung PNG gốc vào `<clips>/<tên clip không đuôi>/raw/000001.png…` (cần ffmpeg) – đúng chỗ
  `check_episode.py` chấp nhận và `tools/layers/matte_seq.py` đọc khung gốc.
- `--seed` mặc định ngẫu nhiên, luôn in ra và ghi lại; `--timeout` (mặc định 2400 s) quá thì job bị dừng.
- **Hàng đợi GPU**: `run` (trừ `--dry-run`) giữ khoá GPU chung của lab (`tools/gpu_run.py`) từ ngay trước dòng ledger
  `pending` tới khi job xong; Blender hay job khác đang giữ thì chờ (in người giữ). `FILM_GPU_WAIT=<giây>` từ chối
  (mã 2, chưa gửi gì, không dòng ledger) khi chờ quá; `FILM_GPU_QUEUE=0` tắt hàng đợi. Lấy được khoá thì kiểm lại
  đầu ra (lần chạy khác cùng `--out` có thể đã xong trong lúc chờ: mã 2, chưa gửi gì, không dòng ledger); lúc tải về
  không bao giờ ghi đè file vừa xuất hiện.
- **Giải phóng VRAM**: hết job (thành công hay lỗi), trước khi nhả khoá, `run` gọi `POST /free`
  (`unload_models`, `free_memory`) để việc kế tiếp (render Blender) có đủ 16 GB. `--keep-models` bỏ bước này khi chạy
  nhiều job comfy liên tiếp (lần sau khỏi nạp lại model 20 GB); job cuối của loạt thì bỏ cờ.
- Mất server khi đang hỏi `/history`: `run` giữ khoá thêm tối đa 10 phút, chờ prompt rời hàng đợi (`/queue`) rồi mới
  nhả; quá hạn thì dòng ledger ghi `MAY STILL RUN` kèm lệnh `comfy.py interrupt --prompt-id <id>`.

## Tạo ảnh concept (`qwen-t2i`)

Qwen-Image 2512 (fp8) chạy local, miễn phí: ảnh concept (sinh vật, đạo cụ, bối cảnh) để người dùng chọn trước khi dựng
3D. Model đã có trên máy chủ lab (bộ `qwen-image` trong `comfy.lock.json`): không tải gì.

```bash
python tools/comfy/comfy.py run qwen-t2i --prompt "..." --size 1664x928 --seed 7 \
    --out out/<project>/<id>/concepts/<id>_phuong-hoang_v01.png --ledger out/<project>/<id>/ledger.csv --dry-run
python tools/comfy/comfy.py run qwen-t2i --prompt-file concept.txt --turbo --seed 7 \
    --out out/<project>/<id>/concepts/<id>_phuong-hoang_draft_v01.png --ledger out/<project>/<id>/ledger.csv
```

- Graph (node lõi của ComfyUI): `UNETLoader` → `ModelSamplingAuraFlow` (shift 3.1) → `KSampler` (euler/simple, 30 bước,
  cfg 2.5); `CLIPLoader` `type: qwen_image` (`qwen_2.5_vl_7b_fp8_scaled`); `EmptySD3LatentImage`; `VAEDecode`
  (`qwen_image_vae`); `SaveImage`. `--turbo` chèn `LoraLoaderModelOnly` (Wuli Turbo LoRA 2 bước, cfg 1): **chỉ nháp**.
- `--size WxH` bội số 16, mỗi cạnh 256–2048 (mặc định 1664x928); ngoài các khung đã huấn luyện (1328x1328, 1664x928,
  928x1664, 1472x1104, 1104x1472, 1584x1056, 1056x1584) thì cảnh báo. `--steps`, `--cfg`, `--negative` đè mặc định.
- Từ chối (2): cờ của video (`--image`, `--last`, `--ref`, `--guide`, `--seconds`, `--res`, `--keep-frames`), `--out`
  không phải `.png` hoặc đã có (tăng `_v<NN>`), size sai; các luật chung (allow list, server, model, ledger) như clip.
  Ngược lại `--size`/`--cfg` với workflow H3 cũng bị từ chối.
- Đầu ra: `<out>.png` + sidecar `<out>.png.json` (prompt, negative, seed, size, bước, cfg, turbo, model, graph, giây GPU).
  Ledger: `kind image`, `model comfy:qwen-image`, `size WxH`, `count 1`, chi phí 0.
- Tiến độ: comfy.py nghe websocket `/ws` của ComfyUI (thư viện chuẩn) và in `step <n>/<tổng>` mỗi bước sampler; không
  mở được websocket thì báo tiến độ theo thời gian ước lượng. `--review BUILD`: build kiểu `image`, mỗi bước sampler
  là một sự kiện tiến độ, ảnh xong là một `step` (không gửi prompt lên trang công khai).
- Tốc độ (chủ lab đo, RTX 5070 Ti, model đã nạp): **~135 s cho 30 bước ở 1664x928**; `run` ước lượng theo
  ~4 s mỗi bước × số điểm ảnh + ~15 s; `--turbo` ~25 s. Lần chạy đầu của phiên thêm thời gian nạp model (20 GB).
- Graph chưa được xác nhận với `/object_info` của server thật (`"verified": false`); bản thử tạm của chủ lab chạy được
  với cùng các node lõi.

## Tạo phôi 3D (`hunyuan3d`)

Hunyuan3D 2.1 chạy local, miễn phí: **một ảnh concept → một mesh GLB không màu**, phôi để điêu khắc/retopo trong Blender
(`tools/blender/blender.py mesh-prep`; quy trình đủ: `.claude/skills/film-compose-shot/references/blender-method.md` §7).
Model `checkpoints/hunyuan_3d_v2.1.safetensors` (bản đóng gói Comfy-Org, 7,4 GB) đã có trên máy chủ lab.

```bash
python tools/comfy/comfy.py run hunyuan3d --image <concept_trang>.png --seed 7 --dry-run \
    --out out/<project>/characters/<c>/<c>_raw_v01.glb --ledger out/<project>/<id>/ledger.csv
python tools/comfy/comfy.py run hunyuan3d --image <concept_trang>.png --seed 7 --octree 512 --steps 50 \
    --out out/<project>/characters/<c>/<c>_raw_v02.glb --ledger out/<project>/<id>/ledger.csv
```

- Graph (node lõi, dựng lại từ template `3d_hunyuan3d-v2.1` của ComfyUI): `LoadImage` → `CLIPVisionEncode` (cắt giữa) →
  `Hunyuan3Dv2Conditioning`; `ImageOnlyCheckpointLoader` → `ModelSamplingAuraFlow` (shift 1.0) → `KSampler` (euler/normal,
  30 bước, cfg 5, denoise 1) trên `EmptyLatentHunyuan3Dv2` (4096) → `VAEDecodeHunyuan3D` → `VoxelToMesh` (surface net,
  ngưỡng 0,6) → `SaveGLB`.
- **Ảnh vào**: toàn thân trên nền trắng trơn (làm bằng Qwen-Image-Edit). `run` kiểm một viền 2 % quanh ảnh: dưới 98 %
  điểm ảnh trắng (nền màu, thân chạm mép) → từ chối (2); `--allow-bg` vẫn gửi (cảnh báo). Ảnh PNG trong suốt tính
  là nền trắng. Trước khi tải lên: cắt theo khung bao của vật (bỏ đốm lẻ ở mép), đệm thành ảnh vuông trắng 1024×1024, vật
  chiếm 85 % cạnh (`CLIPVisionEncode` cắt giữa: ảnh rộng sẽ mất đầu/đuôi), vào file tạm; file gốc không bị đụng.
- `--octree 256` (mặc định, `num_chunks` 8000, ~40 s với 30 bước) · `512` (`num_chunks` 32000, chi tiết hơn; dùng
  `--steps 50`, ~3 phút). Nên chạy 2–4 seed ở 256 để chọn rồi chạy 512 cho seed được chọn.
- Từ chối (2): cờ của workflow khác (`--prompt`, `--negative`, `--size`, `--turbo`, `--last`, `--ref`, `--guide`,
  `--seconds`, `--res`, `--keep-frames`), thiếu `--image`, `--out` không phải `.glb` hoặc đã có, octree khác 256/512,
  server thiếu node hay checkpoint; ngược lại `--octree`/`--allow-bg` với workflow khác cũng bị từ chối.
- Đầu ra: `<out>.glb` (tải về nguyên tử, không bao giờ thay file có sẵn) + sidecar `<out>.glb.json` (seed, bước, cfg,
  octree, ảnh vào: sha256, khung bao, kết quả kiểm nền; số đỉnh/tam giác của mesh, graph, giây GPU, giấy phép, lệnh
  `mesh-prep` gợi ý). Ledger: `kind image`, `model comfy:hunyuan3d`, `size 1024x1024`, `count 1`, ghi chú
  `req=<hex>; seed=<n>; steps=<n>; octree=<n>`, chi phí 0. `--review BUILD`: build kiểu `model`, mesh xong là một `step`
  có GLB (engine `comfy-hunyuan3d`).
- Mesh ra **không kín**, không vòng cạnh, phần mảnh (vây, tóc, gạc) vỡ: luôn qua `blender.py mesh-prep`. Giấy phép
  trọng số: **Tencent Hunyuan 3D 2.1 Community License – không áp dụng ở EU, Anh, Hàn Quốc** (`THIRD_PARTY.md`,
  `docs/MODELS.md`).
- Graph chưa xác nhận với `/object_info` của server thật (`"verified": false`); script thử của chủ lab chạy được với cùng
  node, cùng giá trị.

### Mã thoát và ledger

- **0** xong · **2** bị từ chối tại chỗ, chưa tải gì lên, chưa xếp hàng, không có dòng ledger (sửa lệnh) · **1** job đã
  vào hàng đợi rồi lỗi / bị dừng / quá giờ (xem dòng ledger), hoặc server không trả lời (`ping`, `interrupt`).
- Từ chối (2): workflow lạ; graph có lớp node ngoài danh sách cho phép (node API trả phí như `Minimax*Node` của
  `comfy_api_nodes` không bao giờ chạy được từ đây); file vào thiếu hoặc không phải ảnh; `--out` (hoặc sidecar) đã tồn
  tại (tăng `_v<NN>`); `--negative`; `--last` không có `--image` hoặc với `h3-r2v`; `--ref`/`--guide` sai workflow; số
  ref ngoài 1–9; guide nằm ngoài clip; clip dài quá 362 khung; server không có node/model; server tắt; thiếu `--ledger`.
  `--no-ledger` chỉ cho thử tay ở phiên chính, bị từ chối khi có `FILM_AGENT`.
- Ledger (bộ ghi và khoá của `tools/ark.py`): `kind video`, `model comfy:<workflow>`, `size WxH`, `seconds` thật của clip,
  `task_id` = prompt id, `usage gpu_s=<n>`, ghi chú `req=<hex>; seed=<n>`, trạng thái cuối `ok | failed | interrupted`.
  `ark.py` tính các dòng `comfy:` (và `blender:`) bằng **0** với mọi trần (`images`, `video_seconds`, `models.*`), nên
  `run` không cần `--budget`.
- Job mồ côi (tiến trình `run` chết giữa chừng): `comfy.py interrupt --prompt-id <task_id>` để dừng trên server, rồi
  `python3 tools/ark.py ledger-close --req <id> --status abandoned --ledger L` để đóng dòng.

## Biến môi trường

`FILM_COMFY_URL` (mặc định `http://127.0.0.1:8188`) · `FILM_COMFY_HOME` · `FILM_COMFY_MODELS` · `FILM_COMFY_PYTHON`
(python cho `start`) · `FILM_COMFY_MODEL_PATHS` (yaml extra_model_paths cho `start`; mặc định yaml instance mới nhất trong
`%APPDATA%\Comfy Desktop\instance-model-paths\`) · `FILM_LEDGER` · `FILM_AGENT`. Không cần và không đọc khoá nào; comfy.py
chỉ liên lạc `FILM_COMFY_URL` (trừ `install --portable`), không qua proxy.

## Kiểm thử

`tests/test_comfy.py` (và `tests/test_comfy_mesh.py` cho `hunyuan3d`) dựng một server ComfyUI giả (thư viện chuẩn, trong thread, có websocket `/ws` gửi tiến độ sampler) và kiểm mọi đường từ chối, lưới
khung/kích thước, cắt ảnh, dry-run, đường thành công (file + sidecar + ledger, không tốn trần), lỗi thực thi, quá giờ →
`interrupted`, `models --verify`, `install --dry-run`, `start`; `tests/test_comfy_ark.py` kiểm luật chi phí 0 và khoá
ledger khi không có `fcntl` (Windows). Không cần GPU, chạy được trong WSL. Graph thật chỉ được xác nhận khi chạy với
`/object_info` của server thật (`"verified": false` trong meta cho tới lúc đó).
