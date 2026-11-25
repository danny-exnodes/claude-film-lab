# Hình người vẽ bằng code cho cảnh rộng (`figure`)

Đọc file này khi một shot **cảnh rộng** cần một người nhỏ: người đứng trên sống núi, đứng trước chiến trường, đi dọc
con đường, một nhóm người ở xa. `COMPOSE.figure.draw` vẽ người đó **hoàn toàn bằng nét mực code** (`tools/compose/ink.js`
+ `figure.js`): không mua ảnh nào, và có chuyển động thật (bước đi, quay người, giơ tay, áo và dải buộc tóc bay theo gió).
Chữ ký và bảng tham số đầy đủ: `compose-api.md` §5.4. Quy tắc chung của `layers`: `layers-method.md`.

Hình mặc định nhìn **từ sau lưng** (đúng quy tắc 5 của `layers-method.md`): một khối áo nhạt, hai nét mực đậm làm viền
áo, đai lưng, tay áo rộng, búi tóc và dải buộc tóc (hoặc nón lá), chân và bàn chân bằng mực cháy.

## 1. Khi nào dùng hình code, khi nào dùng plate AI

| Người trong khung cao | Dùng | Vì sao |
|---|---|---|
| ≤ 12 % khung (≤ 130 px sân khấu) | **hình code** | ở cỡ này chỉ đọc được dáng, tư thế, hướng nhìn và vạt áo bay; chi tiết của plate AI không ai thấy |
| 12–25 % khung (130–270 px) | hình code, nếu người đó **không phải** nhân vật đang được giới thiệu; nhân vật chính lần đầu xuất hiện thì plate AI | đọc được búi tóc/nón, tay áo, đai, bàn chân; chưa đọc được mặt và hoa văn |
| > 25 % khung | **plate AI** (`L4` + `cloth` / `pose-cycle`, `layers-character.md`) | hình code bị chặn ở 270 px: lớn hơn thì nét code lộ là nét code. `height` lớn hơn bị thu về 270 + cảnh báo |

Dùng hình code cho: người đứng xa nhìn cảnh, người đi qua khung, lính gác trên thành, đoàn người, đám đông sau lưng
nhân vật chính. **Không** dùng cho: cận cảnh, trung cảnh, mặt người, biểu cảm, bàn tay, trang phục có hoa văn riêng
của một nhân vật đã khóa, **dị thú và con vật** (chỉ có dáng người mặc áo dài). Những thứ đó vẫn là plate AI.

## 2. Đặt hình

```js
function s07(st) {
  st.wind = { dir: 'right', strength: 0.6, gust: 0.5 };            // một lần cho cả shot: sương, khói, vải, hình code
  st.plate('L1'); st.plate('L2'); st.plate('L3');
  COMPOSE.figure.draw(st, { on: { plate: 'L3', anchor: 'song_nui' }, height: 120, salt: 1 });
}
```

- **Chân**: `on: { plate, anchor }` đặt bàn chân lên một điểm neo của plate (`tools/layers/anchors.py set`, điểm nằm
  trên mặt đứng của L3) và lấy luôn độ sâu của plate đó, nên hình đi cùng nền khi máy quay di chuyển. Hoặc `x`, `y`
  (px sân khấu) + `depth`.
- **Cỡ**: `height` px sân khấu, tối đa 270. Người ở xa nhỏ hơn và đứng cao hơn trong khung.
- **Màu**: `palette: { ink: <mực của style>, accent: <son> }`. Mặc định hoà `'multiply'` (mực làm tối giấy bên dưới);
  trên nền tối dùng `blend: 'source-over'`. Dải buộc tóc màu son chỉ khi nó **là** điểm nhấn son duy nhất của cảnh:
  `accent: true`.
- **Che nền**: `palette.paper` (màu giấy của style) tô thân bằng màu giấy trước khi vẽ mực: hình che được núi, người
  đứng sau. Dùng cho đám đông và khi nền sau lưng rối.
- Vẽ hình sau lớp nó đứng trên, trước sương phía trước (`mist.band` độ sâu 1.25) để sương phủ lên chân.

## 3. Tư thế và dòng thời gian

| `pose` | Dáng | Ghi chú |
|---|---|---|
| `stand` | đứng, thở và đổi trọng tâm rất nhẹ | mặc định khi không có `path` |
| `walk` | bước đi | mặc định khi có `path`; không có `path` = bước tại chỗ (mục 4) |
| `turn` | quay người sang hướng `view` mới | đầu quay trước, thân theo sau, hai chân nhấc đổi chỗ; xong thì thành `stand` |
| `raise-arm` | giơ một tay quá đầu (`arm: 'right'` \| `'left'`) | chỉ tay, vẫy, ra hiệu |
| `bow` | cúi mình, hai tay chắp trước | rõ nhất ở `view: 'side'` |
| `sit` | ngồi xuống đất, áo xoè | hình thấp còn khoảng 60 % |

Hướng nhìn: `view: 'back'` (mặc định) \| `'side'` (+ `facing: 'left'`) \| `'front'` \| số độ (150 = ba phần tư sau).
`head: 'knot'` (búi tóc + dải buộc) \| `'hat'` (nón lá) \| `'bare'`.

