# Claude Film Lab

Bộ công cụ và quy trình chuẩn cho các phiên Claude Code cloud làm phim AI với BytePlus ModelArk.

## Dùng thế nào
1. Mở phiên Claude Code cloud với **môi trường Film Lab** và repo này làm nguồn.
2. Hook khởi động tự cài phụ thuộc, nạp `tools/ark.py` và in báo cáo kiểm tra môi trường.
3. Làm việc theo `CLAUDE.md`.

## Cấu trúc
| Đường dẫn | Nội dung |
|---|---|
| `CLAUDE.md` | Quy trình chuẩn và quy tắc cho Claude |
| `tools/ark.py` | CLI gọi Ark: `ping`, `image`, `video` |
| `tools/doctor.sh` | Kiểm tra môi trường (miễn phí) |
| `lambda/` | Worker tạo ảnh ngoài proxy (pro, 4K) + script triển khai qua AWS MCP |
| `docs/MODELS.md` | Đối chiếu model Console ↔ API, thời gian đo được |
| `docs/RUNBOOK.md` | Sự cố đã gặp và cách xử lý |
| `.claude/hooks/session-start.sh` | Hook khởi động phiên |
| `out/` | File gen ra (git bỏ qua) |

## Cấu hình môi trường (trên claude.ai, làm một lần)
- **Network secrets**: khóa Ark cho `ark.ap-southeast.bytepluses.com` (proxy chèn vào request).
- **Connectors**: Google Drive (lưu sản phẩm), AWS (Lambda).
- **Setup script**: giữ phần đang có (ffmpeg, Chrome, skill `cinecode`). Font CJK và `rembg` đã do hook của repo cài,
  không bắt buộc thêm vào setup script.
