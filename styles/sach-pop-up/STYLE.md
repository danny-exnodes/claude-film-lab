# Sách pop-up giấy (`sach-pop-up`)

Trạng thái: **draft** · Phong cách số 11 của bộ vẽ bằng code (#38, thêm sau nghiên cứu Papertrails) · Kế thừa: `cinecode:paper-popup`
(`$CINECODE/styles/paper-popup.md`) · Engine: **3D (three.js, bìa in hoạ tiết)** · Dữ liệu máy đọc: `style.yaml`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

Style này dùng cho tập **`method: code`**: nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không gọi model
tạo ảnh hay video, ngân sách 0 ảnh / 0 giây. Hướng dẫn chung: `.claude/skills/film-compose-shot/references/code-method.md`.

## Tinh thần

Một cuốn sách pop-up mở trên bàn tối, nhìn từ trên cao qua ống kính dài như chụp mô hình thu nhỏ: trang giấy in nền cỏ màu xô thơm và con đường giấy kraft mép xé; cây là hai tấm bìa cài chéo, bụi cây là dải bìa gợn sóng, mỗi tấm in hoạ tiết lá, hoa và có viền kem của mép cắt; tấm bìa **bật dậy từ trang** có vượt đà rồi rung nhẹ, đung đưa trong gió; ánh nắng ấm từ trên trái đổ bóng mềm, phía trước và phía sau mờ kiểu tilt-shift. Ban đêm (`opts.night`): ánh trăng xanh tối, đèn lồng ấm quanh nhân vật.

## Khi nào dùng

Phim thiếu nhi, truyện cổ, hành trình (nhân vật đi qua thế giới), mở/kết tập, quảng cáo ấm áp.

## Tránh

Cây đứng giữa máy quay và nhân vật (look tự chừa dải trước đường đi); máy quay thấp ngang tầm (mất cảm giác mô hình); bìa uốn cong hay co giãn (bìa chỉ gập quanh bản lề).

## Thông số render (`style.yaml: render`)

| Khóa | Giá trị |
|---|---|
| `engine` | `"three"` |
| `look` | `"popup-paper"` |
| `post` | `[]` |
| `hold` | `1` |
| `opts` | `{"rise": {"at": 0, "dur": 1, "spread": 0.12}, "tiltShift": 1}` |
| `camera` | `{"pos": [0, 5.0, 5.2], "target": [0, 0.3, -0.6], "fov": 26, "follow": 1, "move": {"t": [0, 4.5], "pos": [0, 4.5, 4.6], "target": [0, 0.32, -0.5]}}` |
| `env` | `{"density": 1.7}` |

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

## Nghiên cứu nguồn (2026-11-24)

Người dùng gọi tên "Loc Studio Papertrails". Không tìm thấy studio nào tên Loc Studio làm phong cách này (The Loc
Studios ở London là xưởng VFX). Nguồn khớp là **Papertrails** của Shikhar (@xikhar, 11/2026): "một thế giới giấy pop-up
vô tận" chạy trong trình duyệt bằng three.js, mã nguồn `github.com/xikhar/papertrails`, giấy phép MIT. Pack này chỉ học
**kỹ thuật**; không chép mã, mô hình (`tiles.glb`, `traveller.glb`), atlas tranh hay bố cục của họ. Hoạ tiết trên bìa ở
đây vẽ bằng code (`tools/toon/look3d.js`, `printCard`).

Kỹ thuật quan sát được và cách pack này làm:

| Papertrails | Pack này |
|---|---|
| Thế giới là một cuốn sách mở trên bàn gỗ tối; trang in nền, đường kraft, cỏ; ô đất "in mực" trước khi bật dậy | Trang in nền xô thơm + đường kraft mép xé + vệt cỏ (canvas), khối giấy dưới trang, bàn tối |
| Bìa cắt theo đường viền tranh, dày ~0.016, mép cắt màu kem đều ("gold pass") | `ExtrudeGeometry` dày 0.014, mặt in hoạ tiết, mép là vật liệu kem; viền kem in thêm dọc mép |
| Cây = hai tấm bìa cài chéo; bụi = dải bìa | Cây tròn / thông = hai tấm chéo 90°; bụi = dải gợn in hoa |
| Bìa bật dậy bằng lò xo bản lề: vượt 8–15 %, rung 4–7 Hz vài nhịp, lá rơi có nảy nhẹ | `p = 1 − e^(−6τ)·cos(11τ)` (vượt ~15 %), lan theo khoảng cách (`opts.rise`) |
| Gió: dải gió chạy ngang trang, bìa lắc quanh bản lề, hàm thuần của (t, vị trí) | Lắc ±0.025 rad quanh bản lề, pha theo x |
| Vật liệu Lambert mờ, sợi giấy, bóng mềm PCSS, ánh ấm rò vào bóng, bìa mỏng sáng khi ngược sáng | Lambert + texture sợi, bóng PCF mềm, đèn chính ấm trên trái + đèn phụ lạnh |
| Hậu kỳ: tilt-shift (CoC theo khoảng cách dòng lấy nét), bokeh, AO, bloom, vignette, grade ấm, hạt | Hai lớp mờ trên/dưới dải nét (canvas), grade ấm `soft-light`, vignette tối ấm |
| Máy quay ống dài (~27°), nhìn xuống ~53°, theo nhân vật có vùng tĩnh, nhìn trước hướng đi | `fov 26`, cao 5, `follow: 1`, đẩy nhẹ |
| Nhân vật là con rối giấy phẳng, chân tay xoay quanh chốt, nhún mỗi bước, đèn lồng như con lắc | Rig TOON chiếu lên mặt phẳng, đùn thành bìa, quay về phía máy quay |
| Ngày/đêm: đêm xanh navy, trăng làm đèn chính, ấm chỉ ở đèn lồng, cửa sổ sáng | `opts.night`: hemisphere navy, trăng xanh yếu, đèn lồng điểm ấm theo nhân vật |

Chưa làm (so với tham chiếu): nhà, hàng rào, tổ ong, cầu, sông in trên trang có nước chạy, động vật giấy, lá rơi,
bokeh thật theo độ sâu, AO, cửa sổ sáng ban đêm. Muốn chi tiết tranh in phong phú như tham chiếu thì có thể tạo atlas hoạ
tiết bằng Seedream (có phí) cho mặt bìa — khi đó tập không còn là `method: code` thuần.
