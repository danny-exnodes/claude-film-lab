# Phương pháp `code`: nhân vật và cảnh vẽ hoàn toàn bằng code (bộ TOON)

Đọc file này khi `EPISODE.md` của tập ghi `method: code`. Không gọi model tạo ảnh hay video nào: `budget.yaml` có
`images: 0` và `video_seconds: 0`; không `prompts.csv`, không `plates/`, không khâu 5–6. Nguồn: #38 (bộ 10 phong cách),
#39–#43; gộp `code3d` của #35.

## 1. Bộ TOON (`tools/toon/`)

| File | Làm gì |
|---|---|
| `rig.js` | nhân vật = dữ liệu (`character.json`): thân `drop` / `blob` / `box`, 1 hoặc 2 mắt, chỏm tóc, tay chân ống; khung xương, IK hai đoạn |
| `motion.js` | timeline hành động → tư thế tại `t`: `walk`, `run`, `turn`, `jump`, `wave`, `cheer`, `point`, `bounce`, `look`, `blink`, `idle`; chớp mắt và thở tự động |
| `creature.js` | dị thú = spec (**Thông số model**, §8) + seed: thân loft theo spline (thân – cổ – đầu liền một khối), 0/2/4/6 chân IK, nhiều đuôi trễ pha, cánh lông vũ, sừng, tai, bờm, 1–3 mắt; chu kỳ `walk`, `run`, `swim`, `fly`, `turn`, `idle` + lớp phủ `look`, `head-turn`, `flap`, `tail-fan`, `blink`, `breath`; dữ liệu lưới (bố cục đỉnh cố định mọi khung) |
| `project.js` | máy quay (`pos`, `target`, `fov`, `move`, `follow`, `shake`), phép chiếu, danh sách hình 2D, đạo cụ cảnh theo seed (đồi, cây, đá, mây) |
| `look2d.js` | look canvas: `flat-toon`, `ink-silhouette`, `rubber-hose`, `blueprint` |
| `look3d.js` | look three.js: `clay-3d`, `lowpoly-90s`, `cardboard`, `popup-paper` (hai look đầu vẽ được dị thú) |
| `ink3d.js` | look `ink-wash-3d`: mực loang bậc theo thớ giấy, mực đọng ở mép lớp, nét khô ở rìa, viền inverted-hull mảnh dần theo khoảng cách; núi heightfield ba tầng có nét thuân, chấm rêu, chân tan vào sương; dải sương; mặt nước có vòng sóng; giấy dó nhân lên khung |
| `post.js` | hậu kỳ áp lên mọi khung: `riso`, `pixel-16`, `ascii` |
| `toon.js` | `TOON.ready(scene)`, `TOON.render(g, W, H, scene, t)`; chữ viết bút lông `scene.write` (`brush-write`) |
| `looks.json` | sổ đăng ký look và hậu kỳ (khớp `TOON.LOOKS` / `TOON.POSTS`); `creatures: true` = look vẽ được dị thú |
| `toon.py` | xem thử miễn phí: `still`, `turntable`, `clip`, `lookbook`, `reel`; `--creature <mẫu hoặc spec.json>` |
| `demo/giot.json` | linh vật của lab, "Giọt" |
| `demo/creatures/*.json` | ba dị thú mẫu, thiết kế riêng cho lab: `mac-loc` (4 chân), `van-dieu` (2 chân, cánh), `luc-tuc-ngu` (6 chân, bơi) |
| `three.lock` | phiên bản và mã băm three.js ghim (`install_three.sh`, `doctor.sh` dòng `three`) |

Mọi khung là hàm thuần của `(scene, t)`: không `Math.random`, `Date`, `performance.now` (`inline.py` từ chối). three.js
ghim cục bộ (`tools/toon/three.lock`, `FILM_THREE`, cài bằng `tools/toon/install_three.sh`); Chrome headless chạy WebGL
phần mềm (SwiftShader, `chrome-root.sh`). Không tải CDN lúc render.

