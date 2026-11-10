---
name: film-compose-shot
description: >-
  Dựng shot và bản dựng tập phim AI từ các lớp tranh Seedream bằng ghép 2.5D trong cinecode Quick mode: parallax theo
  độ sâu, máy quay tiến về chủ thể, rung nhẹ, sương cuộn, tàn lửa, quầng sáng, đuôi/tóc/vạt áo đung đưa, mắt nhắm mở,
  thở; clip Seedance đã tách nền cho cử động lớn; âm thanh; render stills → draft → final; gói và lưu Drive. Dùng khi
  người dùng nói "dựng shot", "ghép lớp", "ghép tranh", "parallax", "làm sống tranh", "cho con thú cử động",
  "render tập", "bản nháp tập", "compose shot", hoặc khi tập đã có lớp tranh duyệt trong out/<series>/ep<NN>/plates/.
---

# film-compose-shot

Biến các lớp tranh đã duyệt (L1 nền, L2 tầng giữa, L3 tiền cảnh, L4 nhân vật, P bộ phận) thành shot chuyển động,
rồi thành bản dựng của cả tập, bằng **cinecode Quick mode** + bộ mã dùng chung `tools/compose/`.

**Nguyên tắc:** tranh AI lo chất liệu; code lo máy quay, không khí, thời gian, âm thanh; Seedance chỉ cho cử động code
không làm được (quay đầu, đứng dậy, vỗ cánh). **Không vẽ nhân vật hay dị thú bằng nét code** (đã thử: luôn phẳng và giả).

Quy ước chung: `docs/CONVENTIONS.md` (tên file §2, `shots.csv` §6, ngân sách và ledger §7, lưu trữ §9).
API bộ ghép: `references/compose-api.md`. Clip Seedance thành lớp: `references/seedance-layer.md`.

## 0. Trước khi dựng (miễn phí)

- Đầu vào: `series/<series>/ep<NN>-<slug>/{EPISODE.md, shots.csv, anchors.json}`, lớp tranh đã duyệt trong
  `out/<series>/ep<NN>/plates/`, `styles/<id>/{style.yaml, motion.md, sound.md}`.
- Mỗi `code_motion` trong `shots.csv` phải là id có trong `tools/compose/motions.json` (`mist-bands`, `embers`,
  `sun-glow`, `strip-warp`, `eyelid`, `breath`, `parallax`, `push-in`) và có trong `style.yaml` `motion:`.
- `strip-warp`, `eyelid`, `breath`, `push-in` cần điểm neo trong `anchors.json` (`tools/layers/anchors.py set`; hộp =
  cặp điểm `<tên>_tl`/`<tên>_br`; chi tiết `references/compose-api.md` §2).
- Kiểm tra bộ mã: `python3 tools/compose/inline.py --lint`.
- Chrome trong container chạy bằng root cần `--no-sandbox`:
  `export CHROME_PATH=$FILM_LAB/tools/compose/chrome-root.sh` (nếu hook chưa đặt). Thiếu biến này `make.py` báo
  `Chrome did not start ... Running as root without --no-sandbox`.

## 1. Khởi tạo phim của tập

Nạp skill `cinecode` bằng Skill tool trước (để guard của nó chạy), rồi:

```bash
mkdir -p out/<series>/ep<NN>/film && cd out/<series>/ep<NN>/film
python3 ~/.claude/skills/cinecode/scripts/init_film.py <slug> --quick --title "<Tên tập>"
cd <slug>
python3 $FILM_LAB/tools/compose/inline.py film.html --init --anchors $FILM_LAB/series/<series>/ep<NN>-<slug>/anchors.json
```

- Một tập = một phim cinecode (`out/<series>/ep<NN>/film/<slug>/film.html`), mỗi shot = một dòng `SCENES`.
  Lớp tranh được tham chiếu tương đối: `'../../plates/<file>'`.
- `inline.py --init` làm một lần trên film.html mới: chèn bộ mã (một khối `<script>` giữa hai dấu `compose-kit`,
  không sửa tay), đổi kích thước mặc định 1080x1920 → **1920x1080**, nối `loadPlates` vào `window.READY`, thay các cảnh
  mẫu bằng `templates/plates-film-section.js`, thêm look `plates` và điền dòng Format của `STATE.md`
  (`<giây> s, 16:9, 1920x1080, 24 fps`; `make.py` đọc dòng này). Sau mỗi lần sửa `tools/compose/` hoặc
  `anchors.json`: chạy lại `inline.py film.html --anchors ...` (không `--init`).
