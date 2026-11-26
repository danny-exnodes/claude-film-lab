# Clip AI chạy local: MiniMax H3 qua ComfyUI (`video_engine: comfy`)

Đọc file này khi `EPISODE.md` của tập ghi `video_engine: comfy` (chỉ đi với `method: seedance` hoặc `method: blender`).
Khâu 6 chạy `tools/comfy/comfy.py run` thay cho `ark.py video`: model MiniMax H3 (open weights, node ComfyUI gốc) chạy
trên GPU của chủ lab, **miễn phí**, không tải model nào thêm. `video_seconds` của `budget.yaml` để 0 được; dòng ledger
`comfy:*` không tính vào trần nào (`status.py` liệt kê riêng ở `LOCAL`).

**Chỉ trong phiên local trên máy của chủ lab** (Comfy Desktop, RTX 5070 Ti 16 GB). Phiên cloud không chạy được khâu 6
của tập này: dừng, ghi Nhật ký, báo người dùng mở phiên local. `tools/doctor.sh` dòng `comfy`: `n/a` khi chưa cấu hình,
`OK` khi `comfy.py ping` trả lời, WARN khi đã cấu hình mà server không chạy.

## 1. Luật cứng

- **Không bao giờ dùng node API trả tiền.** Bản cài ComfyUI có sẵn node API của các hãng (kể cả node MiniMax trả tiền
  trong `comfy_api_nodes/`): `comfy.py run` từ chối (mã 2, không gửi gì) mọi workflow có node ngoài danh sách cho phép.
  Không sửa danh sách đó để cho qua, không chạy workflow bằng tay qua giao diện cho clip của tập.
- Server: `comfy.py start` (Python của Comfy Desktop, không giao diện, `127.0.0.1:8188`, `--offline`). Ứng dụng Comfy
  Desktop đang mở cũng dùng được qua `FILM_COMFY_URL`; danh sách node cho phép vẫn áp dụng.
- Mọi lần chạy vẫn vào ledger của tập (`--ledger`, `FILM_AGENT` khi chạy trong agent): dòng `pending` trước khi gửi, dòng
  cuối `ok|failed|interrupted`, model `comfy:h3-i2v` / `comfy:h3-r2v`, `usage` = `gpu_s=<n>`. Không chạy lại một request
  đã gửi mà chưa xem `/history`; `comfy.py interrupt` chỉ dừng prompt của mình.
- Không ghi đè: `--out` đã có → mã 2, tăng `_v<NN>`. Mã thoát như `ark.py`: 0 xong · 2 từ chối tại chỗ · 1 đã gửi và lỗi.
- Một việc GPU một lúc: không chạy clip khi Blender đang render. `comfy.py run` tự giữ khoá GPU của lab và chờ khi việc
  khác đang giữ (`FILM_GPU_QUEUE=0` tắt); ai đang giữ: `python tools/gpu_run.py status`; lệnh GPU khác:
  `python tools/gpu_run.py --label <agent> -- <lệnh>`.

## 2. Lệnh

```
python tools/comfy/comfy.py ping                     # phiên bản ComfyUI, torch, GPU, VRAM trống
python tools/comfy/comfy.py start                    # chạy server local (không giao diện)
python tools/comfy/comfy.py workflows                # id, đầu vào, ràng buộc của từng workflow
python tools/comfy/comfy.py run h3-i2v --image <khung đầu>.png [--last <khung cuối>.png] --prompt-file <prompt>.json \
    --seconds 5 --seed N --out out/<project>/<id>/clips/<id>_s<NN>_h3_v<NN>.mp4 --ledger out/<project>/<id>/ledger.csv [--dry-run]
python tools/comfy/comfy.py run h3-r2v --ref <a>.png --ref <b>.png [--guide 2.5=<c>.png] --prompt-file <prompt>.json ...
python tools/comfy/comfy.py interrupt --ledger out/<project>/<id>/ledger.csv      # hoặc --prompt-id <id>
```
Bản nháp: `--res 480p` (864×480; mặc định `768p` = 1344×768), `--turbo` (LoRA Turbo, ít bước) chỉ cho nháp. `--seconds`
được làm tròn lên lưới khung của H3. `--prompt-file` (JSON/YAML với các trường của §4) thay cho `--prompt` một dòng.
`--dry-run` in đồ thị đã điền (node, kích thước, số khung, seed) mà không gọi server: chạy trước mỗi lần thật.
Cạnh mỗi clip là file `.json` (workflow + mã băm đồ thị, seed, prompt, kích thước, số khung, model, phiên bản ComfyUI,
giây GPU): giữ cùng clip, vào gói shot như clip.