```js
COMPOSE.figure.draw(st, { x: 900, y: 820, height: 150,
  timeline: [{ at: 2, pose: 'raise-arm' }, { at: 4.5, pose: 'stand' }, { at: 6, pose: 'turn', view: 'side' }] });
```
Mỗi mục `timeline` chuyển sang tư thế mới trong `dur` giây (0.5; `turn` 0.8), **theo bậc 12 fps** (bước đôi): thân
không bao giờ trôi mượt như hình cắt dán. `at` tính từ `start` (mặc định 0 = giờ phim).

## 4. Đi dọc một đường

```js
COMPOSE.figure.draw(st, { height: 110, salt: 2,
  path: [{ at: 1, x: 420, y: 830 }, { at: 6, x: 860, y: 800 }, { at: 8, x: 860, y: 800 }, { at: 12, x: 1010, y: 720, h: 80 }] });
```

- `path`: các điểm sân khấu kèm thời điểm. Vị trí trên đường đổi **mỗi khung**; dáng thân đổi theo bậc 12 fps.
- **Chân không trượt**: bàn chân đã đặt xuống đứng yên tại điểm sân khấu của nó cho tới lúc nhấc lên. Độ dài bước suy
  từ tốc độ của đường (nhịp tự nhiên 1,8 bước/giây, bước dài 10–38 % chiều cao). Mỗi đoạn giữa hai lần dừng là một số
  nguyên bước: hình bắt đầu và dừng với hai chân chụm.
- Đường đòi nhanh hơn 2,6 bước/giây → cảnh báo `impossible stride`: cho đoạn đó thêm thời gian hoặc rút ngắn đường.
  Tốc độ đi vừa: khoảng 0,3–0,7 lần chiều cao hình mỗi giây (hình 110 px: 35–75 px/s).
- Hai điểm liên tiếp cùng toạ độ = đứng lại (thở, áo vẫn bay). Hai điểm khác toạ độ cùng thời điểm = nhảy cóc → cảnh báo.
- Hướng nhìn tự theo hướng đường: đi ngang = nhìn nghiêng, đi lên khung (ra xa) = nhìn từ sau, đi xuống = chính diện.
  `view` ghi rõ thì giữ nguyên hướng đó. `h` ở điểm đường đổi chiều cao dần (đi ra xa thì nhỏ lại).
- `timeline` vẫn dùng được trong lúc đi (vd. `raise-arm` khi tới nơi).
- **Bước tại chỗ**: `pose: 'walk'` không có `path`, khi máy quay đi theo người; `speed` (px/s) phải bằng tốc độ nền
  trôi dưới chân, nếu không chân sẽ trượt trên nền.

## 5. Gió

Áo, tay áo, đai và dải buộc tóc nghe theo gió của shot: cùng `st.wind` (hoặc `wind` của riêng hình) và cùng cơn gió
(`COMPOSE.cloth.gust`) với vải của plate, nên mọi thứ trong khung nghiêng cùng hướng, cùng lúc. Biên độ bị chặn: mép
gấu áo lệch tối đa 16 % chiều cao hình, tay áo 6 %, dải buộc tóc không dài ra. Vải chuyển động mỗi khung (mượt), thân
theo bậc. Không gió (`strength: 0`): gấu áo chỉ khẽ động.

## 6. Đám đông

```js
COMPOSE.figure.crowd(st, { count: 14, area: [300, 760, 1500, 900], height: [70, 110], salt: 5,
                           palette: { ink: '#1A1714', paper: '#EFE6D3' },
                           each: (i) => (i % 5 === 0 ? { head: 'hat' } : null) });
```
`area` là hộp sân khấu chứa bàn chân; `height: [xa, gần]` cho người phía trên hộp nhỏ hơn. Mỗi người một `salt`: nhịp
thở, pha vải, nét mực và góc quay khác nhau, **không ai động đồng loạt**. Vẽ từ xa đến gần. Tối đa 60 người; đám đông
nên đứng (`stand`), một hai người `raise-arm` hoặc `sit` qua `each`. Cho đám đông đi: gọi `draw` từng người với `path`
riêng, lệch thời điểm 0,3–1 s.

## 7. Giới hạn và danh sách kiểm

- Không mặt, không cận cảnh, không dị thú, không hoa văn: xem bảng mục 1. Hình code không thay nhân vật đã khóa.
- Không tự dịch `x`, `y` của hình theo thời gian trong shot (trượt): muốn hình đổi chỗ thì dùng `path`.
- Một shot không nên có hình code **và** plate AI của cùng một nhân vật.
- Trước G3, trên `make.py stills` (hai khung cách 1 s) và bản nháp:
  - [ ] hình ≤ 25 % chiều cao khung, không có cảnh báo `over the cap` hay `impossible stride` trong `qc`;
  - [ ] bàn chân nằm trên mặt đứng của lớp nền, không lơ lửng; khi đi, bàn chân đang đặt không trôi theo thân;
  - [ ] hình đọc được là **người mặc áo dài** (đầu, vai, đai, gấu áo, chân), không phải một vệt mực hay một que;
  - [ ] áo và dải buộc tóc nghiêng cùng hướng với sương, khói, vải của plate;
  - [ ] đám đông: không hai người nào giống hệt nhau và động cùng nhịp; nếu chồng lên nhau thì có `palette.paper`.
