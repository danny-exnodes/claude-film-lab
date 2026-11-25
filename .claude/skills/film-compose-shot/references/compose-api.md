# Bộ ghép 2.5D `tools/compose/` – tham chiếu API

**Mã tập (`docs/CONVENTIONS.md` §2):** ví dụ dưới đây viết `ep<NN>` (dự án không chia quyển: thư mục `ep01-<slug>`, media `out/<project>/ep01/`, file `ep01_s03_...`). Dự án chia quyển dùng `q<NN>t<NN>`: thư mục tập `q01-t01-<slug>`, media `out/<project>/q01t01/`, file `q01t01_s03_L4_bac-di_v02.png`, clip `q01t01_s03_seedance25_v01.mp4`, bản dựng `q01t01_draft_v01.mp4`. Đọc mã tập từ `EPISODE.md` (`book` + `episode`) / tên thư mục tập, không tự đổi.

Mã JS thuần (không ES module, không thư viện), gắn vào `window.COMPOSE`. `inline.py` chèn các file theo thứ tự
`core → plates → stage → breath → strip-warp → foliage → eyelid → cloth → pose → ink → figure → mist → embers → glow → smoke → fire`
thành một khối `<script>` trước script của film.html (`inline.py --lint` in số file được chèn; rig `cloth` và `poses`:
`references/layers-character.md`; hình người vẽ bằng code: §5.4 và `references/layers-figure.md`). Toạ độ **sân khấu** luôn là 1920x1080 px; khung render khác cỡ (nháp 960x540, biến thể 1:1) được co theo
kiểu cover. Toạ độ **ảnh** là px của chính file lớp tranh (như trong `anchors.json`).

## 1. Nạp lớp: `COMPOSE.load(spec)` (trong `loadPlates`, trước READY)

```js
const PLATES = {
  L1: { src: '../../plates/ep01_s03_L1_nui-co_v01.png', depth: 0.12, overscan: 1.03 },
  L2: { src: '../../plates/matte/ep01_s03_L2_rung_v01.png', depth: 0.45, overscan: 1.04, cover: false },
  L4: { src: '../../plates/matte/ep01_s03_L4_bac-thi_v02.png', depth: 1.0, place: { x: 860, y: 905, h: 640, pivot: 'feet' },
        rig: { warp: { tail: { amp: 30 } }, eyes: { eye_back: {} }, breath: { pivot: 'feet' } } },
  L4b: { seq: { pattern: '../../clips/ep01_s03_seedance25_v01/{n}.png', count: 120, fps: 24, at: 4.0, end: 'hold' },
         depth: 1.0, cover: false },
};
async function loadPlates() {
  const r = await COMPOSE.load({ seed: SEED, plates: PLATES, mist: { color: '#f2ecde' },
                                 embers: { color: '#ff9a3c', colors: ['#ffd27a'] }, glow: { color: '#ffd49a' },
                                 smoke: { color: '#1a1714', light: '#f2ecde' },          // tuỳ chọn (§5.1)
                                 fire: { inner: '#e0a23a', outer: '#b02e22' } });        // tuỳ chọn (§5.2)
  if (r.warnings.length) console.warn('compose: ' + r.warnings.join(' | '));
}
```

| Trường | Ý nghĩa |
|---|---|
| `src` | đường dẫn tương đối từ film.html. Lớp đã tách nền (matte khác `none`: L2–L4, P, FX) nằm ở `../../plates/matte/<cùng tên file>`; L1 (matte `none`) vẫn ở `../../plates/` (`docs/CONVENTIONS.md` §3) |
| `depth` | độ sâu parallax (`COMPOSE.DEPTH`: bg 0.12, mid 0.45, fg/char 1.0, mist 1.25, near 1.7) |
| `place` | bỏ trống = phủ kín sân khấu, căn giữa. `{ x, y, h \| w \| scale, pivot }`: điểm `pivot` của ảnh (`'center'`, `'bottom'`, `'top'`, tên điểm neo, `[px, py]`) đặt tại (x, y) sân khấu, cao `h` px |
| `overscan` | nhân thêm kích thước (≥ 1) để máy quay có chỗ di chuyển |
| `cover` | lớp phải luôn phủ kín khung (mặc định `true` khi không có `place`; lớp `seq` mặc định `false` vì clip đã tách nền không có mép để che và phải trùng khít lớp nó thay thế); lộ mép → tự zoom thêm liên tục + cảnh báo `compose: plate <id> shows its edge` |
| `anchors` | khoá trong `anchors.json` (mặc định: tên file của `src`) |
| `rig` | `warp`, `sway`, `eyes`, `breath` (§4); bỏ qua với lớp `seq` |
| `seq` | chuỗi PNG thay cho `src`: `pattern` (`{n}` = số khung), `digits` 6, `start` 1, `count`, `fps` 24, `at` (giây phim của khung đầu), `end`: `'hold'` \| `'loop'` \| `'hide'`. Trước `at`: `hold` hiện khung đầu, `loop` quay vòng, `hide` không vẽ gì; sau khung cuối: giữ khung cuối / quay vòng / ẩn. Mọi khung phải cùng kích thước với khung đầu (khác → `load` báo lỗi `plate <id>: frame <i> is WxH, frame 0 is WxH`). Không `place` = phủ sân khấu như khung đầu của `keyframe.py` |

