# In riso (`in-riso`)

Trạng thái: **draft** · Phong cách số 4 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:risograph`
(`$CINECODE/styles/risograph.md`) · Engine: **2D + hậu kỳ riso** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Phim như in từng khung trên máy riso: 2–3 mực spot trong suốt chồng nhau (xanh, hồng huỳnh quang, vàng) trên giấy ngà, chấm halftone, bản in lệch nhau vài pixel và đổi mỗi hình, mực không đều.

## Khi nào dùng

Thương hiệu indie, zine, nội dung phong cách sống, poster động.

## Tránh

Quá nhiều màu nguồn (mọi thứ phải tách được về 2–3 mực); halftone quá mịn ở 1080p (cell < 5 px).

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"canvas2d"` |
| `look` | `"flat-toon"` |
| `post` | `[{"id": "riso", "paper": "#F4EEDF", "inks": ["#0078BF", "#FF48B0", "#FFE800"], "cell": 7, "misreg": 2.5}]` |
| `hold` | `2` |
| `palette` | `{"sky": "#F4EEDF", "sky2": "#F4EEDF", "sun": "#FFE800", "hill": "#9CC3E6", "hill2": "#F7A8D3", "ground": "#FFF2B3", "ground2": "#FFE98A", "tree": "#5A9FD6", "tree2": "#3C7DB8", "trunk": "#E2589F", "rock": "#F2A2CB", "rock2": "#E07DB2", "cloud": "#F4EEDF", "shadow": "rgba(0,120,191,0.25)"}` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:risograph` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
