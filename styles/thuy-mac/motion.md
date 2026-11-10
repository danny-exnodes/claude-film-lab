# Chuyển động – Thủy mặc

Kế thừa `cinecode:ink-wash` §5 (chất chuyển động), §6 (ngữ pháp máy quay), §8 (thủ pháp riêng). File này chỉ ghi
lựa chọn của series và cách dùng bốn id trong `style.yaml: motion`. Tham số và API là của `tools/compose/`
(đọc chú thích đầu mỗi file); ở đây chỉ ghi **giá trị và cách dùng riêng của thủy mặc**.

## Nguyên tắc series

- Tranh AI là bất động; mọi thứ sống là code: sương, ánh sáng, tàn lửa, dao động nhỏ của bộ phận, máy quay.
- Nhịp theo recipe §5: máy quay, sương, ánh sáng mượt 24 fps; chuyển động của nhân vật nên bước đôi (12 fps).
  `tools/compose/` hiện chạy mượt mọi thứ – muốn bước đôi thì người dựng làm tròn thời gian của rig nhân vật
  (`t = floor(t*12)/12`) trong shot.
- Parallax: L1 chậm nhất, L3 nhanh nhất; gợi ý độ sâu L1 0.1–0.2 · L2 0.5 · L3 1.0 · L4 theo L3 (nhân vật đứng trên L3).
- Tranh AI không có thứ tự nét (khác recipe §5 "painted into existence"): hiện bằng loang mực (§8 ink bloom), sương
  tan (`mist.open`), hoặc quét ngưỡng độ đậm trên alpha luminance (vùng đậm hiện trước, 0,6–1,2 s).
- Lia ngang theo cuộn tranh: phải sang trái (§6 handscroll). L1 rộng hơn khung 25–33% để đủ chỗ lia.
- Màu của mọi texture code lấy từ `palette` của style: sương = `paper`, nắng và tàn lửa = `ochre`.

## Bốn id của style

| id (`style.yaml`) | File / API | Cách dùng trong thủy mặc | Thay cho | Liên hệ recipe |
|---|---|---|---|---|
| `mist-bands` | `mist.js`: `COMPOSE.mist.bands/band/open` | 2–3 dải sau chủ thể (một dải phủ chân L2 nơi đá tan vào giấy), tối đa một dải trước khi đẩy vào; tốc độ 10–35 px/s, các dải ngược chiều nhau; `mist.open` mở đầu shot đầu tiên. `spec.mist.color` = `paper` (`#EFE6D3`, không dùng mặc định `#f2ecde`). | sương vẽ sẵn (cấm trong prompt) | §2 mountains dissolve into mist bands; §6/§8 push into mist |
| `sun-glow` | `glow.js`: `COMPOSE.glow.sun` | Mặt trời thấp bên phải khung (theo `light`), độ sâu 0.1–0.15 cùng L1, màu `ochre`, cường độ ≤ 0.6 để không làm giấy cháy trắng. Không vẽ đĩa mặt trời vào L1. | đĩa mặt trời trong tranh | series thêm (recipe §3 không có màu ấm) |
| `embers` | `embers.js`: `COMPOSE.embers.draw` | Chỉ ở cảnh có lửa hoặc chiều tà; ít (≤ 40 hạt), màu `ochre`; một vài hạt `accent` là đủ (giữ quy tắc một màu son §3). | tàn lửa vẽ sẵn | series thêm |
| `strip-warp` | `strip-warp.js`: rig `warp` trên L4 | Đuôi, tai, lông, cỏ lay trong chính lớp L4; mỗi bộ phận một hộp trong `anchors.json` (gốc → ngọn). Biên độ nhỏ (ngọn lệch ≤ 2–3% chiều dài bộ phận). Đuôi nhiều nhánh (vd. chín đuôi) → mỗi nhánh một hộp, lệch pha (`salt`) để không lay đồng loạt. | clip AI cho chuyển động nhỏ | §5 (không "boil") |

Module khác trong `tools/compose/` dùng chung cho mọi style, không cần khai báo ở đây: `breath.js` (thở),
`eyelid.js` (mắt nhắm/mở bằng code từ hộp mắt trong `anchors.json`). Với thủy mặc, **thử `eyelid.js` trước** khi tạo
biến thể `prompts/edit-eyes-closed.txt` (biến thể đó cần model `pro` qua Lambda, tốn phí).

## Lựa chọn máy quay hay dùng trong series

Chọn từ bảng recipe §6, không thêm chuyển động mới:
- Mở tập: giấy trống rồi sương tan (`mist.open`), hoặc lia cuộn tranh qua dãy núi.
- Nhân vật lộ diện: khung tĩnh + đẩy vào rất chậm, im lặng, rồi một cắt cứng sang cận cảnh (lần cắt cứng duy nhất).
- Kết: trở lại khung mở đầu (§6 return to an earlier framing) hoặc một dấu nhỏ (§11 one small mark).

`shots.csv`: cột `camera` dùng tên chuẩn CONVENTIONS §6; cột `code_motion` ghi các id ở bảng trên (và `breath`,
`eyelid` khi dùng), cách nhau bởi `;`.
