# Thủy mặc Blender (`thuy-mac-blender`)

Trạng thái: **draft** · Kế thừa: `cinecode:ink-wash` · Engine: **Blender** (render trên máy của chủ lab) · Bảng màu:
`styles/thuy-mac` · Dữ liệu máy đọc: `style.yaml` · Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: blender`**: núi, đá, cây, nước và dị thú là model 3D (preset thủ tục của
`tools/blender/` hoặc file GLB có giấy phép ghi trong `ASSETS.md`), Blender render từng khung theo `shots3d/s<NN>.json`
với look `ink-wash`. Không gọi model tạo ảnh nào; render miễn phí, chỉ tốn thời gian GPU. Cử động khó (con thú đi, quay
đầu) có thể thêm bằng clip local (`video_engine: comfy`, MiniMax H3 nối hai khung Blender). Hướng dẫn chung:
`.claude/skills/film-compose-shot/references/blender-method.md`.

## Tinh thần

Bản 3D của `thuy-mac`: giấy trắng ngà, khối được tô bằng vài bậc giá trị mực (đậm ở lưng, nhạt ở bụng), nét Line Art
mảnh dần theo khoảng cách, sương theo độ sâu làm ba tầng núi xa – giữa – gần nhạt dần (tam viễn). Nắng thấp, ấm (ochre)
từ bên phải; đúng một điểm son.

## Khi nào dùng

Cảnh cần máy quay 3D thật và bố cục nhất quán giữa các shot (cùng một ngọn núi nhìn từ nhiều góc), khi `thuy-mac-3d`
(vẽ bằng three.js trong trình duyệt) không đủ chi tiết hoặc cần model GLB có sẵn.

## Tránh

Ánh sáng đầy đủ kiểu ảnh chụp (mất chất mực); nhiều màu; sương dày che hết núi; máy quay nhìn ngang mặt đất.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `look` | `ink-wash` (look của Blender: `grey-layout`, `clay`, `toon-ink`, `ink-wash`) |
| `engine` | `eevee` (mặc định, cần GPU) hoặc `cycles` (dự phòng) |
| `line` | độ dày nét Line Art ở 1080p, `0` = không nét |
| `mist` | sương theo độ sâu, 0–1 |
| `palette` | màu giấy, mực, nắng cho look |

`shot3d.json` của mỗi shot ghi `look` và `engine` riêng; đạo diễn chép từ khối `render` này, không đổi giữa các shot.

## Quan hệ với `thuy-mac` và `thuy-mac-3d`

Cùng series, cùng bảng màu và âm thanh. Một tập một phương pháp (`EPISODE.md: method`): không trộn style ảnh, style vẽ
bằng code và style Blender trong một tập.

## Duyệt

Turntable model (`blender.py turntable`) và một shot mẫu (`blender.py render ... --preview`) ở G2. Chuyển
`status: stable` khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