## 2. Mười hai phong cách (`styles/<id>/`, `engine: code`)

| # | Style pack | Look (+ hậu kỳ) | Engine | `hold` |
|---|---|---|---|---|
| 1 | `dat-nan-3d` | `clay-3d` | three | 2 |
| 2 | `hoat-hinh-phang` | `flat-toon` | canvas2d | 1 |
| 3 | `ban-ve-ky-thuat` | `blueprint` | canvas2d | 1 |
| 4 | `in-riso` | `flat-toon` + `riso` | canvas2d | 2 |
| 5 | `pixel-16bit` | `flat-toon` + `pixel-16` | canvas2d | 2 |
| 6 | `bong-muc` | `ink-silhouette` (máy quay thấp) | canvas2d | 1 |
| 7 | `ong-cao-su` | `rubber-hose` (nhún theo `bpm`) | canvas2d | 2 |
| 8 | `chu-ascii` | `flat-toon` + `ascii` | canvas2d | 1 |
| 9 | `bia-cat-dan` | `cardboard` | three | 2 |
| 10 | `low-poly-90` | `lowpoly-90s` | three | 1 |
| 11 | `sach-pop-up` | `popup-paper` (sách pop-up, bìa bật dậy `opts.rise`, đêm `opts.night`) | three | 1 |
| 12 | `thuy-mac-3d` | `ink-wash-3d` (dị thú và núi thủy mặc 3D, bảng màu `thuy-mac`) | three | 1 |

Hậu kỳ ghép được với mọi look (vd. `lowpoly-90s` + `riso`): style mới = chép `styles/_template-code/`. Xem tất cả:
`python3 tools/toon/toon.py lookbook` (miễn phí, ~2 phút bản nháp, ra `out/_lab/lookbook/lookbook.mp4` + `sheet.png`).

## 3. Khâu theo phương pháp `code`

| Khâu | Việc |
|---|---|
| 0 | người dùng chọn `method: code` và một style `engine: code` (cho xem lookbook); `budget.yaml`: `images: 0`, `video_seconds: 0` |
| 2 | `film-writer` viết `shots.csv` theo §4 (không `ai_motion`) |
| 3a | dị thú chính: cổng thiết kế sinh vật (`film-pipeline` mục 2.2): ảnh sách của chủ dự án → `ICONOGRAPHY.md` → 2–3 concept (Qwen-Image local ở phiên local, hoặc `toon.py turntable` nhiều spec thử, miễn phí) → **người dùng chọn** → `CHARACTER.md` `## Concept đã duyệt`. `status.py --gate G2` báo `[MISSING]` khi chưa duyệt |
| 3 | `film-art-director` viết `characters/<slug>/character.json` (nhân vật rig) hoặc spec dị thú (`creature.js`, theo concept đã duyệt) + `CHARACTER.md` mục **Thông số model** (§8, thay prompt lớp) và tham số bối cảnh `E-<slug>` (`env` của look) |
| 4 | đạo diễn chạy `toon.py turntable --character … --style … --out review/turntable-<slug>.png` (dị thú: `--creature characters/<slug>/character.json`, style mặc định `thuy-mac-3d`) và một clip shot mẫu → **G2** (`status.py --gate G2` kiểm `character.json`, turntable, chi phí 0) |
| 5–6 | bỏ qua (Nhật ký: `khâu 5–6 bỏ qua (method code)`) |
| 7–10 | `film-compositor`: `inline.py film.html --init --toon`, mỗi shot một hàng `SHOTS`, render như mọi tập |

## 4. `shots.csv` của tập `code`

- `layers`: `C-<nhân vật>` hoặc `M-<model>` (model 3D, đạo cụ), `E-<bối cảnh>`, `FX` hoặc `FX-<hiệu ứng>`, `T` (chữ
  trên hình). Không `L1–L4`/`P`.
