# Nhân vật cử động trong phương pháp `layers` (không dùng Seedance)

Dành cho compositor và họa sĩ (art director). Áp dụng khi `EPISODE.md` ghi `method: layers`: mọi cử động của nhân vật
do code làm trên các lớp tranh, **không gọi Seedance**. Hai rig: `cloth` (`tools/compose/cloth.js`) và `pose-cycle`
(`tools/compose/pose.js`); id trong `shots.csv` cột `code_motion`: `cloth`, `pose-cycle`.

Bài học tập 1 (cổng G3): người duyệt loại mọi con vật/nhân vật **trượt hoặc xoay như hình cắt giấy** và mọi bộ phận
**trôi rời một mình**. Vì vậy trong `layers`:
- Nhân vật **giữ nguyên tư thế**. Sự sống nằm ở áo choàng, tay áo, tóc, đuôi biến dạng tại chỗ; ở khí quyển (sương, khói,
  lửa, tàn lửa); ở máy quay.
- Hành động lớn (quay đầu, giơ tay, bước đi) = **đổi bậc giữa 2–4 tranh tư thế** (limited animation, 8–12 fps), không nội
  suy vị trí hay góc xoay của cả thân.

## 1. Chọn rig nào

| Cần gì | Rig | Vì sao |
|---|---|---|
| Áo choàng, tay áo, dải lụa, vạt áo, mảng tóc bay trong gió | `cloth` | sóng chạy từ mép dính vào thân ra mép tự do, 3 sóng có nhiễu + gió chung cho cả shot; mép dính không bao giờ rời thân |
| Đuôi, một lọn tóc, một sợi dây đung đưa đều, chậm | `strip-warp` | một sóng sin + lắc chậm; rẻ, đủ cho vật mảnh, không cần gió chung |
| Quay đầu, giơ tay, cúi, bước đi, đổi dáng đứng | `pose-cycle` | đổi hẳn sang tranh tư thế khác theo lưới 8–12 fps |
| Ngực phập phồng, chớp mắt | `breath`, `eyelid` | như cũ (`compose-api.md` §4) |
| Cả hình trôi rất chậm trong khung | máy quay (`COMPOSE.camera`: `zoom`, `pan`) | rig nhân vật **không** có tween vị trí/góc xoay, có chủ ý |

Dùng chung được: một tranh tư thế có thể mang `cloth` + `breath` + `eyes` của riêng nó. Không đặt hộp `cloth` và hộp
`warp` chồng lên nhau trên cùng một tranh.

## 2. `cloth`: vải bay tại chỗ

```js
const PLATES = {
  L4: { src: '../../plates/matte/<tập>_s03_L4_dao-si_v02.png', depth: COMPOSE.DEPTH.char,
        place: { x: 1180, y: 960, h: 620, pivot: 'feet' },
        rig: { cloth: [ { box: 'cloak', root: 'top' },                       // áo choàng: dính ở vai, bay ở gấu
                        { box: 'sleeve', root: 'right', amp: 0.05 },         // tay áo: dính ở khuỷu (mép phải hộp)
                        { box: 'hair', root: 'hair_root', tip: 'hair_tip', wavelength: 0.6, speed: 0.9 } ],
               breath: { pivot: 'feet' } } },
};
function s03(g, k, t, S) {
  COMPOSE.stage(g, S, COMPOSE.camera(t, { from: 0, to: 8, zoom: [1, 1.06] }), (st) => {
    st.wind = { dir: 'left', strength: 0.5, gust: 0.6 };     // một lần cho cả shot: mọi hộp vải chung một cơn gió
    st.plate('L1'); st.plate('L4');
  });
}
```

