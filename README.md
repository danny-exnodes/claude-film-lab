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
3. Nói với Claude, ví dụ: *"Làm tập 1 Sơn Hải Kinh"* hoặc *"Tiếp tục tập ep01-<slug>"*. Skill `film-pipeline`
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
| `.claude/agents/` | 8 agent theo vai: researcher, writer, art-director, plate-maker, animator, compositor, reviewer, publisher |
| `styles/` | Style pack: `thuy-mac` (ổn định), `moc-ban` (nháp), `_template` |
| `templates/project/` | Mẫu dự án mới: `PROJECT.md` (manifest ID Drive), `SERIES.md`, `README_CauTruc.md`, `TienDo_SanXuat.csv` |
| `templates/episode/` | Mẫu `EPISODE.md`, `budget.yaml`, `shots.csv`, `prompts.csv` |
| `tools/ark.py` | CLI Ark: `ping`, `image`, `video`, có `--budget`/`--ledger` |
| `tools/check_episode.py` | Kiểm tra tập và style pack (schema, nhịp, tên file) |
| `tools/layers/` | Tách alpha (`matte.py`), điểm neo (`anchors.py`), upscale |
| `tools/compose/` | Bộ JS dựng 2.5D cho cinecode: parallax, sương, tàn lửa, đung đưa, chớp mắt, thở |
| `tools/bundle.py` | Gói zip theo shot để lưu Google Drive |
| `tools/doctor.sh` | Kiểm tra môi trường (miễn phí) |
| `lambda/` | Worker tạo ảnh ngoài proxy (pro, 4K) – chưa triển khai |
| `formats/` | Định dạng cinecode đã lưu (`CINECODE_FORMATS`) |
| `tests/` | `python3 -m unittest discover -s tests` |
| `projects/` | Bản làm việc chữ của dự án, kéo từ Drive (git bỏ qua) |
| `out/` | Media sinh ra (git bỏ qua) |

## Phát triển
```bash
python3 -m unittest discover -s tests
python3 tools/check_episode.py style styles/thuy-mac
python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug>   # sau khi kéo dự án từ Drive
tools/doctor.sh
```
Đổi schema → sửa `docs/CONVENTIONS.md` trước. Thay đổi ghi vào `CHANGELOG.md`.

## Cấu hình môi trường (trên claude.ai, làm một lần)
- **Network secrets**: khóa Ark cho `ark.ap-southeast.bytepluses.com` (proxy chèn vào request).
- **Connectors**: Google Drive (dữ liệu dự án và sản phẩm, bắt buộc), AWS (Lambda, khi triển khai).
- **Setup script**: dán nội dung `docs/setup-script.sh` (cài ffmpeg, font, Chrome, `rembg`, cinecode và shim
  `/opt/byteplus/ark.py` gọi sang `tools/ark.py` của repo). Hook khởi động vẫn kiểm tra lại font và gói Python.