- `code_motion`: id hành động trong `tools/compose/motions.json` có `engine: toon` (`walk-cycle`, `run-cycle`, `jump`,
  `turn`, `wave`, `cheer`, `point`, `bounce`, `look-at`, `blink`; thở là tự động, `breath` là rig lớp tranh; dị thú:
  `head-turn`, `tail-fan`, `wing-flap`, `fly`, `swim`), id máy quay (`orbit`, `dolly`, `crane`, `fly-through`) và id cảnh
  (`ink-reveal-3d`, `water-ripple`, `brush-write`).
  `check_episode.py` đọc thẳng `motions.json`: id mới đăng ký ở đó là hợp lệ ngay; id rig lớp tranh (`cloth`,
  `strip-warp`…) là WARN.
- `camera`: thêm `orbit`, `dolly`, `crane`, `track` (máy quay 3D thật) và id `engine: toon` của `toon/project.js`.
- Tập trên 99 shot: id `s001`… cho cả tập (CONVENTIONS §6).
- `ai_motion` trống (ERROR nếu có).

## 5. Dàn cảnh và luật

- **Chân không trượt.** Bước chân tính theo quãng đường, nên đổi tốc độ không làm trượt. Muốn đổi hướng: `turn` (chân
  đặt lại), không xoay cả thân trên một điểm.
- Một shot một hành động chính + một chuyển động máy. Nhân vật trong khung ≥ 25 % chiều cao khung (ASCII, pixel cần to
  hơn: ≥ 35 %).
- Mắt và miệng chỉ hiện khi mặt hướng về máy quay; quay lưng thì chỉ thấy dáng (đúng cho `bong-muc`).
- `bong-muc`: máy quay thấp (`render.camera` của pack) để dáng nổi trên trời; tay không che thân.
- `ong-cao-su`: `bounce` cùng BPM với nhạc (`render.opts.bpm`).
- `ban-ve-ky-thuat`: nét vẽ dần trong `opts.reveal` giây đầu shot; shot đầu tập dùng được làm "thiết kế" nhân vật.
- `sach-pop-up`: máy quay cao, ống dài (`render.camera` của pack); look tự rải bìa dày theo `env.density` và chừa dải
  trước đường đi nên không cây nào che nhân vật; đường đi chạy dọc trục x (z = 0): cho nhân vật đi ngang.
- `thuy-mac-3d`: dị thú vẽ bằng `ink-wash-3d` (cũng chạy được trong `clay-3d`, `lowpoly-90s`; look khác báo `toon: look … does
  not draw creatures`). Mỗi bàn chân chạm đất đứng yên tới khi nhấc (4 chân: sau trái – trước trái – sau phải – trước
  phải; 6 chân: kiềng ba chân; luôn ≥ 2 chân chạm đất khi đi). Bơi cần `env.water`; con thú bơi để lại vòng sóng. Cánh
  vỗ trong `TOON.WING_LIMITS` dù `amp` lớn. Máy quay đặt cao hơn lưng con thú để thấy ba tầng núi; `follow` khi con thú đi xa.
- 3D (`clay-3d`, `lowpoly-90s`, `cardboard`, `popup-paper`, `ink-wash-3d`): cần three.js (`tools/doctor.sh` dòng `three`, bản đầy đủ thêm `webgl`).
  Tốc độ ở 1080p trong container: 2D 25–70 ms/khung, 3D 100–650 ms/khung (cardboard chậm nhất).

## 6. Mẫu FILM section