Mọi ảnh được `decode()` và chép sang canvas; mọi texture (sương, tàn lửa, quầng sáng, phần cắt của rig) dựng xong
trước khi `load` trả về. Ảnh lỗi làm READY thất bại với tên lớp và đường dẫn.

## 2. `anchors.json` (film-plate-maker viết bằng `tools/layers/anchors.py`, `projects/<project>/ep<NN>-<slug>/anchors.json`)

```bash
python3 tools/layers/anchors.py set  projects/<p>/ep01-<slug>/anchors.json ep01_s03_L4_bac-thi_v02.png subject 540 995
python3 tools/layers/anchors.py set  projects/<p>/ep01-<slug>/anchors.json ep01_s03_L4_bac-thi_v02.png tail_tl 1290 760
python3 tools/layers/anchors.py mark out/<p>/ep01/plates/ep01_s03_L4_bac-thi_v02.png projects/<p>/ep01-<slug>/anchors.json /tmp/mark.png
```
```json
{ "ep01_s03_L4_bac-thi_v02.png": {
    "subject": [540, 995], "feet": [900, 1720], "tail_root": [1310, 1195], "tail_tip": [1985, 880],
    "tail_tl": [1290, 760], "tail_br": [2044, 1330], "eye_back_tl": [466, 946], "eye_back_br": [614, 1044] } }
```
- Toạ độ px trên ảnh đã duyệt (đúng ảnh dùng trong phim). Bộ ghép cũng đọc dạng `{ "plates": { "<file>": { "size",
  "points", "boxes" } } }`; có `size` (hoặc `_size`) khác cỡ ảnh thì tự co theo, kèm cảnh báo.
- Điểm: `subject` (máy quay tiến về), `feet` (pivot đặt lớp, thở), `<vùng>_root` / `<vùng>_tip` (strip-warp).
- Hộp = cặp điểm `<tên>_tl` (trên trái) và `<tên>_br` (dưới phải): vùng warp (chỉ phần được cử động + nền trong suốt
  quanh nó), hộp mắt (sát mép mắt; vùng ngay phía trên hộp phải là da/lông liền, vì mí được lấy từ đó).
- Kiểm: ảnh `anchors.py mark`, rồi `make.py stills` ở thời điểm chớp mắt / đuôi cong nhất.

## 3. Máy quay và sân khấu

```js
const cam = COMPOSE.camera(t, { from, to, ease, zoom: [z0, z1], toward: [x, y], center, pan: [[dx0, dy0], [dx1, dy1]],
                                shake: { amp, freq, roll, salt }, events: [{ at, dur, zoom, kick, decay }], seed });
COMPOSE.stage(g, S, cam, (st) => { st.plate('L1'); /* ... */ });
```
- `ease`: `'inOut'` (mặc định), `'out'`, `'in'`, `'linear'`, `'sine'` hoặc hàm. `center`: 0 giữ chủ thể tại chỗ trên
  màn hình, 1 đưa vào giữa (mặc định 0.35). `pan`: px sân khấu ở độ sâu 1.
- Lớp ở độ sâu d thấy zoom `1 + (z − 1)·d` và độ lệch `pos·d`. Rung là dịch/xoay toàn khung, noise có seed.
- `st.layer(depth, (g) => {...})` vẽ tuỳ ý trong toạ độ sân khấu qua máy quay; `st.screen((g) => {...})` vẽ không qua
  máy quay; `st.plate(id, o)` vẽ một lớp kèm rig. `o`: `{ t, depth, alpha, blend, filter, dx, dy, breath, warp, eyes }`;
  `t: Math.floor(t * 12) / 12` cho rig nhân vật bước đôi (12 fps) như recipe ink-wash §5.
- `COMPOSE.anchor(id, name)` → điểm neo theo toạ độ sân khấu (trước máy quay).

## 4. Rig của lớp