## 3. Hai workflow

| Id | Đầu vào | Dùng khi |
|---|---|---|
| `h3-i2v` | khung đầu, tuỳ chọn khung cuối (nối hai khung) | cử động bắt đầu từ một khung đã duyệt; tập `blender`: hai khung của `blender.py keyframes` (khung đầu + cuối) → H3 nối giữa |
| `h3-r2v` | tối đa 9 ảnh tham chiếu (`--ref`, lặp lại) + mốc thời gian tuỳ chọn ("Add Guide": `--guide <giây>=<ảnh>`) | giữ một nhân vật/vật nhất quán qua nhiều góc khi không có khung đầu cố định |

Thông số H3: 24 hình/s; số khung theo lưới `17k + 5`; bản dùng 1344×768 (7:4), bản nháp 864×480; khung đầu bị cắt giữa
về 7:4 (lanczos) trong `comfy.py`, nên đặt chủ thể ở giữa (khung 16:9 mất ~0,8 % mỗi bên trái/phải; khung
Blender cho clip nên render đúng 1344×768). Không có negative prompt (cfg 1); mặc định 20 bước. LoRA Turbo/Lightning
**chỉ cho bản nháp**, không bao giờ cho bản dùng hay shot có mặt người/nhân vật cận.
Thời gian (đo trên máy chủ lab 2026-11-25): clip 5,17 s 1344×768, 20 bước = 713 s GPU (~34 s mỗi bước: model 20 GB
chạy từ RAM vì VRAM 16 GB) ≈ **12 phút cho 5 s**; bản nháp 864×480 ~10 s mỗi bước ≈ 4 phút cho 5 s (theo log Desktop
của chủ lab). Một tập 20 clip bản cuối ≈ 4 giờ GPU: duyệt bằng bản nháp trước. `status.py` FORECAST cộng phút GPU từ các hằng số này (ghi rõ "estimate").

## 4. Prompt (tiếng Anh, theo trường)

- `h3-i2v` (và T2V): `integrated_multimodal_description` (hình + chuyển động + máy quay trong một đoạn), `overall_soundscape`,
  `non_diegetic_music`.
- `h3-r2v`: sáu khối `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`,
  `non_diegetic_music`.
- Như clip Seedance: **một** chuyển động (từ `ai_motion`), máy quay đứng yên trừ khi shot cần, không chữ trên hình. Prompt
  đã dùng lưu `projects/<project>/<thư mục tập>/prompts/<tên clip>.txt`.

## 5. Âm thanh của clip

Clip H3 mang âm thanh tự sinh (soundscape). Compositor **quyết định giữ hay tắt** từng clip và ghi vào
`review/sound-audit.md`; mặc định **tắt** dưới lời bình và khi tập dùng nhạc/foley bằng code. Giữ chỉ khi người dùng
duyệt tiếng đó (ghi vào `## Đã khóa`).

## 6. Shot kiểu mới: thử trong giao diện trước

Workflow cho một kiểu shot mới (vd. nhiều mốc "Add Guide", nối ba khung) được thử trước trong giao diện ComfyUI (phác
sơ đồ → workflow giao diện chạy thử → xuất JSON dạng API), rồi mới thêm vào `tools/comfy/` để `comfy.py` dùng (đồ thị
API + file meta, node trong danh sách cho phép). Không đưa JSON chưa chạy thử vào sản xuất.

## 7. Sau khi có clip

- Tập `seedance`: tách nền như clip Seedance (`tools/layers/matte_seq.py <clip>.mp4 --start-frame <khung đầu> --strict`,
  `seedance-layer.md`), rồi dựng như cũ.
- Tập `blender`: clip là cả khung hình (không tách nền); compositor đặt nó vào shot thay cho đoạn render tương ứng,
  phóng 1344×768 theo chiều rộng khung dựng (1920 → cao 1097) và cắt ~8 px trên/dưới về 16:9.
- G3: mỗi shot có `ai_motion` phải có clip trong `clips/` (`check_episode.py` ERROR từ khâu 8).
