# Đất nặn 3D (`dat-nan-3d`)

Trạng thái: **draft** · Phong cách số 1 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:claymation`
(`$CINECODE/styles/claymation.md`) · Engine: **3D (three.js)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Nhân vật và cảnh như nặn bằng đất sét mềm, quay stop-motion trên bàn: khối tròn, bề mặt mờ có dấu ngón tay, bóng đổ mềm, ánh sáng studio ấm. Mỗi giây 12 hình (bước đôi) và bề mặt "sôi" nhẹ giữa các hình như được nặn lại.

## Khi nào dùng

Phim thiếu nhi, quảng cáo thân thiện, linh vật, cảnh ấm áp trong nhà hoặc ngoài đồi.

## Tránh

Bề mặt bóng như nhựa; chuyển động mượt 24 hình (mất chất stop-motion); màu bão hoà gắt.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"three"` |
| `look` | `"clay-3d"` |
| `post` | `[]` |
| `hold` | `2` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:claymation` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