| Rig | Khai trong `rig` | Theo shot (`st.plate(id, { ... })`) |
|---|---|---|
| strip-warp | `warp: { <tên>: { box, root, tip, amp: 16, waves: 0.8, speed: 0.45, power: 1.6, sway: 0.35, lag: 0.35, strip: 4, salt } }` | `warp: false` (đứng yên) hoặc `{ <tên>: {...} \| false }` |
| eyelid | `eyes: { <tên>: { box, gap: 2, source: 'above' \| [dx, dy], grow: 1.08, close: 0.3, line, lineWidth: 0.07, blinks, keys } }` | `eyes: { <tên>: { blinks: [{ at, dur }], keys: [[t, lid]] } \| false }` |
| breath | `breath: { amp: 0.008, period: 3.6, pivot: 'bottom', width: 0.25, salt }` | `breath: false` hoặc `{...}` ghi đè |
| foliage | `sway: { <tên>: { box, root: 'bottom', amp: 0.015, period: 5.5, gust: 0.6, power: 1.6, lag: 0.5, strip: 4, salt } }` | như strip-warp: `warp: false`, `warp: { <tên>: false \| {...} }` |

- strip-warp: `root` là tên điểm hoặc `'left' | 'right' | 'top' | 'bottom'` (mặc định `<tên>_root`). Gốc→ngọn chủ yếu
  nằm ngang → dải dọc lệch lên xuống; chủ yếu thẳng đứng (tóc, vạt áo) → dải ngang lệch sang bên. `amp` tính bằng px
  ảnh ở ngọn; `strip` tính bằng px sân khấu.
- eyelid: `lid` 0 mở … 1 nhắm. `blinks`: nhắm nhanh, giữ chút, mở chậm. `keys`: nội suy mượt giữa các mốc.
- Giá trị có thể là hàm của `t` ngay trong lời gọi (vd. `amp: 30 * (1 - COMPOSE.smooth((t - 4) / 0.5))`).
- foliage (id `foliage`, `foliage.js`): tán cây / bụi / cỏ đung đưa **tại chỗ** – vùng hộp bị xô ngang theo dải, bằng 0
  ở đường gốc, lớn dần về phía ngọn, theo một nhịp gió chậm; không trượt, không xoay cả khối. Chi tiết: §5.3.

## 5. Không khí

| Gọi | Tham số chính (mặc định) |
|---|---|
| `COMPOSE.mist.band(st, o)` | `depth` 0.5, `y` 760 (tâm), `h` 300, `speed` 20 px/s (dấu = hướng), `alpha` 0.5, `variant` 0–2, `salt`, `bob` 12, `breathe` 0.3, `blend` |
| `COMPOSE.mist.bands(st, [o, ...])` | nhiều dải một lần |
| `COMPOSE.mist.open(st, o)` | `at` 0, `dur` 2, `alpha` 0.95, `depth` 1.25, `from` 0.22 (phần đã hé ở khung đầu), `dir` 1 |
| `COMPOSE.embers.draw(st, o)` | `box` nơi sinh, `count` 50, `depth` 1, `rise` [50, 130] px/s, `life` [2.2, 4.5] s, `size` [2.5, 7], `drift` 26, `wind` 6, `alpha` 1, `color`, `fade` [[t, v]], `salt`, `blend` `'lighter'` |
| `COMPOSE.glow.sun(st, o)` | `x`, `y`, `r` 180, `depth` 0.12, `intensity` 0.8, `halo` 3, `pulse` 0.05, `color`, `fade`, `blend` `'screen'` |
| `COMPOSE.smoke.plume(st, o)` | cột khói từ một điểm (§5.1) |
| `COMPOSE.fire.flames(st, o)` · `COMPOSE.fire.glow(st, o)` | lưỡi lửa và ánh lửa (§5.2) |

Màu sương / tàn lửa / quầng sáng / khói / lửa phải khai trong `COMPOSE.load` (dựng sẵn trước READY); màu lạ → dùng màu
mặc định + cảnh báo. Không khai `smoke` / `fire` thì dùng màu mặc định ghi ở dưới.

Ba module dưới đây làm khói, lửa, cây cử động **hoàn toàn bằng code** (phương pháp `layers`: không gọi Seedance). Cũng như
mọi thứ trong bộ ghép: hàm thuần của `(t, SEED)`, khung nào cũng render độc lập được; tham số sai (NaN, kích thước ≤ 0,
thiếu hộp neo; với khói và lửa: mọi trường số, kể cả `alpha`, `depth`, `t`) → một dòng `compose: ...` trong `qc` và phần
đó không vẽ / đứng yên, không làm hỏng READY. Lời gọi nhận
`st` như các module không khí khác (thời gian lấy từ `st.t`; truyền `t:` để vẽ ở thời điểm khác, vd. bước đôi 12 fps).

