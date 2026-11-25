# Claude Film Lab

Bộ công cụ, skill, agent và quy trình chuẩn để làm phim AI 2.5D nhiều lớp trong các phiên Claude Code cloud,
với BytePlus ModelArk (Seedream cho ảnh, Seedance cho video) và skill `cinecode` (dựng phim bằng code).

Repo này chỉ là **lõi dùng lại**. Dữ liệu của từng dự án phim (kinh thư, kịch bản, tập, prompt, tiến độ, tài liệu gốc,
media) nằm trên Google Drive `ClaudeFilmLab/<ProjectName>/` và được kéo về `projects/<project>/` (git bỏ qua) trong
mỗi phiên – xem `docs/CONVENTIONS.md` §11.

## Dùng thế nào
1. Mở phiên Claude Code cloud với **môi trường Film Lab** và repo này làm nguồn.
2. Hook khởi động tự cài phụ thuộc, trỏ `/opt/byteplus/ark.py` vào `tools/ark.py`, đặt `CINECODE_FORMATS`
   và in báo cáo kiểm tra môi trường.
3. Nói với Claude, ví dụ: *"Làm tập 1 Sơn Hải Kinh"* hoặc *"Tiếp tục tập ep01-<slug>"* (dự án chia quyển: *"Làm quyển 1 tập 1"*, thư mục `q01-t01-<slug>`). Skill `film-pipeline`
   kéo dự án từ Drive (`00_QuanLy/PROJECT.md` trước), đọc `EPISODE.md`, giao việc cho các agent theo vai, dừng ở 4 cổng
   duyệt (kịch bản, ảnh khóa, bản nháp, bản cuối) và đẩy kết quả lên Drive sau mỗi khâu.

