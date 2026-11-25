# Hoạt hình 3D Blender (`toon-3d-blender`)

Trạng thái: **draft** · Engine: **Blender** (render trên máy của chủ lab) · Dữ liệu máy đọc: `style.yaml` ·
Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: blender`** cần chất hoạt hình 3D: model tô toon (hai ba dải sáng tối gắt), viền Line
Art đen, màu phẳng tươi, nền sạch. Linh vật `giot` có sẵn dạng preset 3D. Không gọi model tạo ảnh nào; render miễn phí.
Hướng dẫn chung: `.claude/skills/film-compose-shot/references/blender-method.md`.

## Tinh thần

Đồ chơi gọn gàng dưới nắng trưa: khối tròn, ít chi tiết, bóng đổ rõ, viền đều. Chuyển động máy quay êm (`ease: inout`).

## Khi nào dùng

Phim thiếu nhi, giải thích kiến thức, intro kênh, khi cần model 3D có sẵn (GLB) hoặc bố cục nhất quán mà style vẽ bằng
code (`dat-nan-3d`, `low-poly-90`) không đủ.

## Tránh

Vật liệu bóng kiểu ảnh chụp; viền quá mảnh ở cảnh rộng; quá năm màu chính trong một khung.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `look` | `toon-ink` |
| `engine` | `eevee` (toon ramp chỉ có trong EEVEE; Cycles cho ra khối phẳng) |
| `line` | độ dày viền ở 1080p |
| `mist` | sương rất nhẹ cho chiều sâu |
| `palette` | màu giấy, trời, cỏ, mực viền |

## Duyệt

Turntable model (`blender.py turntable`) và một shot mẫu (`blender.py render ... --preview`) ở G2. Chuyển
`status: stable` khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