| Tham số | Mặc định | Ghi chú |
|---|---|---|
| `box` | — | tên hộp trong `anchors.json` (`<tên>_tl` / `<tên>_br`) hoặc `[x0, y0, x1, y1]` (px của tranh) |
| `root` | điểm `<hộp>_root`, không có thì `'top'` | mép dính vào thân: `'top' \| 'left' \| 'right' \| 'bottom'`, hoặc tên một điểm neo (kèm `tip` để biết hướng; chỉ phần hộp từ gốc về phía ngọn là vải) |
| `amp` | `0.04` | độ lệch ở mép tự do = 4 % chiều dài vùng; **trần cứng 10 %** (lớn hơn → cảnh báo, dùng 0.10) |
| `wavelength` | `0.9` | bước sóng theo chiều dài vùng; nhỏ hơn = nhiều nếp hơn (tóc 0.5–0.7, áo choàng 0.8–1.2) |
| `speed` | `0.6` | chu kỳ/giây; gió nhẹ 0.3–0.5, gió mạnh 0.8–1.2 |
| `gain` | `1.5` | số mũ của đường bao: lớn hơn = gần thân đứng yên hơn, chỉ gấu áo bay |
| `feather` | `0.06` | phần chiều dài mà thân mờ dần dưới vải ở chỗ nối (không lộ vết cắt) |
| `strip` | `3` | bề dày dải, px sân khấu, tối đa 4 |
| `wind` | `{ dir: 0, strength: 0.5, gust: 0.5 }` | `dir`: độ trên mặt tranh (0 thổi sang phải, 90 xuống, 180 sang trái, 270 lên) hoặc `'right' \| 'down' \| 'left' \| 'up'`; `strength` 0–1; `gust` 0 (đều) – 1 (toàn cơn giật) |
| `salt` | theo thứ tự hộp | pha riêng của từng hộp; các hộp luôn lệch pha nhau |

- Gió: đặt `st.wind = {...}` một lần trong shot (hoặc `st.plate(id, { wind })`). Cơn giật là nhiễu chậm **chung** cho mọi
  hộp: áo choàng và tay áo cùng nghiêng, cùng căng một lúc, nhưng nếp gợn lệch pha. Hướng gió phải khớp với khói, tàn lửa,
  sương của shot. Thứ tự ưu tiên: `wind` khai trong rig của hộp < gió của shot (`st.wind`, rồi `st.plate(id, { wind })`)
  < `wind` của riêng một hộp trong shot đó (`{ cloth: { cloak: { wind: { strength: 0.2 } } } }`).
- Theo shot: `st.plate('L4', { cloth: false })` giữ yên mọi hộp; `{ cloth: { cloak: { amp: 0.06 }, sleeve: false } }`.
- Vẽ hộp: hộp chỉ chứa phần vải được bay **và khoảng trong suốt quanh nó** (ít nhất 10 % chiều dài mỗi bên theo hướng
  lệch); phần lệch ra ngoài hộp bị cắt, điểm ảnh ngoài hộp không bao giờ đổi. Mép `root` của hộp đặt **trên phần vải
  còn dính thân** (đường vai, khuỷu tay, chân tóc), không đặt giữa khoảng trống.
- Hộp không được chứa tay, mặt, vũ khí: mọi thứ trong hộp đều bị uốn theo. Hai hộp `cloth` của một tranh không chồng lên
  nhau (điểm ảnh chung chỉ thuộc hộp khai trước).
- Vùng vải nên **đặc** (tách nền kiểu thân đặc, như `rembg` của L4): ở `feather` đầu tiên thân và vải đè lên nhau, nên vải
  bán trong suốt (lụa mỏng, mực loang tách bằng luminance) sẽ đậm hơn một chút ở đoạn sát mép `root`.
- Tham số không phải số (hoặc `gain` ≤ 0) không làm hỏng khung hình: giá trị mặc định được dùng, `gain` tối thiểu 0.1.
- Cảnh báo (`compose:` trong `qc` của `make.py`): `cloth <tên> has no anchor box; held still`, `box is too small`,
  `amp ... is over the cap`, `has no anchor point for its root or tip; held still`.
- Thứ tự file trong bộ mã: `cloth.js` và `pose.js` đứng sau `stage.js`, `strip-warp.js`, `eyelid.js`.

## 3. `pose-cycle`: đổi tư thế theo bậc

```js
const PLATES = {
  L4:      { src: '../../plates/matte/<tập>_s05_L4_dao-si-dung_v01.png', depth: COMPOSE.DEPTH.char,
             place: { x: 1180, y: 960, h: 620, pivot: 'feet' },                       // chỉ tranh chủ có place
             rig: { cloth: [{ box: 'cloak' }],
                    poses: { frames: ['L4', 'L4_tay1', 'L4_tay2'], fps: 8,
                             ...COMPOSE.pose.once([0, 1, 2], { at: 3.5, hold: 2.5, back: true }) } } },
  L4_tay1: { src: '../../plates/matte/<tập>_s05_L4_dao-si-gio-tay-1_v01.png', rig: { cloth: [{ box: 'cloak' }] } },
  L4_tay2: { src: '../../plates/matte/<tập>_s05_L4_dao-si-gio-tay-2_v01.png', rig: { cloth: [{ box: 'cloak' }] } },
};
// trong shot chỉ gọi tranh chủ: st.plate('L4')
```