`inline.py <film>/film.html --init --toon` đặt `templates/toon-film-section.js` vào film.html: `CHARS` (character.json),
`STYLE` (khối `render` của style pack), `SHOTS` (timeline + camera mỗi shot), `loadToon()` nối vào READY, mỗi hàm shot
gọi `TOON.render(g, S.W, S.H, sceneOf('s01'), t - from)`. Thời gian trong timeline tính từ đầu shot. Cảnh báo của bộ
TOON đi vào danh sách `qc` của READY (`toon: …`). Dị thú: phần tử của `cast` là `{ creature: <spec>, timeline }` thay cho
`{ character, timeline }` (spec chép vào `CHARS`). Chữ bút lông: `write: [{ text, t: [a, b], x, y, size }]` trong scene của
shot (font CJK của container, `type.cjk` của style).

## 7. Kiểm trước G3 (thêm vào danh sách chung)

- [ ] `check_episode.py` sạch; `status.py` FORECAST: 0 ảnh, 0 giây.
- [ ] Nhân vật đúng `character.json` đã khóa ở G2 (cùng tỉ lệ, màu, seed).
- [ ] Không shot nào chân trượt, xuyên đất, tay xuyên thân.
- [ ] `make.py final` báo `deterministic: yes`.

## 8. Thông số model (dị thú, `tools/toon/creature.js`)

Mục **Thông số model** của `CHARACTER.md` (thay mục prompt và ảnh khóa) chép spec JSON của con thú và giải thích từng
nhóm bằng lời. Spec nằm ở `characters/<slug>/character.json` (dữ liệu dự án, trên Drive), con thú vào shot bằng
`cast: [{ creature: <spec>, timeline }]`. Mọi khóa đều tuỳ chọn (mặc định: `TOON.CREATURE_DEFAULTS`); độ dài tính bằng
đơn vị thế giới (mặt đất y = 0, linh vật `giot` cao 1.0), `scale` nhân tất cả.

| Nhóm | Khóa | Ý nghĩa |
|---|---|---|
| chung | `id`, `name`, `seed`, `scale` | seed quyết định pha đuôi, chớp mắt, đốm vằn |
| `body` | `length`, `radius`, `flat` (rộng/cao), `belly`, `arch`, `pitch` (rad, nâng ngực: thú đứng hai chân), `rump`, `waist`, `chest`, `wave` | thân loft theo spline: đuôi thân → eo → ngực → cổ → đầu → mõm liền một khối |
| `neck` | `length`, `radius`, `rise` (rad) | cổ nhận một nửa góc quay đầu |
| `head` | `length`, `radius`, `pitch`, `snout` (bán kính mõm / đầu) | |
| `legs` | `pairs` (0–3 → 0, 2, 4, 6 chân), `length`, `radius`, `foot`, `at` (vị trí hông 0 đuôi – 1 ngực), `splay` | IK hai đoạn, đùi to dần; `wave` của thân bị giới hạn để chân luôn với tới |
| `tails` | `count` (0–9), `length`, `radius`, `segments`, `spread`, `droop`, `curl`, `sway`, `lag` (giây mỗi đốt), `freq`, `tip` (búp lông ở ngọn) | đốt k lặp lại đốt 0 trễ k × `lag` |
| `wings` | `pairs` (0/1), `span`, `chord`, `feathers`, `at`, `fold` (1 = xếp khi đứng) | ba xương, lông chính + lông phủ |
| `horns` / `ears` / `mane` | `count`, `length`, `radius`, `sweep`, `curl`, `branch` (nhánh sừng) | |
| `eyes` | `count` (1–3), `radius` | mắt thứ ba ở trán |
| `pattern` | `kind`: `none` / `stripes` / `spots`, `scale` | |
| `palette` | `body` (độ đậm mực thân lấy từ độ sáng màu này), `ink`, `accent`, `eye` | `eye` = điểm son duy nhất |
| `demo` | `seconds`, `timeline`, `camera`, `turntable`, `env` | chỉ cho `toon.py` xem thử |

Tỉ lệ để duyệt ở G2: thân : cổ : đầu, chiều dài chân so với chiều cao hông (`0.88 × legs.length`), số chi, bảng màu mực,
seed. Đổi một trong các số này sau G2 = con thú mới (turntable lại).
