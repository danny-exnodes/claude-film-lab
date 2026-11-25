# Tay ống cao su (`ong-cao-su`)

Trạng thái: **draft** · Phong cách số 7 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:rubber-hose`
(`$CINECODE/styles/rubber-hose.md`) · Engine: **2D (canvas)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Hoạt hình đen trắng thập niên 1930: tay chân là ống cong không khớp, găng trắng, mắt khoét hình bánh, mọi vật nhún theo nhịp nhạc jazz; giấy sepia, hạt phim, rung khung, vết xước.

## Khi nào dùng

Quảng cáo hoài cổ, đồ ăn thức uống, phim vui thiếu nhi, đoạn nhạc.

## Tránh

Khớp khuỷu/gối gãy góc; màu (trừ khi chủ ý); nhún lệch nhịp nhạc.

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"canvas2d"` |
| `look` | `"rubber-hose"` |
| `post` | `[]` |
| `hold` | `2` |
| `opts` | `{"bpm": 120}` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:rubber-hose` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