### 5.1 Khói: `COMPOSE.smoke.plume(st, o)` (id `smoke`)

Cột khói bốc lên và cuộn từ một điểm: chuỗi "bụm khói" mềm, mỗi bụm bay lên, nở rộng, nghiêng theo gió, uốn theo một
đường lượn chậm rồi tan trước độ cao `height`. Khung 0 đã có sẵn cả cột khói.

| Trường | Mặc định | Khoảng nên dùng | Ý nghĩa |
|---|---|---|---|
| `x`, `y` | bắt buộc | – | gốc khói, px sân khấu ở độ sâu đó (`COMPOSE.anchor('L3', 'fire')` cho điểm neo) |
| `depth` | 1 | 0.12–1.7 | độ sâu parallax |
| `rate` | 4 | 2–8 | số bụm sinh ra mỗi giây; cả cột có `rate · height / rise` bụm (tối đa 240, vượt → cảnh báo) |
| `rise` | 70 | 30–160 | tốc độ bay lên, px/s |
| `height` | 560 | 150–900 | độ cao (px) nơi bụm khói đã tan hết |
| `size` | 30 | 10–60 | bán kính bụm tại gốc, px |
| `spread` | 0.3 | 0.1–0.6 | bán kính tăng thêm trên mỗi px bay lên (cột khói hình nón) |
| `wind` | 12 | −60…60 | gió ngang px/s (+ sang phải); độ nghiêng tăng theo độ cao |
| `curl` | 36 | 0–90 | px uốn lượn ngang ở gần đỉnh |
| `alpha` | 0.5 | 0.2–0.8 | độ đục của một bụm (0–1); các bụm chồng nhau nên gần gốc đậm hơn |
| `color` | mực đậm `spec.smoke.color` (`#1a1714`) | – | một màu đã khai trong `COMPOSE.load` (`smoke: { color, light, colors: [...] }`) |
| `light` | `false` | – | `true`: khói sáng (`spec.smoke.light`, `#f2ecde`), hoà `'screen'` – cho nền tối |
| `blend` | `'source-over'` (khói đậm trên giấy sáng) | – | ghi đè kiểu hoà |
| `fade` | – | `[[t, v], ...]` | độ đục theo thời gian phim (lửa tàn dần) |
| `salt` | suy từ gốc `(x, y)` | số nguyên | cột khói nào. Hai cột trong một shot tự khác nhịp. **Gốc khói di chuyển theo `t` → đặt `salt` cố định** (nếu không cột khói bị xáo lại mỗi lần gốc đổi chỗ) |

```js
COMPOSE.smoke.plume(st, { x: 980, y: 760, depth: 1.0 });                                         // khói bếp lửa
COMPOSE.smoke.plume(st, { x: 420, y: 610, depth: 0.45, height: 380, size: 16, rate: 3, alpha: 0.35 });   // mái nhà xa
COMPOSE.smoke.plume(st, { x: 980, y: 760, light: true, alpha: 0.4 });                            // khói sáng trên nền tối
```

### 5.2 Lửa: `COMPOSE.fire.flames(st, o)` và `COMPOSE.fire.glow(st, o)` (id `fire`)

`flames`: các lưỡi lửa nhấp nháy đứng trên một đường chân (`base`) hoặc tại các điểm (`points`: đuốc, nến). Mỗi lưỡi là
một sprite hình giọt (màu `inner` – thổ hoàng – ở chân, chuyển sang `outer` – màu nhấn – ở ngọn), chiều cao, độ nghiêng
và độ sáng theo noise có seed. Mỗi lưỡi vẽ hai lượt: thân màu (`source-over`, để lửa giữ được màu trên giấy sáng) rồi một
lượt cộng sáng (`'lighter'`). Một lưỡi không bao giờ cao quá nửa sân khấu (540 px) hay rộng quá một phần tư (480 px):
là ngọn lửa, không bao giờ là chớp sáng toàn khung (vượt → bị giới hạn + cảnh báo).