- Ngay sau đó: `DURATION` = `length_s` của `EPISODE.md`, `TITLE`, và sửa số giây trên dòng Format của `STATE.md` cho
  khớp; thay `PLATES`, `CUES`, hàm shot và `SCENES` mẫu bằng của tập (template chạy được nguyên trạng chỉ trên lớp thử).
- Định dạng lưu của cinecode: hook đặt `CINECODE_FORMATS=<repo>/formats` (CONVENTIONS §9). Sau bản final đầu tiên
  người dùng ưng: `python3 tools/formats.py save "film-lab-<style-id>" ...` (cinecode hỏi trước). Tập sau:
  `init_film.py <slug> --quick --format film-lab-<style-id>`, **rồi vẫn chạy `inline.py --init`**: format chỉ mang
  ngôn ngữ (`FORMAT.md`), film.html luôn là template mới.
- `film.html` nằm trong `out/` (git bỏ qua): nó là mã nguồn của tập, phải đi vào gói Drive (§7).

## 2. Ghép 2.5D

Sửa phần FILM của film.html (chỉ phần đó; mỗi lần một shot). Bảng `PLATES` (một dòng mỗi lớp), `ATMOS` (màu từ
`style.yaml palette`), `CUES`, một hàm mỗi shot, `SCENES`, `SFX`.

**Độ sâu** (`COMPOSE.DEPTH`):

| Lớp | depth | Ghi chú |
|---|---|---|
| L1 nền, mặt trời | 0.10–0.15 | phủ kín khung, `overscan` 1.02–1.05 |
| L2 tầng giữa | 0.40–0.50 | |
| L3 tiền cảnh, L4 nhân vật, P | 1.0 | L4 đặt bằng `place: { x, y, h, pivot: 'feet' }` |
| sương trước | 1.25 | |
| hạt gần (tàn lửa, bụi) | 1.7 | ít, to, mờ |

**Thứ tự vẽ (xa → gần):** L1 → `sun-glow` → dải sương sau → L2 → dải sương giữa → L4 (+P) → tàn lửa → L3 →
sương trước → hạt gần → sương mở khung (`COMPOSE.mist.open`, luôn cuối). Chữ trên hình (`text()`, `label()` của
cinecode) vẽ sau `COMPOSE.stage`.

**Máy quay** (`COMPOSE.camera`):
- Tiến về chủ thể: `toward: COMPOSE.anchor('L4', 'subject')`, `zoom: [1, 1.06–1.12]`, `center` ≤ 0.35. Đừng lia
  ra xa hay đẩy lệch làm cắt đầu/đuôi; ảnh L1 không đủ lớn thì console báo `shows its edge` (bộ mã tự zoom thêm
  liên tục cho khỏi lộ mép): tăng `overscan` hoặc giảm chuyển động.
- Rung: `shake: { amp: 1.5–3, freq: 0.5–0.7, roll: ≤ 0.1 }` (noise có seed, không ngẫu nhiên thật).
- Một cú đẩy nhỏ ở sự kiện chính: `events: [{ at: CUES.<sự kiện>, zoom: 0.02–0.04, dur: 0.5, kick: 2–3 }]`.
- Shot đầu: `ease: 'out'` (nhanh nhất ở khung 0: luật hook của cinecode); các shot sau `inOut`. Hai shot liền nhau
  không trùng cả `shot_size` lẫn `camera` (CONVENTIONS §6).

**Không khí:** dải sương ở 2–3 độ sâu, **ngược chiều nhau** (`speed` âm/dương); tàn lửa blend `lighter`; quầng
sáng `screen`; sương mở khung 2 s đầu (khung 0 đã thấy cảnh qua khe sương: không bao giờ mở từ trắng hay đen).
Số liệu preset (tốc độ, alpha, số hạt, biên độ) lấy từ `styles/<id>/motion.md`; thiếu thì dùng số của template.

**Tất định (bắt buộc):** mọi thứ là hàm của `(t, SEED)`: không `Math.random`, `Date`, `performance.now`, không giữ
trạng thái giữa các khung (`inline.py` từ chối). Ảnh hay texture mới phải nạp trong `loadPlates` (trước READY).
Kiểm: `node tools/capture.mjs --url film.html --verify --params "w=1920&h=1080"` → phải in `deterministic: yes`.

## 3. Cử động trong một ảnh phẳng (rig của lớp)

