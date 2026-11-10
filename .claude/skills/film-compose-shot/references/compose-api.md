# Bộ ghép 2.5D `tools/compose/` – tham chiếu API

**Mã tập (`docs/CONVENTIONS.md` §2):** ví dụ dưới đây viết `ep<NN>` (dự án không chia quyển: thư mục `ep01-<slug>`, media `out/<project>/ep01/`, file `ep01_s03_...`). Dự án chia quyển dùng `q<NN>t<NN>`: thư mục tập `q01-t01-<slug>`, media `out/<project>/q01t01/`, file `q01t01_s03_L4_bac-di_v02.png`, clip `q01t01_s03_seedance25_v01.mp4`, bản dựng `q01t01_draft_v01.mp4`. Đọc mã tập từ `EPISODE.md` (`book` + `episode`) / tên thư mục tập, không tự đổi.

Mã JS thuần (không ES module, không thư viện), gắn vào `window.COMPOSE`. `inline.py` chèn các file theo thứ tự
`core → plates → stage → breath → strip-warp → eyelid → mist → embers → glow` thành một khối `<script>` trước script của
film.html. Toạ độ **sân khấu** luôn là 1920x1080 px; khung render khác cỡ (nháp 960x540, biến thể 1:1) được co theo
kiểu cover. Toạ độ **ảnh** là px của chính file lớp tranh (như trong `anchors.json`).

## 1. Nạp lớp: `COMPOSE.load(spec)` (trong `loadPlates`, trước READY)

```js
const PLATES = {
  L1: { src: '../../plates/ep01_s03_L1_nui-co_v01.png', depth: 0.12, overscan: 1.03 },
  L2: { src: '../../plates/ep01_s03_L2_rung_v01.png', depth: 0.45, overscan: 1.04, cover: false },
  L4: { src: '../../plates/ep01_s03_L4_bac-thi_v02.png', depth: 1.0, place: { x: 860, y: 905, h: 640, pivot: 'feet' },
        rig: { warp: { tail: { amp: 30 } }, eyes: { eye_back: {} }, breath: { pivot: 'feet' } } },
  L4b: { seq: { pattern: '../../clips/ep01_s03_seedance25_v01/{n}.png', count: 120, fps: 24, at: 4.0, end: 'hold' },
         depth: 1.0, cover: false },
};
async function loadPlates() {
  const r = await COMPOSE.load({ seed: SEED, plates: PLATES, mist: { color: '#f2ecde' },
                                 embers: { color: '#ff9a3c', colors: ['#ffd27a'] }, glow: { color: '#ffd49a' } });
  if (r.warnings.length) console.warn('compose: ' + r.warnings.join(' | '));
}
```

| Trường | Ý nghĩa |
|---|---|
| `src` | đường dẫn tương đối từ film.html |
| `depth` | độ sâu parallax (`COMPOSE.DEPTH`: bg 0.12, mid 0.45, fg/char 1.0, mist 1.25, near 1.7) |
| `place` | bỏ trống = phủ kín sân khấu, căn giữa. `{ x, y, h \| w \| scale, pivot }`: điểm `pivot` của ảnh (`'center'`, `'bottom'`, `'top'`, tên điểm neo, `[px, py]`) đặt tại (x, y) sân khấu, cao `h` px |
| `overscan` | nhân thêm kích thước (≥ 1) để máy quay có chỗ di chuyển |
| `cover` | lớp phải luôn phủ kín khung (mặc định `true` khi không có `place`); lộ mép → tự zoom thêm liên tục + cảnh báo |
| `anchors` | khoá trong `anchors.json` (mặc định: tên file của `src`) |
| `rig` | `warp`, `eyes`, `breath` (§4); bỏ qua với lớp `seq` |
| `seq` | chuỗi PNG thay cho `src`: `pattern` (`{n}` = số khung), `digits` 6, `start` 1, `count`, `fps` 24, `at` (giây phim của khung đầu), `end`: `'hold'` \| `'loop'` \| `'hide'`. Không `place` = phủ sân khấu như khung đầu của `keyframe.py` |

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

- strip-warp: `root` là tên điểm hoặc `'left' | 'right' | 'top' | 'bottom'` (mặc định `<tên>_root`). Gốc→ngọn chủ yếu
  nằm ngang → dải dọc lệch lên xuống; chủ yếu thẳng đứng (tóc, vạt áo) → dải ngang lệch sang bên. `amp` tính bằng px
  ảnh ở ngọn; `strip` tính bằng px sân khấu.
- eyelid: `lid` 0 mở … 1 nhắm. `blinks`: nhắm nhanh, giữ chút, mở chậm. `keys`: nội suy mượt giữa các mốc.
- Giá trị có thể là hàm của `t` ngay trong lời gọi (vd. `amp: 30 * (1 - COMPOSE.smooth((t - 4) / 0.5))`).

## 5. Không khí

| Gọi | Tham số chính (mặc định) |
|---|---|
| `COMPOSE.mist.band(st, o)` | `depth` 0.5, `y` 760 (tâm), `h` 300, `speed` 20 px/s (dấu = hướng), `alpha` 0.5, `variant` 0–2, `salt`, `bob` 12, `breathe` 0.3, `blend` |
| `COMPOSE.mist.bands(st, [o, ...])` | nhiều dải một lần |
| `COMPOSE.mist.open(st, o)` | `at` 0, `dur` 2, `alpha` 0.95, `depth` 1.25, `from` 0.22 (phần đã hé ở khung đầu), `dir` 1 |
| `COMPOSE.embers.draw(st, o)` | `box` nơi sinh, `count` 50, `depth` 1, `rise` [50, 130] px/s, `life` [2.2, 4.5] s, `size` [2.5, 7], `drift` 26, `wind` 6, `alpha` 1, `color`, `fade` [[t, v]], `salt`, `blend` `'lighter'` |
| `COMPOSE.glow.sun(st, o)` | `x`, `y`, `r` 180, `depth` 0.12, `intensity` 0.8, `halo` 3, `pulse` 0.05, `color`, `fade`, `blend` `'screen'` |

Màu sương / tàn lửa / quầng sáng phải khai trong `COMPOSE.load` (dựng sẵn trước READY); màu lạ → dùng màu mặc định
+ cảnh báo.

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
- Bộ mã inline ~44 KB; READY (giải mã 4 lớp 2K + dựng texture) ~1–2 s.