| Trường | Mặc định | Khoảng nên dùng | Ý nghĩa |
|---|---|---|---|
| `base` \| `points` | bắt buộc một trong hai | – | `[x0, y0, x1, y1]` đường chân lửa, hoặc `[[x, y], ...]` các điểm; px sân khấu |
| `depth` | 1 | – | độ sâu parallax |
| `count` | đường: 1 lưỡi / nửa bề rộng lưỡi (≥ 3); điểm: 3 / điểm | ≤ 200 | số lưỡi lửa |
| `h` | 140 | 30–400 | lưỡi cao nhất, px |
| `w` | 60 | 16–160 | bề rộng lưỡi, px |
| `flicker` | 0.45 | 0.2–0.7 | phần chiều cao lúc có lúc không (0–1) |
| `speed` | 1 | 0.5–2.5 | 1 = lửa trại; 2 = lửa dữ |
| `sway` | 0.18 | 0–0.4 | ngọn lửa đảo ngang, tính theo phần chiều cao (ngọn lệch tối đa 0.6 · cao) |
| `lean` | 0 | −80…80 | px ngọn bị gió đẩy ngang (+ sang phải) |
| `alpha` | 0.9 | 0.5–1 | độ đục (0–1) |
| `body` | 0.8 | 0–1 | phần vẽ thành thân màu dưới lượt cộng sáng; 0 = chỉ cộng sáng (lớp nền tối) |
| `palette` | `spec.fire.inner` / `outer` (`#e0a23a` / `#b02e22`) | – | tên một bộ màu khai trong `fire: { palettes: { <tên>: { inner, outer } } }` (vd. lửa ma xanh) |
| `blend`, `fade`, `salt` | `'lighter'`, –, suy từ `base` / điểm đầu | – | kiểu hoà của lượt cộng sáng; cường độ theo thời gian; đống lửa nào |

`glow`: ánh lửa ấm, mềm, nhấp nháy trên các lớp **đã vẽ trước nó** (hoà `'screen'`: nâng sáng mà không cháy trắng). Độ
đục không bao giờ vượt `intensity`, và `intensity` bị chặn ở `COMPOSE.fire.MAX_GLOW` = 0.6.

| Trường | Mặc định | Khoảng nên dùng | Ý nghĩa |
|---|---|---|---|
| `x`, `y` | bắt buộc | – | tâm ánh lửa, px sân khấu |
| `r` | 280 | 120–600 | bán kính, px |
| `depth` | 1 | – | độ sâu parallax |
| `intensity` | 0.3 | 0.1–0.6 | độ đục lớn nhất (0–1, chặn ở 0.6) |
| `pulse` | 0.3 | 0–0.5 | phần cường độ nhấp nháy mất đi: độ đục nằm trong `intensity · (1 − pulse) … intensity` |
| `speed`, `palette`, `fade`, `salt` | 1, mặc định, –, suy từ `(x, y)` | – | như `flames` |
| `blend` | `'screen'` | – | trên giấy sáng `'screen'` gần như không thấy: dùng `'soft-light'` để nhuộm ấm vùng giấy quanh lửa |

**Ghép với tàn lửa và khói** – một đống lửa là năm lời gọi đầu dưới đây, từ xa đến gần, dùng chung một đường chân (`embers` sinh ra ở
nơi lưỡi lửa kết thúc; màu tàn lửa khai ở `embers` của `COMPOSE.load`):

```js
COMPOSE.smoke.plume(st, { x: 900, y: 800, depth: 1 });                          // khói sau lưỡi lửa
st.plate('L4');                                                                 // lớp được lửa chiếu
COMPOSE.fire.glow(st, { x: 900, y: 880, r: 320, intensity: 0.3 });              // sau các lớp nó chiếu sáng
COMPOSE.fire.flames(st, { base: [780, 900, 1020, 900], h: 150 });
COMPOSE.embers.draw(st, { box: [780, 820, 1020, 900], count: 30 });             // tàn lửa bay lên từ ngọn lửa
COMPOSE.fire.flames(st, { points: [[1500, 500], [1800, 420]], h: 70, w: 30 });  // hai ngọn đuốc
```

### 5.3 Cây cỏ: rig `sway` (id `foliage`)

```js
L2: { src: '../../plates/matte/ep01_s03_L2_rung_v01.png', depth: 0.45, overscan: 1.04, cover: false,
      rig: { sway: { tan_trai: {}, tan_phai: { amp: 0.012, period: 6.5 }, co: { amp: 0.03, period: 3 },
                     day_leo: { root: 'top' } } } },
// theo shot: st.plate('L2', { warp: { co: false } })  ·  st.plate('L2', { warp: { tan_trai: { amp: 0.02 } } })
```
Điểm neo (px ảnh, `anchors.py set`): hộp `<tên>_tl` / `<tên>_br` bao **chỉ** phần được đung đưa (tán cây, bụi, cụm cỏ) và
nền trong suốt quanh nó; tuỳ chọn điểm `<tên>_root` nếu đường gốc không phải mép dưới hộp.

