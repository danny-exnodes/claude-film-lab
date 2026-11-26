# Model BytePlus Ark – đối chiếu và lựa chọn

Kiểm tra ngày 2026-11-10 trên tài khoản Ark của Film Lab. Model trong Console phải ở trạng thái **Activated**.

## Model đã kích hoạt

| Tên trên Console | ID trong API | Dùng cho | Đo được (qua proxy cloud) |
|---|---|---|---|
| Dola-Seedream-5.0-lite | `seedream-5-0-lite-260128` | **Ảnh mặc định** (`tools/ark.py image`), chỉ khi **không** `--ref` | 2K: ~25–26 s ✅ · 2K + `--ref`: 502 ở 31 s ❌ · 4K: bị cắt ở 30 s ❌ |
| Dola-Seedream-5.0-flash | `dola-seedream-5-0-flash-260915` | **Lớp tranh sản xuất** (`--fast`), nhất là có `--ref` | 1024²: ~11 s ✅ · 2K/2560x1440 + `--ref`: ~75 ảnh, 0 lần 502 ✅ |
| Dola-Seedream-5.0-pro | `dola-seedream-5-0-pro-260628` | Ảnh chất lượng cao – **chỉ qua Lambda** (`ark.py lambda-job`, `lambda/README.md`) | 1024² và 2K: luôn > 30 s → 502 ❌ · qua Lambda 2K: **77,3 s** ✅ (2026-11-10, 1 ảnh, trả 1664×2496: `2K` không cố định tỉ lệ, luôn truyền `WxH`) · 4K: chưa đo |
| ByteDance-Seedream-4.5 | `seedream-4-5-251128` | Ảnh dự phòng | 2K ✅ |
| ByteDance-Seedream-4.0 | `seedream-4-0-250828`, `seedream-4-0-20260415` | Ảnh dự phòng | 1024²: 7–9 s ✅ |
| Dreamina-Seedance-2.5 | `dreamina-seedance-2-5-260628` | **Video mặc định** | 5 s 720p: ~2,5 phút ✅ (task bất đồng bộ); `ark.py video` mặc định `--resolution 720p` (1080p chưa đo) |

## Lưu ý
- `seedream-5-0-lite-260128` hoạt động nhưng **không xuất hiện** trong `GET /models`.
- `seedream-5-0-260128` và `dreamina-seedance-2-0-*` (mặc định cũ của ark.py) **không có** trong danh sách kích hoạt được
  → lỗi `ModelNotOpen`.
- Không có model LLM/VLM nào được kích hoạt (deepseek, glm, seed-2-x đều `ModelNotOpen`).
- Seedream trả ảnh JPEG; `ark.py` tự chuyển sang PNG khi tên file đuôi `.png`.
- Seedance 2.5 tự thêm âm thanh; `--no-audio` gửi `generate_audio=false` (đã xác minh).
- **Seedance 2.5 image-to-video từ chối `ratio`** (HTTP 400 khi có ảnh khung đầu; ảnh quyết định tỉ lệ, đã xác minh
  khi sản xuất q01t01). Từ nay `ark.py video --image` **không gửi** `ratio`; truyền `--ratio` cùng `--image` chỉ in
  cảnh báo và gửi đúng giá trị đó (API có thể trả 400). Muốn clip 16:9 thì tự làm khung đầu 16:9 (vd. 1280x720,
  `tools/compose/keyframe.py` ra 1920x1080); ảnh vuông cho clip vuông (720p → 960×960). Không có `--image` → `ratio=16:9`.
- Seedance 2.5 `duration`: API nhận **4–30 s** (API kiểm tham số, xác minh 2026-11-10); clip dài hơn 5–8 s chưa thử thực tế.
- Seedream có `--ref` chậm hơn: `seedream-5-0-lite` ở 2K **kèm `--ref`** vượt mốc cắt 30 s của proxy (502 ở 31 s, có thể
  vẫn tính phí); `dola-seedream-5-0-flash` ở 2K/2560x1440 kèm `--ref` chạy ~75 ảnh không một lần 502.
  → **Lớp tranh sản xuất dùng flash (`--fast`)**; lite chỉ dùng khi không có `--ref`.
