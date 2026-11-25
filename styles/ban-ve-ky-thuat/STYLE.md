# Bản vẽ kỹ thuật (`ban-ve-ky-thuat`)

Trạng thái: **draft** · Phong cách số 3 của bộ 10 phong cách vẽ bằng code (#38) · Kế thừa: `cinecode:blueprint`
(`$CINECODE/styles/blueprint.md`) · Engine: **2D (canvas, chỉ nét)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Nét trắng trên giấy xanh Phổ, lưới mờ, đường tâm gạch-chấm, đường kích thước có mũi tên và số đo; mọi nét **vẽ dần theo thứ tự** như người kỹ sư đang dựng hình. Không tô khối, không ánh sáng 3D.

## Khi nào dùng

Giới thiệu cấu tạo, sản phẩm, quá trình; mở đầu một tập (nhân vật "được thiết kế" rồi mới sống).

## Tránh

Tô màu, bóng đổ, phối cảnh 3D có ánh sáng; chữ trang trí; vẽ hiện cùng lúc (mất thứ tự nét).

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"canvas2d"` |
| `look` | `"blueprint"` |
| `post` | `[]` |
| `hold` | `1` |
| `opts` | `{"reveal": [0, 2.4], "sheet": "ELEVATION", "title": "AI FILM LAB · TOON"}` |

`hold`: 1 = 24 hình/giây, 2 = bước đôi (12), 3 = stop-motion (8). Máy quay, chữ và âm thanh luôn 24 hình/giây.
Màu trong `render.palette` ghi đè màu mặc định của look (tên khóa: chú thích đầu look trong `tools/toon/look2d.js` /
`look3d.js`); `palette` ở gốc là bảng màu để duyệt. Nhân vật giữ bảng màu riêng trong `character.json`.

## Quan hệ với recipe cinecode

Recipe `cinecode:blueprint` mô tả chất liệu và ngữ pháp đầy đủ của phong cách; pack này là bản **dựng sẵn bằng bộ TOON** để
một tập dùng ngay, với cùng một rig nhân vật cho mọi phong cách. Khi cần sâu hơn (chữ, chuyển cảnh, âm thanh), đọc recipe
và thêm vào FILM section của shot; không sửa skill cinecode.

## Duyệt

Xem lookbook (`python3 tools/toon/toon.py lookbook`) và một clip của style với linh vật `giot`. Chuyển `status: stable`
khi có tập đầu tiên qua G2 bằng style này (ghi vào `examples.md`).