- `frames`: id các tranh tư thế trong `PLATES`; khung 0 là tư thế nghỉ (có thể là chính tranh chủ). Tranh tư thế **không
  cần `place`**: rig đặt điểm `align` (mặc định `feet`) của nó trùng điểm `feet` của tranh chủ và co giãn theo tranh chủ
  (theo chiều cao tranh; hoặc `span: 'head'` → theo khoảng cách `feet`–`head`, dùng khi các tranh bị cắt khung khác nhau).
- `timeline: [{ at: <giây>, frame: <chỉ số> | 'hold' }]`; thời gian được lượng tử hoá trước (`floor(t * fps) / fps`), khung
  là mục có `at` muộn nhất mà ≤ thời điểm đó (không cần xếp sẵn theo `at`; `'hold'` không đổi khung); trước mục đầu là khung 0; sau mục cuối giữ nguyên khung cuối. `loop: <giây>`
  lặp lại timeline. `start: <giây>` dời gốc thời gian (theo shot: `st.plate('L4', { poses: { start: 41.5 } })`).
- `fps`: 8–12 (mặc định 8; ngoài khoảng → cảnh báo và bị kẹp). `blend`: 0 = đổi cứng (mặc định, đúng chất limited
  animation); 1–2 = hoà tan ngắn tính bằng khung của lưới fps (tối đa 2).
- Mỗi tranh tư thế mang rig riêng (`cloth`, `breath`, `eyes`): khai hộp neo cho **từng** tranh. Theo shot:
  `st.plate('L4', { poses: false })` vẽ tranh chủ như một lớp thường.
- Thiếu tranh, thiếu điểm neo → cảnh báo `compose: plate L4: poses: frame 2: ...; frame 0 is shown` và khung đó hiện khung 0
  (không bao giờ nhảy vị trí).

Hàm dựng timeline (thời gian luôn rơi đúng lưới fps):

| Hàm | Dùng cho | Trả về |
|---|---|---|
| `COMPOSE.pose.walk([0, 1, 2, 3], { step: 0.25 })` | bước đi tại chỗ, lặp vô hạn | `{ timeline, loop }` |
| `COMPOSE.pose.once([0, 1], { at: 4, hold: 2, back: true })` | quay đầu, giơ tay rồi (tuỳ chọn) trở về | `{ timeline, end }` |
| `COMPOSE.pose.sequence([[0, 1.5], [1, 0.25], [2, 2]], { at: 0, repeat: 1 })` | chuỗi tuỳ ý `[khung, giây giữ]` | `{ timeline, end }` |

### Một hành động cần bao nhiêu tranh tư thế

| Hành động | Số tranh | Nhịp gợi ý (8 fps) |
|---|---|---|
| Đứng → quay đầu / ngẩng nhìn | 2 | đổi cứng một lần; giữ tư thế mới ≥ 1.5 s |
| Giơ tay, chỉ tay, vung phất trần | 2–3 | khung giữa 1–2 khung lưới (0.125–0.25 s); tư thế cuối giữ 2–3 s; về lại cũng qua khung giữa |
| Cúi lạy, ngồi xuống, đứng lên | 3 | mỗi khung giữa 0.25 s; đầu và cuối giữ ≥ 2 s |
| Đi xa dần, nhìn từ sau lưng (vòng lặp) | 3–4 | mỗi khung 0.25 s (2 khung lưới) → một vòng 0.75–1 s; cảm giác tiến lên do **máy quay** tiến/`pan` và parallax, nhân vật bước tại chỗ |
| Thú quay đầu, vẫy tai | 2 | như quay đầu |

Số đo:
- `fps` 8 cho nhân vật người, thú lớn, nhịp trầm; 12 cho cử động nhanh (vung tay, chạy). Không dưới 8, không trên 12.
- Khung giữa (in-between) 1–2 khung lưới: 0.125–0.25 s ở 8 fps. Tư thế chính giữ **≥ 1 s** (thường 1.5–3 s); đổi tư thế
  dày hơn 1 lần/giây ngoài vòng bước đi sẽ thành giật.
