# Pixel 16-bit (`pixel-16bit`)

Trạng thái: **draft** · Phong cách số 5 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:pixel-rpg`
(`$CINECODE/styles/pixel-rpg.md`) · Engine: **2D + hậu kỳ pixel** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Khung 320×180 phóng nguyên khối lên 1080p, bảng màu index 16 màu, dither Bayer, hình chạy bước đôi như sprite máy chơi game giữa thập niên 90.

## Khi nào dùng

Trailer game, recap, nội dung hoài cổ, đoạn "menu" vui trong một tập.

## Tránh

Scanline/CRT (đó là ASCII/CRT, không phải pixel); nửa pixel; zoom làm đổi cỡ khối.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"canvas2d"` |
| `look` | `"flat-toon"` |
| `post` | `[{"id": "pixel-16", "rows": 180, "dither": 0.6}]` |
| `hold` | `2` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:pixel-rpg` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