- Link video (`*.tos-ap-southeast-1.volces.com`) có hạn dùng → tải về ngay (ark.py đã làm).
- `ark.py image-batch` gửi N request `image` đồng bộ thông thường (tối đa 4 cùng lúc), **giá từng ảnh như cũ**: nó giảm
  chi phí nhờ không tạo lại ảnh đã có và chặn cả lô trước khi vượt trần, không nhờ giá lô. **Chưa xác minh** (issue #28,
  cần request trả tiền để thử, nên chưa làm): Batch API bất đồng bộ của Ark (giá lô) và chế độ tạo chuỗi ảnh
  (sequential / group image generation) của Seedream. Giới hạn tốc độ (HTTP 429) khi chạy 3–4 request song song cũng
  chưa đo; gặp 429 thì chạy lại với `--parallel 1`.

## Kiểm tra miễn phí
- Video: gửi tham số sai (vd. `resolution: "9999p"`) → `InvalidParameter` = đã kích hoạt, `ModelNotOpen` = chưa.
- Ảnh: **không kiểm miễn phí được** – API ảnh kiểm tham số trước khi kiểm kích hoạt; muốn chắc phải gen 1 ảnh nhỏ.

## Model local (máy chủ lab, ComfyUI) – miễn phí, chỉ phiên local

Chạy bằng `tools/comfy/comfy.py` trên Comfy Desktop của chủ lab (RTX 5070 Ti 16 GB); model đã có sẵn trên máy, **không tải
thêm gì**. Dòng ledger `comfy:<workflow>` không tính vào trần nào. Cách dùng:
`.claude/skills/film-compose-shot/references/local-video.md`.

| Model | File (bản đóng gói Comfy-Org/MiniMax-H3) | Workflow | Dùng cho | Đo được |
|---|---|---|---|---|
| MiniMax H3 – image/first-last-frame to video | `minimax_h3_fl2va_pruned_int8_convrot` | `h3-i2v` | clip từ khung đầu, tuỳ chọn khung cuối (nối hai khung Blender) | 20 bước ~34 s mỗi bước ở 1344×768: ≈ 12 phút cho clip 5 s (đo 2026-11-25: 713 s); nháp 864×480 ≈ 4 phút |
| MiniMax H3 – reference to video | `minimax_h3_ref2va_pruned_int8_convrot` | `h3-r2v` | tối đa 9 ảnh tham chiếu + mốc "Add Guide" | chưa đo |
| Bộ mã hoá chữ | `qwen3vl_32b_minimax_h3_nvfp4_awq` | cả hai | | |
| VAE hình / âm thanh | `minimax_h3_video_vae_int8_convrot`, `minimax_h3_audio_vae_fp32` | cả hai | clip có âm thanh tự sinh | |
| LoRA Turbo | `minimax_h3_fl2v_turbo_8step_v1.0`, `minimax_h3_ref2v_turbo_4step_v0.1` | nháp | **chỉ bản nháp**, không cho bản dùng hay mặt nhân vật | |
| Qwen-Image 2512 – text to image | `qwen_image_2512_fp8_e4m3fn` + bộ mã hoá `qwen_2.5_vl_7b_fp8_scaled` + VAE `qwen_image_vae` | `qwen-t2i` | ảnh concept (sinh vật, đạo cụ, bối cảnh) để người dùng chọn trước khi dựng 3D; ledger `comfy:qwen-image`, kind `image` | 30 bước ở 1664×928 ≈ **135 s** mỗi ảnh (chủ lab đo, model đã nạp); lần đầu của phiên thêm thời gian nạp model |
| LoRA Turbo Qwen | `Wuli-Qwen-Image-2512-Turbo-LoRA-2steps-V1.0-bf16` | `qwen-t2i --turbo` | 2 bước, cfg 1: **chỉ nháp**, không phải ảnh người dùng duyệt | ước lượng ~25 s |
| Hunyuan3D 2.1 – image to 3D | `hunyuan_3d_v2.1` (`checkpoints/`, bản đóng gói Comfy-Org, 7,4 GB) | `hunyuan3d` | **phôi** điêu khắc (mesh không màu) của sinh vật từ concept đã duyệt, nền trắng, toàn thân; ledger `comfy:hunyuan3d`, kind `image` | octree 256 + 30 bước ≈ **40 s** mỗi mesh (đỉnh VRAM cả card ~8,8 GB); octree 512 + 50 bước ≈ **3 phút** (~9,8 GB); chủ lab đo 2026-11-26 |