- Vòng bước: 0.2–0.3 s mỗi khung; chậm hơn 0.35 s trông như trượt băng.
- Mỗi shot tối đa một hành động lớn; phần còn lại của shot là vải, khí quyển, máy quay.
- Rig khác trên tranh tư thế nên chạy cùng lưới: `st.plate('L4', { t: Math.floor(t * 8) / 8 })` nếu muốn cả vải cũng bước
  8 fps (chất hoạt hình vẽ tay); để mặc định thì vải mượt 24 fps trên thân đổi bậc.

## 4. Tạo tranh tư thế sao cho khớp nhau (họa sĩ)

Mọi tranh tư thế của một hành động phải chồng khít lên nhau, nếu không nhân vật sẽ nhảy khi đổi khung:
1. **Cùng kích thước canvas** (cùng `--size`, cùng tỉ lệ), nhân vật cùng cỡ trong khung.
2. **Cùng điểm `feet`**: bàn chân trụ (hoặc gốc thân với thú) ở cùng một chỗ. Prompt ghi rõ "same position, same
   scale, feet on the same spot, only <phần đổi> changes". Sau khi tách nền, đánh dấu `feet` (và `head` nếu dùng `span`)
   cho **từng** tranh bằng `tools/layers/anchors.py set` → rig căn theo điểm neo nên lệch vài px giữa các tranh vẫn khớp.
3. **Cùng ảnh khoá làm `--ref`**: mọi tranh tư thế đều tham chiếu ảnh khoá nhân vật đã duyệt (và tranh tư thế nghỉ), không
   tham chiếu dây chuyền tranh này sang tranh kia (sai lệch cộng dồn).
4. **Nền phẳng một màu** theo quyết định nền L4 của style pack (`matte.paper_bg` với `rembg`/luminance như `thuy-mac`,
   `matte.key_bg` khi lớp dùng `chroma`), không bóng đổ, không sàn → tách nền cùng một phương pháp, cùng tham số cho cả bộ.
5. Chỉ đổi đúng phần phải đổi (đầu, cánh tay, chân bước); trang phục, nét viền, bảng màu, hướng sáng giữ nguyên. Áo choàng
   và tóc vẽ ở dáng trung tính trong mọi tranh: phần bay do `cloth` làm.
6. Tạo cả bộ trong **một lô** (`python3 tools/ark.py image-batch <jobs.csv>`, có `--budget` và `--ledger`), xem cạnh nhau
   trước khi tách nền; tranh lệch cỡ hoặc lệch nét thì làm lại tranh đó, không sửa bằng code.
7. Đặt tên theo `docs/CONVENTIONS.md` §2, mỗi tư thế một tên chủ thể: `..._L4_<nhan-vat>-dung_v01.png`,
   `..._L4_<nhan-vat>-gio-tay-1_v01.png`.

Kiểm trước khi dựng: mở các tranh đã tách nền chồng lên nhau ở 50 % (hoặc `make.py stills` tại các mốc `at` của
timeline): chân trụ không xê dịch, đầu–vai cùng cỡ, viền không dày mỏng khác nhau.

## 5. Không bao giờ làm

- **Không trượt** nhân vật trên nền (`dx`/`dy` theo thời gian, tween `place`) để giả bước đi. Muốn đi: `pose-cycle` bước
  tại chỗ + máy quay.
- **Không xoay** cả thân hay một bộ phận quanh khớp (kiểu rối cắt giấy), không `rotate` lớp nhân vật.
- **Không cho một bộ phận hiện một mình** (cánh tay, đầu, đuôi là lớp rời trôi trên thân). Bộ phận chỉ cử động bằng biến
  dạng tại chỗ trong tranh (`cloth`, `strip-warp`) hoặc bằng đổi cả tranh tư thế.
- Không tween giữa hai tư thế dài hơn 2 khung lưới (`blend` > 2 bị kẹp): hoà tan dài thành bóng ma.
- Không kéo `amp` của `cloth` lên để "cho rõ": quá 10 % là vải rách khỏi dáng vẽ; muốn mạnh hơn thì tăng gió
  (`strength`, `gust`) và thêm khói, tàn lửa bay cùng hướng.
- Không gọi `tools/ark.py video` trong tập `method: layers`.