| Trường | Mặc định | Khoảng nên dùng | Ý nghĩa |
|---|---|---|---|
| `box` | tên vùng | – | tên hộp neo hoặc `[x0, y0, x1, y1]` (px ảnh) |
| `root` | điểm `<tên>_root` nếu có, không thì `'bottom'` | `'bottom'`, `'top'`, tên điểm | đường gốc (đứng yên): mép dưới hộp; `'top'` cho dây leo / cành rủ; tên điểm → đường ngang qua điểm đó, phần hộp bên kia đường gốc (thân cây) đứng yên |
| `amp` | 0.015 | 0.005–0.04 | độ lệch ngang lớn nhất ở ngọn, tính bằng **phần chiều cao** từ đường gốc tới ngọn (1.5 %). Chặn ở `COMPOSE.foliage.MAX_AMP` = 0.04 (lớn hơn trông như cao su) + cảnh báo |
| `period` | 5.5 | 2.5–9 | giây cho một nhịp đung đưa (cỏ nhanh, cây to chậm) |
| `gust` | 0.6 | 0–1 | phần chuyển động lặng đi giữa hai đợt gió |
| `power` | 1.6 | 1–2.5 | độ lệch tăng nhanh thế nào khi ra xa gốc |
| `lag` | 0.5 | 0–1.2 | ngọn trễ sau gốc bao nhiêu giây |
| `strip` | 4 | 2–8 | bề dày dải, px sân khấu |
| `salt` | suy từ lớp + hộp | số nguyên | các cây cạnh nhau tự khác nhịp, không cần đặt |

- Dùng chung bộ máy strip-warp (cắt vùng lúc nạp, vẽ theo dải, mối nối không lộ), chỉ khác luật độ lệch
  (`COMPOSE.foliage.offset`); vì vậy điều khiển theo shot đi qua khoá `warp` của `st.plate`, và tên vùng `sway` không
  được trùng tên vùng `warp` trên cùng lớp (trùng → vùng `sway` bị bỏ + cảnh báo).
- Hộp thiếu trong `anchors.json`, hộp nhỏ hơn 8 px, đường gốc nằm sát đầu ngọn → cảnh báo
  `compose: plate <id>: sway <tên> ...` và vùng đó đứng yên (lớp vẫn vẽ bình thường).
- `period`, `gust`, `power`, `lag`, `strip`, `salt` không phải số hữu hạn (hoặc `power` ≤ 0) → cảnh báo và dùng giá trị
  mặc định; giá trị ghi đè theo shot cũng được xử lý như vậy (không cảnh báo), nên độ lệch luôn ≤ `amp` · chiều cao.
- Kiểm: `make.py stills` ở hai thời điểm cách nhau nửa `period`; mép tán không được lộ răng cưa, gốc không được hở.

### 5.4 Hình người vẽ bằng code: `COMPOSE.figure.draw(st, o)`, `COMPOSE.figure.crowd(st, o)` (id `figure`) và nét mực `COMPOSE.ink`

Người nhỏ trong **cảnh rộng**, vẽ hoàn toàn bằng nét mực code, không ảnh; khi nào dùng, tư thế, đường đi, đám đông và
giới hạn: `references/layers-figure.md`. Thân theo bậc 12 fps, vị trí trên đường và vải mỗi khung; bàn chân đã đặt
không trượt.

```js
st.wind = { dir: 'right', strength: 0.6, gust: 0.5 };
st.plate('L1'); st.plate('L2'); st.plate('L3');
COMPOSE.figure.draw(st, { on: { plate: 'L3', anchor: 'song_nui' }, height: 120, salt: 1,           // đứng trên sống núi
                          timeline: [{ at: 3, pose: 'raise-arm' }] });
COMPOSE.figure.draw(st, { height: 110, salt: 2, head: 'hat',                                       // đi dọc đường
                          path: [{ at: 1, x: 420, y: 830 }, { at: 6, x: 860, y: 800 }] });
COMPOSE.figure.crowd(st, { count: 12, area: [300, 760, 1500, 900], height: [70, 110], palette: { paper: '#EFE6D3' } });
```

`COMPOSE.figure.draw(st, o)` → trạng thái của hình (`null` = không vẽ được); `COMPOSE.figure.state(st, o)` trả cùng dữ
liệu mà không vẽ (`x, y, h, yaw, tq, pose, feet[{ x, y, planted, lift }], cloth, path{ stride, steps, cadence }`).