Khai trong `PLATES.<id>.rig`, chỉnh theo shot bằng tham số của `st.plate(id, {...})` (chi tiết: `compose-api.md` §4):
- **strip-warp** (đuôi, tóc, vạt áo): vùng = hộp neo; dải 4 px (px sân khấu) lệch theo sóng chạy từ gốc ra ngọn,
  biên độ tăng về ngọn (`amp` 15–35 px ảnh, `speed` 0.3–0.6 vòng/s). Hộp chỉ chứa phần được cử động và nền trong suốt
  quanh nó; gốc nối vào thân với độ lệch 0 nên không có đường nối.
- **eyelid** (mắt nhắm/mở, kể cả mắt trên lưng): hộp neo của mắt; mảng da lấy ngay trên mắt trượt xuống làm mí.
  `blinks: [{ at, dur: 0.3 }]` hoặc `keys: [[t, 1], [t2, 0]]` (mắt mở dần một lần).
- **breath**: phóng dọc 0,8 % quanh chân (`pivot: 'feet'`), chu kỳ 3–4 s.

Trước khi chuyển sang clip Seedance trong cùng shot, đưa rig về nghỉ trong 0,5 s cuối
(`warp: { tail: { amp: 34 * (1 - COMPOSE.smooth((t - T + 0.5) / 0.5)) } }`), để cú chuyển không giật.

## 4. Clip Seedance (cử động lớn)

Chỉ khi shot cần cử động code không làm được; mỗi clip tính phí: theo `references/seedance-layer.md`. Tóm tắt:
khung đầu = nhân vật trên nền key phẳng đúng vị trí trên sân khấu 16:9 (`tools/compose/keyframe.py`, miễn phí) →
`ark.py video` model `dreamina-seedance-2-5-260628`, 720p 5 s (~2,5 phút, chạy nền), `--ratio 16:9`, `--no-audio`
khi âm thanh do code làm, `--ledger`/`--budget` và `FILM_AGENT` → tách nền từng khung bằng
`tools/layers/matte.py chroma` có khử loang màu (despill; `rembg` chỉ để dự phòng: viền nhấp nháy) → chuỗi PNG
`out/<series>/ep<NN>/clips/<tên-clip>/000001.png` → lớp `seq` trong `PLATES`. Request 502 không tự thử lại.

## 5. Âm thanh

- Theo `styles/<id>/sound.md` (thang âm, nhạc cụ) và cinecode `references/sound.md` §5: gió (ambience của từng
  shot), tiếng tàn lửa, whoosh trầm khi sương dâng (tối đa 2 whoosh/riser mỗi 30 s), khoảng lặng trước sự kiện, tiếng
  kéo trầm, cồng ở tiêu đề. Hiệu ứng vật lý dùng bản thu (`tools/sounds.py search|get`, `asset_search.py search
  --type sound`, mỗi file một dòng `LICENSES.csv`) đặt trên bus `sfx`/`ambience` của `audio/mix.json`; code chỉ cho
  âm theo chuyển động hay rơi đúng điểm cắt. Không đủ thì `make.py` giữ bản nháp (`SOUND THIN`, `SOUND ALL CODE`).
- Liệt kê mọi sự kiện trên hình trong `review/sound-audit.md` của thư mục phim (`make.py` đọc file này): bảng
  thời điểm · sự kiện · âm · bus, và dòng `events N · sounded M · silent by choice K`. Chép bản chữ sang
  `series/<series>/ep<NN>-<slug>/review/sound-audit.md` (git).
- **Nhạc luôn do người dùng chọn** (câu hỏi của cinecode: bản thu giấy phép mở ★ · nhạc của họ · code · không), ghi
  vào dòng `Music:` của `STATE.md` kèm `(user)`. Không tự viết `score()` khi họ chưa chọn code.
- Âm thanh được đo, không nghe: mỗi lần giao bản nháp nhờ người dùng nghe, nêu các giây quan trọng.

## 6. Render và giao

1. `python3 tools/make.py stills --at <các giây chính>` → tự xem (Read ảnh `review/stills-N.jpg`) rồi gửi người
   dùng. Kiểm: đủ lớp, sương, parallax (so khung đầu và cuối: nền gần như đứng yên, tiền cảnh/nhân vật lớn dần),
   chủ thể không bị mép cắt, mắt/đuôi đúng thời điểm.
2. `python3 tools/make.py draft` (960x540, đủ âm, chạy nền với `run_in_background`, rồi `make.py wait`). Đo trên
   container cloud (CPU, 2 worker): ~10 khung/s ở 1080p, nhanh hơn ở 960x540; 8 s phim ≈ 20 s render + kiểm.
   Phim 60 s ≈ 2–3 phút.