## Cấu trúc
| Đường dẫn | Nội dung |
|---|---|
| `CLAUDE.md` | Quy tắc bắt buộc và quy trình cho Claude |
| `docs/CONVENTIONS.md` | Hợp đồng chung: cấu trúc, đặt tên, schema, quyết định thiết kế |
| `docs/WORKFLOW.md` | Quy trình một tập: khâu 0–11, cổng G1–G4, ngân sách, chuyển giao phiên |
| `docs/MODELS.md` · `docs/RUNBOOK.md` | Model Ark đã kiểm chứng · sự cố đã gặp và cách xử lý |
| `.claude/skills/` | `film-pipeline`, `film-script`, `film-prompt-layers`, `film-compose-shot` |
| `.claude/agents/` | 9 agent theo vai: researcher, writer, art-director, plate-maker, animator, compositor, reviewer, publisher, narrator (lồng tiếng, chưa gắn vào khâu nào) |
| `styles/` | Style pack ảnh: `thuy-mac` (ổn định), `moc-ban` (nháp), `_template`; style vẽ bằng code (`engine: code`, nháp): `dat-nan-3d`, `hoat-hinh-phang`, `ban-ve-ky-thuat`, `in-riso`, `pixel-16bit`, `bong-muc`, `ong-cao-su`, `chu-ascii`, `bia-cat-dan`, `low-poly-90`, `sach-pop-up`, `_template-code` |
| `templates/project/` | Mẫu dự án mới: `PROJECT.md` (manifest ID Drive), `SERIES.md`, `README_CauTruc.md`, `TienDo_SanXuat.csv` |
| `templates/episode/` | Mẫu `EPISODE.md`, `budget.yaml`, `shots.csv`, `prompts.csv` |
| `tools/ark.py` | CLI Ark: `ping`, `image`, `video`, có `--budget`/`--ledger`; `lambda-job prepare/finish` (ảnh qua Lambda vào ledger), `ledger-merge` |
| `tools/check_episode.py` | Kiểm tra tập và style pack (schema, nhịp, tên file) |
| `tools/layers/` | Tách alpha (`matte.py`), điểm neo (`anchors.py`), upscale |
| `tools/compose/` | Bộ JS dựng 2.5D cho cinecode: parallax, sương, tàn lửa, khói, lửa, lá lay, đung đưa, vải bay, đổi tư thế theo khung, nhân vật vẽ bằng nét mực cho cảnh rộng, chớp mắt, thở |
| `tools/toon/` | Bộ TOON cho `method: code`: nhân vật vẽ bằng code (rig, đi/chạy/nhảy/vẫy, chân không trượt), 8 look (canvas + three.js) và 3 hậu kỳ (riso, pixel, ASCII); `toon.py` xem thử miễn phí, `lookbook` cả 11 style; linh vật `demo/giot.json` |
| `tools/bundle.py` | Gói zip theo shot để lưu Google Drive |
| `tools/audio/` | Âm thanh tổng hợp local: dây gảy (cổ cầm, tỳ bà, koto), tiếng động theo sự kiện, `score.py` xuất stem WAV từ bản nhạc JSON |
| `tools/status.py` | Một màn hình chỉ đọc cho một tập: khâu, cổng, ngân sách còn lại, request dở, độ phủ lớp tranh, điều kiện cổng kế tiếp |
| `tools/layers/matte_seq.py` | Tách nền cả clip Seedance thành chuỗi khung, kèm số đo nhấp nháy |
| `tools/tts/vieneu_tts.py` | Lồng tiếng Việt local trên CPU (VieNeu-TTS v3 Turbo, Apache-2.0); cài riêng, xem `tools/tts/README.md` |
| `tools/drive_sync.py` | Đồng bộ Drive không gọi mạng: chụp dấu sau khi kéo, lập lệnh connector cho file đã đổi, ghi file đã đẩy |
| `tools/doctor.sh` | Kiểm tra môi trường (không tính phí) |
| `docs/BACKLOG.md` | Lỗi đã biết chưa sửa và việc hoãn lại sau đợt kiểm toán 2026-11-10 |
| `lambda/` | Worker tạo ảnh ngoài proxy (pro, 4K), đi qua `ark.py lambda-job` – đã triển khai (bản gia cố: 2026-11-11); ảnh thật đầu tiên 2026-11-10 (Pro 2K, 77 s) |
| `docs/RELEASING.md` | Bước phát hành: Claude sửa CHANGELOG + mở PR, người dùng tạo tag và GitHub Release |
| `formats/` | Định dạng cinecode đã lưu (`CINECODE_FORMATS`) |
| `tests/` | `python3 -m unittest discover -s tests` |
| `projects/` | Bản làm việc chữ của dự án, kéo từ Drive (git bỏ qua) |
| `out/` | Media sinh ra (git bỏ qua) |

## Phát triển
```bash
python3 -m unittest discover -s tests
python3 tools/check_episode.py style styles/thuy-mac
python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug>   # sau khi kéo dự án từ Drive (hoặc q<NN>-t<NN>-<slug>)
python3 tools/rename_episode.py ep01 q01t01 --project-dir projects/<project>/ep01-<slug> --media out/<project>/ep01   # đổi mã tập (thêm --apply)
python3 tools/toon/toon.py lookbook --draft                               # 11 style vẽ bằng code, miễn phí
tools/doctor.sh
```
Đổi schema → sửa `docs/CONVENTIONS.md` trước. Thay đổi ghi vào `CHANGELOG.md`. Phát hành: `docs/RELEASING.md`
(tag và GitHub Release do người dùng tạo tay; phiên cloud không push tag được).

## Cấu hình môi trường (trên claude.ai, làm một lần)
- **Network secrets**: khóa Ark cho `ark.ap-southeast.bytepluses.com` (proxy chèn vào request).
- **Connectors**: Google Drive (dữ liệu dự án và sản phẩm, bắt buộc), AWS (Lambda, khi triển khai).
- **Setup script**: dán nội dung `docs/setup-script.sh` (cài ffmpeg, font, Chrome, `rembg`, cinecode **ghim ở commit đã kiểm** và shim
  `/opt/byteplus/ark.py` gọi sang `tools/ark.py` của repo). Hook khởi động vẫn kiểm tra lại font và gói Python.
