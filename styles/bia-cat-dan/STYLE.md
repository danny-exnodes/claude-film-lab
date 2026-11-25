# Bìa cắt dán (`bia-cat-dan`)

Trạng thái: **draft** · Phong cách số 9 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:paper-popup`
(`$CINECODE/styles/paper-popup.md`) · Engine: **3D (three.js, tấm phẳng)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Nhân vật là các mảnh bìa phẳng có độ dày, mép cắt nâu xám, ghim đồng ở khớp; cảnh là các tấm bìa xếp lớp trong một hộp sân khấu nông, một đèn bàn ấm đổ bóng thật lên tấm phía sau. Chuyển động stop-motion 12 hình/giây, rung nhẹ.

## Khi nào dùng

Truyện cổ, phim thiếu nhi, kể chuyện tự làm (DIY), quảng cáo thủ công.

## Tránh

Mảnh xoay ra khỏi mặt phẳng (lộ là 3D giả); bóng quá cứng; chuyển động mượt 24 hình.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"three"` |
| `look` | `"cardboard"` |
| `post` | `[]` |
| `hold` | `2` |
| `camera` | `{"pos": [0, 0.8, 4.4], "target": [0, 0.6, 0], "fov": 32, "move": {"t": [0, 4.5], "pos": [0.2, 0.78, 4.0], "target": [0.1, 0.6, 0]}}` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:paper-popup` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