3. Sau khi người dùng duyệt bản nháp: `python3 tools/make.py final` (kiểm tất định, 1920x1080, master −14 LUFS).
4. Chép bản dựng sang tên chuẩn: `out/<series>/ep<NN>/renders/ep<NN>_draft_v<NN>.mp4` /
   `ep<NN>_final_v<NN>.mp4` (phiên bản luôn tăng, không ghi đè); ghi `EPISODE.md` Nhật ký.

**"TOO STILL":** `make.py` đo phần thay đổi còn lại sau khi trừ chuyển động máy quay (ngưỡng 1,0 mức xám, mẫu 4
khung/s, ảnh thu nhỏ). Cử động nhỏ trên lớp tranh nhạt màu gần như không lọt ngưỡng: shot thử 8 s qua được ở 2 s
đầu (sương mở khung) nhưng sau đó chỉ đo được 0,2–0,45, và tăng gấp đôi đuôi, sương, tàn lửa cũng chỉ 0,5–0,8. Vì
vậy một shot chỉ có lớp tranh giữ khung dài sẽ bị báo. Cách xử lý trong phim thật: cắt shot ngắn lại (3–5 s), thêm một hành động thật (clip Seedance, một vật
lớn đi ngang khung, sương trước dày quét qua chủ thể), hoặc ghi vào `STATE.md` là cố ý (khoảng lặng trước sự kiện)
và nói với người dùng trong một dòng. `make.py` chỉ giữ một lượt sửa; bản sau được giao kèm điều còn lại.

## 7. Lưu trữ (CONVENTIONS §9)

- Gói mỗi shot: `python3 tools/bundle.py out/<series>/ep<NN> --shot s<NN>` → một zip (lớp tranh, clip mp4, dòng
  `prompts.csv`, điểm neo của shot) → người dùng duyệt tải lên Drive `AI Film Lab/<series>/ep<NN>/<YYYY-MM-DD>/`.
  Khung PNG đã tách nền không cần gói (tách lại miễn phí từ mp4).
- Phần chữ của phim nằm trong `out/` nên **không có trong git**, và `bundle.py` chưa gói nó. Sau mỗi bản nháp được
  duyệt, gói một zip riêng rồi tải lên cùng thư mục Drive (một lần duyệt):
  `cd out/<series>/ep<NN> && zip -r bundles/ep<NN>_film_<YYYYMMDD>.zip film/<slug>/film.html film/<slug>/STATE.md film/<slug>/LICENSES.csv film/<slug>/review/*.md film/<slug>/notes film/<slug>/audio/mix.json`
  (bỏ những mục chưa có).
- Bản dựng duyệt (`renders/*.mp4`) tải riêng từng file.
- Container bị thu hồi khi phiên rảnh: thay đổi trong `tools/compose/` hay skill phải commit + push trước khi dừng.

## 8. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `deterministic: NO` | ảnh nạp muộn, `Math.random`/`Date`, trạng thái giữa khung | nạp trong `loadPlates`; chỉ dùng `COMPOSE.rng/noise`, `rng()` của cinecode; `inline.py` để kiểm |
| `Chrome did not start ... --no-sandbox` | container chạy bằng root | `CHROME_PATH=$FILM_LAB/tools/compose/chrome-root.sh` |
| `page threw while loading ... plate L4: could not load` | sai đường dẫn tương đối | đường dẫn tính từ film.html: `../../plates/<file>` |
| console `shows its edge` | L1 không đủ lớn cho chuyển động | tăng `overscan`, giảm `zoom`/`pan`, hoặc ảnh L1 lớn hơn |
| vạch dọc trên đuôi | hộp warp chứa cả phần thân xa gốc | thu hộp lại, đặt `tail_root` đúng chỗ nối |
| `cliché: lens flare` | chữ "flare" trong phần FILM | đừng dùng từ đó trong mã/ghi chú của FILM, hoặc ghi lý do trên director card |
| `anchors ... scaled` | `anchors.json` đo trên ảnh khác cỡ | cập nhật `size` hoặc đo lại trên ảnh đã duyệt |

Thử nhanh bộ mã không tốn phí: `python3 tools/compose/demo_plates.py out/demo`, khởi tạo một phim Quick trong
`out/demo/film/`, `inline.py --init --anchors out/demo/anchors.json`; template chạy nguyên trạng trên lớp thử.