| Trường | Mặc định | Khoảng nên dùng | Ý nghĩa |
|---|---|---|---|
| `x`, `y` \| `on` | giữa khung, 80 % chiều cao | – | bàn chân, px sân khấu; hoặc `on: { plate, anchor, dx, dy }`: điểm neo của một plate đã nạp (lấy luôn độ sâu của plate); `on: 'L3'` = điểm `feet` của plate đó. Thiếu plate/điểm → cảnh báo, dùng `x`, `y` nếu có, không thì không vẽ |
| `depth` | độ sâu của plate trong `on`, không thì 1 | – | độ sâu parallax |
| `height` | 160 | 40–270 | chiều cao hình, px sân khấu. **Chặn ở 270** (25 % sân khấu, `COMPOSE.figure.CAP`): lớn hơn → thu về 270 + cảnh báo (dùng plate AI + `cloth` / `pose-cycle`) |
| `view` | `'back'`; có `path` thì theo hướng đường | `'back'`, `'side'`, `'front'`, số độ | 0 = chính diện, 90 = nhìn nghiêng quay phải, 180 = từ sau, 150 = ba phần tư sau |
| `facing` | `'right'` | `'right'`, `'left'` | hướng mặt khi `view: 'side'` |
| `pose` | `'stand'` (có `path`: `'walk'`) | `stand`, `walk`, `turn`, `raise-arm`, `bow`, `sit` | tư thế nền; tên lạ → cảnh báo |
| `timeline` | – | `[{ at, pose, view, facing, arm, dur }]` | đổi tư thế tại `at` giây trong `dur` (0.5; `turn` 0.8), theo bậc 12 fps; `arm: 'right'` \| `'left'` cho `raise-arm` |
| `path` | – | `[{ at, x, y, h }]` hoặc `[[at, x, y, h], ...]` | đi dọc các điểm sân khấu; `h` tuỳ chọn = chiều cao tại điểm đó. Hai điểm trùng toạ độ = dừng. Bước dài suy từ tốc độ; > 2,6 bước/giây → cảnh báo `impossible stride` |
| `speed` | 0,36 · `height` px/s | 0,2–0,9 · `height` | chỉ cho `pose: 'walk'` không `path` (bước tại chỗ): tốc độ nền trôi dưới chân |
| `start` | 0 | – | giờ phim của mốc 0 của `timeline` và `path` |
| `salt` | 0 | số nguyên | người nào: pha thở, pha vải, nét mực, chân bước trước. Hai hình cùng shot phải khác `salt` |
| `head` | `'knot'` | `'knot'`, `'hat'`, `'bare'` | búi tóc + dải buộc, nón lá, đầu trần |
| `ribbon` | 22 | 0–30 | chiều dài dải buộc tóc, đơn vị thân (thân cao 100); 0 = không có |
| `wind` | `st.wind` | `{ dir, strength, gust }` | gió riêng của hình, chồng lên gió của shot (cùng dạng với `cloth`) |
| `palette` | `{ ink: '#1a1714', accent: '#b02e22' }` | màu của style | `ink` mọi nét; `accent` cho dải buộc tóc khi `accent: true`; `paper` (không mặc định): tô thân bằng màu giấy trước (độ đục `cover` 0.9) để che thứ phía sau |
| `tone` | 1 | 0.5–1 | nhân vào độ đậm mọi nét (người ở xa nhạt hơn) |
| `blend`, `alpha` | `'multiply'`, 1 | – | mực làm tối giấy; nền tối dùng `'source-over'` |
| `ground` | `true` | – | một nét khô nhạt dưới chân |
| `boil` | 0 | 0–0.5 | nét mực "sôi" nhẹ theo bậc 12 fps (bề rộng nét, không phải chỗ đứt nét) |
| `seed`, `t` | `COMPOSE.seed`, `st.t` | – | |

`crowd`: `count` (5; tối đa 60), `area: [x0, y0, x1, y1]` (hộp chứa bàn chân, bắt buộc), `height: n | [xa, gần]` (90),
`salt`, `each: (i, o) => ghi đè cho người thứ i`, và mọi trường của `draw` (riêng `on` chỉ cho **độ sâu** của plate:
chỗ đứng do `area` quyết định). Trả về danh sách trạng thái, xa đến gần.

**Nét mực** – dùng được riêng cho một nét vẽ tay (một nhành cỏ, một vệt chim), vẽ thẳng vào `g` của `st.layer`:

```js
st.layer(1, (g) => {
  COMPOSE.ink.stroke(g, [[400, 700], [520, 640], [700, 660]], { id: 'canh-1', w: 9, tone: 'nong', dry: 0.6 });
  COMPOSE.ink.mass(g, [[300, 800], [600, 760], [640, 840], [320, 860]], { id: 'da-1', tone: 'qing', soft: 3 });
});
```

