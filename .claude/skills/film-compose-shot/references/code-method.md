# Phương pháp `code`: nhân vật và cảnh vẽ hoàn toàn bằng code (bộ TOON)

Đọc file này khi `EPISODE.md` của tập ghi `method: code`. Không gọi model tạo ảnh hay video nào: `budget.yaml` có
`images: 0` và `video_seconds: 0`; không `prompts.csv`, không `plates/`, không khâu 5–6. Nguồn: #38 (bộ 10 phong cách),
#39–#43; gộp `code3d` của #35.

## 1. Bộ TOON (`tools/toon/`)

| File | Làm gì |
|---|---|
| `rig.js` | nhân vật = dữ liệu (`character.json`): thân `drop` / `blob` / `box`, 1 hoặc 2 mắt, chỏm tóc, tay chân ống; khung xương, IK hai đoạn |
| `motion.js` | timeline hành động → tư thế tại `t`: `walk`, `run`, `turn`, `jump`, `wave`, `cheer`, `point`, `bounce`, `look`, `blink`, `idle`; chớp mắt và thở tự động |
| `project.js` | máy quay (`pos`, `target`, `fov`, `move`, `follow`, `shake`), phép chiếu, danh sách hình 2D, đạo cụ cảnh theo seed (đồi, cây, đá, mây) |
| `look2d.js` | look canvas: `flat-toon`, `ink-silhouette`, `rubber-hose`, `blueprint` |
| `look3d.js` | look three.js: `clay-3d`, `lowpoly-90s`, `cardboard` |
| `post.js` | hậu kỳ áp lên mọi khung: `riso`, `pixel-16`, `ascii` |
| `toon.js` | `TOON.ready(scene)`, `TOON.render(g, W, H, scene, t)` |
| `looks.json` | sổ đăng ký look và hậu kỳ (khớp `TOON.LOOKS` / `TOON.POSTS`) |
| `toon.py` | xem thử miễn phí: `still`, `turntable`, `clip`, `lookbook`, `reel` |
| `demo/giot.json` | linh vật của lab, "Giọt" |

Mọi khung là hàm thuần của `(scene, t)`: không `Math.random`, `Date`, `performance.now` (`inline.py` từ chối). three.js
ghim cục bộ (`tools/toon/three.lock`, `FILM_THREE`, cài bằng `tools/toon/install_three.sh`); Chrome headless chạy WebGL
phần mềm (SwiftShader, `chrome-root.sh`). Không tải CDN lúc render.

## 2. Mười phong cách (`styles/<id>/`, `engine: code`)

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

Hậu kỳ ghép được với mọi look (vd. `lowpoly-90s` + `riso`): style mới = chép `styles/_template-code/`. Xem tất cả:
`python3 tools/toon/toon.py lookbook` (miễn phí, ~2 phút bản nháp, ra `out/_lab/lookbook/lookbook.mp4` + `sheet.png`).

## 3. Khâu theo phương pháp `code`

| Khâu | Việc |
|---|---|
| 0 | người dùng chọn `method: code` và một style `engine: code` (cho xem lookbook); `budget.yaml`: `images: 0`, `video_seconds: 0` |
| 2 | `film-writer` viết `shots.csv` theo §4 (không `ai_motion`) |
| 3 | `film-art-director` viết `characters/<slug>/character.json` + `CHARACTER.md` mục **Thông số model** (thay prompt lớp) và tham số bối cảnh `E-<slug>` (`env` của `project.js`) |
| 4 | đạo diễn chạy `toon.py turntable --character … --style … --out review/turntable-<slug>.png` và một clip shot mẫu → **G2** (`status.py --gate G2` kiểm `character.json`, turntable, chi phí 0) |
| 5–6 | bỏ qua (Nhật ký: `khâu 5–6 bỏ qua (method code)`) |
| 7–10 | `film-compositor`: `inline.py film.html --init --toon`, mỗi shot một hàng `SHOTS`, render như mọi tập |

## 4. `shots.csv` của tập `code`

- `layers`: `C-<nhân vật>`, `E-<bối cảnh>`, `FX` hoặc `FX-<hiệu ứng>`, `T` (chữ trên hình). Không `L1–L4`/`P`.
- `code_motion`: id hành động trong `tools/compose/motions.json` có `engine: toon` (`walk-cycle`, `run-cycle`, `jump`,
  `turn`, `wave`, `cheer`, `point`, `bounce`, `look-at`, `blink`, `breath`) và id máy quay (`orbit`, `dolly`, `crane`).
- `camera`: thêm `orbit`, `dolly`, `crane`, `track` (máy quay 3D thật).
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
- 3D (`clay-3d`, `lowpoly-90s`, `cardboard`): cần three.js (`tools/doctor.sh` dòng `three`, bản đầy đủ thêm `webgl`).
  Tốc độ ở 1080p trong container: 2D 25–70 ms/khung, 3D 100–650 ms/khung (cardboard chậm nhất).

## 6. Mẫu FILM section

`inline.py <film>/film.html --init --toon` đặt `templates/toon-film-section.js` vào film.html: `CHARS` (character.json),
`STYLE` (khối `render` của style pack), `SHOTS` (timeline + camera mỗi shot), `loadToon()` nối vào READY, mỗi hàm shot
gọi `TOON.render(g, S.W, S.H, sceneOf('s01'), t - from)`. Thời gian trong timeline tính từ đầu shot. Cảnh báo của bộ
TOON đi vào danh sách `qc` của READY (`toon: …`).

## 7. Kiểm trước G3 (thêm vào danh sách chung)

- [ ] `check_episode.py` sạch; `status.py` FORECAST: 0 ảnh, 0 giây.
- [ ] Nhân vật đúng `character.json` đã khóa ở G2 (cùng tỉ lệ, màu, seed).
- [ ] Không shot nào chân trượt, xuyên đất, tay xuyên thân.
- [ ] `make.py final` báo `deterministic: yes`.