- H3: 24 hình/s, số khung theo lưới `17k + 5`, bản dùng 1344×768 (7:4), nháp 864×480 (≈ 1 phút cho 5 s, ước lượng);
  không negative prompt (cfg 1); prompt tiếng Anh theo trường.
- Qwen-Image (`qwen-t2i`): KSampler euler/simple, 30 bước, cfg 2.5, shift 3.1 (ModelSamplingAuraFlow); `--size` bội số 16,
  khung đã huấn luyện 1328×1328, 1664×928, 928×1664, 1472×1104, 1104×1472, 1584×1056, 1056×1584; có `--negative`.
  `python tools/comfy/comfy.py run qwen-t2i --prompt "..." --size 1664x928 --seed N --out <concepts>/<id>_v<NN>.png --ledger L`.
- Hunyuan3D 2.1 (`hunyuan3d`): `ImageOnlyCheckpointLoader` → `ModelSamplingAuraFlow` (shift 1.0) → `KSampler` (euler/normal,
  cfg 5); `CLIPVisionEncode` (cắt giữa) → `Hunyuan3Dv2Conditioning`; `EmptyLatentHunyuan3Dv2` (4096) →
  `VAEDecodeHunyuan3D` (octree 256/512) → `VoxelToMesh` (surface net, 0,6) → `SaveGLB`. Mesh 137k–1M tam giác, **không
  kín** (hàng chục nghìn cạnh non-manifold, vài trăm cạnh hở), không vòng cạnh: luôn qua
  `python tools/blender/blender.py mesh-prep` trước khi điêu khắc/rig. Phần mảnh (vây, tóc, gạc) vỡ. Độ trùng bóng với
  concept (IoU) 0,85–0,99.
  **Giấy phép: Tencent Hunyuan 3D 2.1 Community License – không áp dụng ở EU, Anh, Hàn Quốc**; thương mại có điều kiện
  (ngưỡng người dùng hằng tháng, ghi nguồn): ghi vào `ASSETS.md` mọi model dựng từ mesh này, đọc bản giấy phép đi kèm
  model trước khi phát hành. Cách dùng: `.claude/skills/film-compose-shot/references/blender-method.md` §7.
- **Giấy phép:** open weights; điều khoản chưa được xác minh trong repo → **đọc model card trước khi dùng thương mại**
  (kênh có kiếm tiền) và ghi kết quả vào đây.
- Bản cài ComfyUI có node API **trả tiền** của MiniMax (`comfy_api_nodes/`): không dùng; `comfy.py` chỉ cho node trong
  danh sách cho phép, server chạy `--offline`.
- Có trên máy, **chưa nối** vào lab (không workflow, không công cụ): LTX-2.3 22B dev fp8 (+ spatial upscaler x2, distilled
  LoRA, bộ mã hoá gemma 3 12B fp4), SeedVR2 3B (phóng video), Qwen-Image-Edit 2511 (+ LoRA Lightning 4/8 bước) và
  Z-Image Turbo (model ảnh local), Wan Animate 2. Wan 2.2 và LTX-2.5 không dùng. ComfyUI lõi có node TRELLIS.2
  (ảnh → 3D có texture PBR) nhưng **model chưa tải** (~16 GB): hỏi chủ lab trước khi tải (`docs/BACKLOG.md`).
- Mọi job GPU local (Blender, ComfyUI) đi qua khoá GPU chung của lab `tools/gpu_run.py` (`out/_gpu/gpu.lock` của bản
  checkout chính, một khoá cho mọi worktree): `blender.py` và `comfy.py run` tự lấy khoá; lệnh GPU khác chạy qua
  `python tools/gpu_run.py --label <việc> -- <lệnh>`.

## Blender (render 3D local)

Blender 5.3 trên máy chủ lab (`tools/blender/blender.py find`), EEVEE (`BLENDER_EEVEE`, cần phiên Windows có GPU) hoặc
Cycles (OptiX/CUDA). Không model AI, không giấy phép model; model GLB ghi nguồn và giấy phép trong `ASSETS.md` của tập.
Dòng ledger `blender:*` không tính trần. Thời gian một shot (ước lượng, `tools/status.py`): `--preview` ~1 phút, bản dùng ~5 phút.