| Trường (`stroke`) | Mặc định | Khoảng nên dùng | Ý nghĩa |
|---|---|---|---|
| `id` | – | chuỗi hoặc số | hạt giống của nét: cùng `id` → cùng sợi lông bút và cùng chỗ đứt nét ở mọi khung. **Luôn đặt** |
| `w` | 4 | 1–40 | bề rộng nét, px |
| `tone` | `'nong'` | `jiao` 0.96, `nong` 0.82, `zhong` 0.6, `dan` 0.34, `qing` 0.16, hoặc số 0–1 | năm sắc mực (焦濃重淡清) = độ đục |
| `dry` | 0.25 | 0–1 | 0 = nét ướt liền; 1 = phi bạch (nét khô đứt quãng). Mực cạn dần về cuối nét |
| `profile` | `'brush'` | `brush`, `even`, `tip`, `lens`, `nail`, `robe`, `dot`, hoặc hàm `u → 0..1` | lực nhấn dọc nét |
| `rough` | 0.12 | 0–0.3 | nhiễu bề rộng |
| `side` \| `toward` | 0 | −1…1 \| `[dx, dy]` | bút "ăn mực một bên": mép đó đậm hơn (`toward`: mép quay về hướng đó) |
| `bristles`, `body`, `hair`, `fade` | theo `w`, 1, 1, `dry`·0.55 | – | số sợi lông; trọng số thân ướt / sợi lông; mực mất dọc nét |
| `steps`, `span` | theo chiều dài, 10·`w` | – | số đoạn lấy mẫu và chiều dài vân nét: giữ cố định cho một nét chuyển động để chỗ đứt không bò |
| `color`, `seed`, `alpha` | `'#1a1714'`, `COMPOSE.seed`, 1 | – | |
| `boil`, `t` | 0, 0 | 0–0.5 | bề rộng nét đổi theo bậc 12 fps |

`mass(g, đa giác, { id, tone: 'qing', soft: 2, passes: 3, color, grad })`: khối mực nhạt mép mềm (tô `passes` lượt, mỗi
lượt mép lệch ngẫu nhiên có seed tới `soft` px). `COMPOSE.ink.plan(points, o)` trả hình học của nét (thuần, để kiểm).

## 6. Tiện ích (thuần, có seed)

`COMPOSE.rng(seed, salt)` (dòng số 0–1), `hash(seed, n, salt)`, `noise(seed, x, salt)`, `fbm(seed, x, salt, oct)`,
`noise2`, `fbm2`, `track(keys, t)`, `ease.{linear,in,out,inOut,sine}`, `smooth`, `clamp`, `lerp`, `fract`,
`frameOf(plate, t)`, `get(id)`, `DEPTH`, `STAGE`, `seed`, `warnings`. Seed mặc định là `SEED` của film.html.

## 7. Công cụ đi kèm

| Lệnh | Việc |
|---|---|
| `python3 tools/compose/inline.py <film.html> [--init] [--anchors <file>] [--size WxH]` | chèn/cập nhật bộ mã, nối READY, 1920x1080, kiểm tất định; `--lint` chỉ kiểm bộ mã |
| `python3 tools/compose/keyframe.py <L4.png> <out.png> --x --y --h --pivot [--anchors] --key "#00FF00"` | khung đầu 1920x1080 cho Seedance, nhân vật trên nền key đúng vị trí sân khấu |
| `python3 tools/compose/demo_plates.py out/demo` | 4 lớp thử + `anchors.json` (Pillow, miễn phí) |
| `tools/compose/chrome-root.sh` | Chrome có `--no-sandbox` cho `CHROME_PATH` khi chạy bằng root |
| `tools/compose/motions.json` | id chuyển động (style.yaml `motion:`, shots.csv `code_motion`) → lời gọi |

## 8. Số đo (container cloud, CPU, Chrome headless, 2 worker; shot thử 4 lớp + sương + tàn lửa + warp + mắt)

- Tất định: `capture.mjs --verify` → `deterministic: yes`; 6 khung render theo thứ tự xuôi/ngược với 1 và 2 worker:
  trùng từng bit.
- 1920x1080: ~10 khung/s (8 s phim = 20 s). `make.py draft` 8 s: ~20 s cả kiểm tra. `make.py stills` 4–6 khung: ~3 s.
- Bộ mã inline ~140 KB (v1.2.0, 16 file); READY (giải mã 4 lớp 2K + dựng texture) ~1–2 s.
