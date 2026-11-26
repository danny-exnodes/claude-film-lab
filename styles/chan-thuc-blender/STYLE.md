# Chân thực Blender (`chan-thuc-blender`)

Trạng thái: **draft** · Kế thừa: không · Engine: **Blender** (render trên máy của chủ lab) · Bảng màu chữ/triện:
`styles/thuy-mac` · Dữ liệu máy đọc: `style.yaml` · Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style cho tập **`method: blender`** cần hình chân thực (núi đá, nước, sinh vật có lông, vảy, lông vũ). Blender render
bằng Cycles với look `realistic`: trời là ảnh HDRI (`world.hdri`) hoặc trời vật lý, một đèn mặt trời theo `world.sun`,
vật liệu PBR. Model mang vật liệu riêng (GLB quét 3D, file `.blend` có hair curves và geometry nodes) được giữ nguyên;
preset thủ tục (`mountains`, `rocks`, `ground`, `water`) nhận bộ texture PBR theo vai trò qua khóa `materials`. Asset
CC0 (HDRI, texture, model quét) để trong `out/<project>/assets/` (git và Drive bỏ qua), ghi nguồn và giấy phép trong
`ASSETS.md` của tập. Không gọi model tạo ảnh nào; render miễn phí, chỉ tốn thời gian GPU. Cử động khó dùng clip local
(`video_engine: comfy`, MiniMax H3 nối hai khung Blender). Hướng dẫn chung:
`.claude/skills/film-compose-shot/references/blender-method.md`.

## Tinh thần

Như phim tài liệu thiên nhiên quay ở nơi không ai đến được: ánh sáng thật theo giờ trong ngày, đá ướt, sương, nước
phản chiếu; sinh vật lạ nhưng có xương, da, lông đúng vật lý. Cái lạ đến từ hình dáng theo kinh văn, không từ hiệu ứng.

## Khi nào dùng

Tập cần hình gần phim người đóng/AAA mà không trả phí ảnh/video AI; tập có sinh vật cận cảnh (lông, lông vũ, vảy).

## Tránh

Vật liệu một màu không texture ở cận cảnh (trông như đất nặn); mặt người trên thú ở cận khi chưa qua turntable; trời
HDRI có nhà cửa/đường dây; nhiều nguồn sáng không có lý do.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `look` | `realistic` (Cycles, AgX Medium High Contrast, adaptive sampling 0,02, motion blur 0,5 khung) |
| `engine` | `cycles` (OptiX trên RTX); `eevee` chỉ để thử bố cục |
| `line` | `0` (không nét) |
| `mist` | `0`: sương bằng `mist-bands` khi dựng hoặc volume trong cảnh |
| `palette` | màu chữ và triện (lấy từ `thuy-mac`) |

Đo 2026-11-26 (RTX 5070 Ti, Blender 5.3): một khung 1920×1080, 256 sample adaptive, núi + nước + đá quét + thông
`.blend` + HDRI ≈ 15 s/khung.

## Duyệt

Turntable model (`blender.py turntable`) và một shot mẫu (`blender.py render ... --preview`) ở G2. Chuyển
`status: stable` khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
