# Bóng mực (`bong-muc`)

Trạng thái: **draft** · Phong cách số 6 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:shadow-puppet`
(`$CINECODE/styles/shadow-puppet.md`) · Engine: **2D (canvas)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Mọi hình ở tiền cảnh là một mảng mực đặc trước bầu trời hoàng hôn; các lớp núi nhạt dần theo khoảng cách; một viền sáng mảnh phía mặt trời. Câu chuyện kể bằng dáng: tư thế phải đọc được chỉ từ đường viền.

## Khi nào dùng

Cảnh mở/kết giàu cảm xúc, truyền thuyết, cảnh rộng có nhân vật nhỏ; dùng làm cảnh rộng cho tập thủy mặc (#32).

## Tránh

Máy quay cao (nhân vật chìm vào đất đen); tay chân che thân (mất dáng); chi tiết mặt (không thấy được).

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"canvas2d"` |
| `look` | `"ink-silhouette"` |
| `post` | `[]` |
| `hold` | `1` |
| `opts` | `{"rim": true}` |
| `camera` | `{"pos": [0, 0.12, 4.6], "target": [0, 1.05, 0], "fov": 36, "move": {"t": [0, 4.5], "pos": [0.3, 0.12, 4.2], "target": [0.15, 1.02, 0]}}` |
| `env` | `{"trees": 7, "rocks": 3, "clear": 1.8}` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:shadow-puppet` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
