# <Tên trường phái> (`<id>`)

Trạng thái: **draft** · Phong cách số 2 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:midcentury-toon`
(`$CINECODE/styles/midcentury-toon.md`) · Engine: **2D (canvas)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Mảng màu phẳng, một bậc bóng cho mỗi màu, nền hình học (đồi, cây tròn, mặt trời đĩa), màu tươi sạch. Đọc rõ ở mọi cỡ màn hình; hợp video giải thích.

## Khi nào dùng

Giải thích kiến thức, intro/outro kênh, short dọc, phim ngắn vui.

## Tránh

Gradient phức tạp trên nhân vật; quá nhiều chi tiết nền; viền không đều.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"canvas2d"` |
| `look` | `"flat-toon"` |
| `post` | `[]` |
| `hold` | `1` |
| `opts` | `{"outline": 0}` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:midcentury-toon` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
