---
name: film-compose-shot
description: >-
  Dựng shot và bản dựng tập phim AI từ các lớp tranh Seedream bằng ghép 2.5D trong cinecode Quick mode: parallax theo
  độ sâu, máy quay tiến về chủ thể, rung nhẹ, sương cuộn, tàn lửa, quầng sáng, đuôi/tóc/vạt áo đung đưa, mắt nhắm mở,
  thở; clip Seedance đã tách nền cho cử động lớn; âm thanh; render stills → draft → final; gói và lưu Drive. Dùng khi
  người dùng nói "dựng shot", "ghép lớp", "ghép tranh", "parallax", "làm sống tranh", "cho con thú cử động",
  "render tập", "bản nháp tập", "compose shot", hoặc khi tập đã có lớp tranh duyệt trong out/<project>/ep<NN>/plates/ hoặc out/<project>/q<NN>t<NN>/plates/.
---

# film-compose-shot

**Mã tập (`docs/CONVENTIONS.md` §2):** ví dụ dưới đây viết `ep<NN>` (dự án không chia quyển: thư mục `ep01-<slug>`, media `out/<project>/ep01/`, file `ep01_s03_...`). Dự án chia quyển dùng `q<NN>t<NN>`: thư mục tập `q01-t01-<slug>`, media `out/<project>/q01t01/`, file `q01t01_s03_L4_bac-di_v02.png`, clip `q01t01_s03_seedance25_v01.mp4`, bản dựng `q01t01_draft_v01.mp4`. Đọc mã tập từ `EPISODE.md` (`book` + `episode`) / tên thư mục tập, không tự đổi.

Biến các lớp tranh đã duyệt (L1 nền, L2 tầng giữa, L3 tiền cảnh, L4 nhân vật, P bộ phận) thành shot chuyển động,
rồi thành bản dựng của cả tập, bằng **cinecode Quick mode** + bộ mã dùng chung `tools/compose/`.

**Nguyên tắc:** tranh AI lo chất liệu; code lo máy quay, không khí, thời gian, âm thanh; Seedance chỉ cho cử động code
không làm được (quay đầu, đứng dậy, vỗ cánh). **Không vẽ nhân vật hay dị thú bằng nét code** (đã thử: luôn phẳng và giả);
ngoại lệ duy nhất: người nhỏ ≤ 25 % khung trong cảnh rộng bằng `figure` (`references/layers-figure.md`).

Quy ước chung: `docs/CONVENTIONS.md` (tên file §2, `shots.csv` §6, ngân sách và ledger §7, lưu trữ §9).
API bộ ghép: `references/compose-api.md`. Clip Seedance thành lớp: `references/seedance-layer.md`.

**Bốn phương pháp dựng: rẽ nhánh theo `method` của `EPISODE.md` trước khi dựng shot đầu tiên.** `method: code` (nhân vật
và cảnh vẽ hoàn toàn bằng code, không lớp tranh): đọc `references/code-method.md` thay cho mọi mục về plates của file này;
khởi tạo bằng `python3 tools/compose/inline.py <film>/film.html --init --toon`. `method: blender` (model 3D render bằng
Blender, không lớp tranh): đọc `references/blender-method.md`; render `renders3d/s<NN>/beauty/` (chuỗi PNG) hoặc
`beauty.mp4` dùng như một clip cả khung, compose kit chỉ phủ sương, nắng, chữ. Clip H3 local (`video_engine: comfy`):
`references/local-video.md` (âm thanh tự sinh của clip mặc định tắt dưới lời bình).

| `method` | Cử động lớn của nhân vật | Đọc | Bỏ qua |
|---|---|---|---|
| `layers` | code: `pose-cycle` (đổi bậc 2–4 plate tư thế), `cloth`, `strip-warp`, `foliage`; không khí `smoke`, `fire`, `embers`, `mist-bands`; máy quay | `references/layers-method.md` (quy tắc dàn cảnh, bảng tra, danh sách kiểm trước G3), `references/layers-character.md` | mục 4 của file này và `references/seedance-layer.md`: **không bao giờ yêu cầu clip**, không `keyframe.py`, không `matte_seq.py`, không lớp `seq` |
| `seedance` (hoặc không có khóa) | clip Seedance đã tách nền (mục 4) | `references/seedance-layer.md` | plate tư thế `L4b`… và `pose-cycle` (khóa `L4b: { seq: … }` trong `PLATES` của `seedance-layer.md` là lớp clip, không phải plate tư thế) |

Một tập một nhánh. Với `layers`, shot thiếu chuyển động thì thêm chuyển động code hoặc cắt ngắn, và báo đạo diễn khi
`shots.csv` đòi thứ `layers` không làm được (nước chảy, bay lượn); không tự chuyển sang clip.

## 0. Trước khi dựng (miễn phí)

- Đầu vào: `projects/<project>/ep<NN>-<slug>/{EPISODE.md, shots.csv, anchors.json}`, lớp tranh đã duyệt trong
  `out/<project>/ep<NN>/plates/`, `styles/<id>/{style.yaml, motion.md, sound.md}`.
- Mỗi `code_motion` trong `shots.csv` phải là một id của `tools/compose/motions.json` **không** ghi `"engine": "toon"`
  (id `toon` chỉ cho `method: code`) **và** có trong `style.yaml` `motion:`. Đó là: `mist-bands`, `embers`, `sun-glow`,
  `smoke`, `fire`, `foliage`, `strip-warp`, `cloth`, `pose-cycle`, `figure`, `eyelid`, `breath`, `parallax`, `push-in`.
  Mọi id là code nên dùng được cho cả `layers` lẫn `seedance`, trừ `pose-cycle` và `figure`: chỉ `method: layers`.
- `cloth` và `foliage` cần hộp neo, `pose-cycle` cần các plate tư thế ghi ở cột `layers` (`L4b`, `L4c`…) và điểm neo
  chân chung. Người nhỏ trong cảnh rộng (≤ 25 % khung): `figure`, vẽ bằng code, không cần plate
  (`references/layers-figure.md`); chỉ cần một điểm neo cho bàn chân nếu đứng trên plate. Với `layers`, shot nào có
  `ai_motion` là lỗi của `shots.csv`: báo đạo diễn.
- `strip-warp`, `eyelid`, `breath`, `push-in` cần điểm neo trong `anchors.json` (`tools/layers/anchors.py set`; hộp =
  cặp điểm `<tên>_tl`/`<tên>_br`; chi tiết `references/compose-api.md` §2).
- Kiểm tra bộ mã: `python3 $FILM_LAB/tools/compose/inline.py --lint`.
- **Đường dẫn và thư mục làm việc.** `$FILM_LAB` = gốc repo (hook đặt sẵn). Đặt một lần mỗi phiên
  `FILM=$FILM_LAB/out/<project>/ep<NN>/film/<slug>` (thư mục phim cinecode). Lệnh `tools/make.py`, `tools/capture.mjs`
  là của cinecode, nằm trong thư mục phim: chạy với `cd "$FILM"`. Lệnh của lab (`inline.py`, `bundle.py`,
  `anchors.py`, `score.py`) luôn ghi đường dẫn đầy đủ `$FILM_LAB/...` và đối số tuyệt đối, nên chạy từ đâu cũng được.
- Chrome trong container chạy bằng root cần `--no-sandbox`:
  `export CHROME_PATH=$FILM_LAB/tools/compose/chrome-root.sh` (nếu hook chưa đặt). Thiếu biến này `make.py` báo
  `Chrome did not start ... Running as root without --no-sandbox`.

## 1. Khởi tạo phim của tập

Nạp skill `cinecode` bằng Skill tool trước (để guard của nó chạy), rồi:

```bash
mkdir -p $FILM_LAB/out/<project>/ep<NN>/film && cd $FILM_LAB/out/<project>/ep<NN>/film
python3 ~/.claude/skills/cinecode/scripts/init_film.py <slug> --quick --title "<Tên tập>"
FILM=$FILM_LAB/out/<project>/ep<NN>/film/<slug>
python3 $FILM_LAB/tools/compose/inline.py $FILM/film.html --init --anchors $FILM_LAB/projects/<project>/ep<NN>-<slug>/anchors.json
```

- Một tập = một phim cinecode (`out/<project>/ep<NN>/film/<slug>/film.html`), mỗi shot = một dòng `SCENES`.
  Lớp tranh được tham chiếu tương đối: `'../../plates/<file>'`; lớp có cách tách nền khác `none` (L2–L4, P, FX) dùng
  bản đã tách: `'../../plates/matte/<file>'`.
- `inline.py --init` làm một lần trên film.html mới: chèn bộ mã (một khối `<script>` giữa hai dấu `compose-kit`,
  không sửa tay), đổi kích thước mặc định 1080x1920 → **1920x1080**, nối `loadPlates` vào `window.READY`, thay các cảnh
  mẫu bằng `templates/plates-film-section.js`, thêm look `plates` và điền dòng Format của `STATE.md`
  (`<giây> s, 16:9, 1920x1080, 24 fps`; tỉ lệ theo `--size`; `make.py` đọc dòng này). Sau mỗi lần sửa
  `tools/compose/` hoặc `anchors.json`: chạy lại `python3 $FILM_LAB/tools/compose/inline.py $FILM/film.html` (không
  `--init`): nó tự đọc lại `anchors.json` đã ghi lần trước (đường dẫn lưu tương đối với film.html, chạy từ thư mục nào
  cũng tìm thấy). film.html CRLF vẫn giữ CRLF; file được ghi qua file tạm rồi đổi tên, không bao giờ ghi dở.
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
  ra xa hay đẩy lệch làm cắt đầu/đuôi; ảnh L1 không đủ lớn cho đường đi của máy quay thì bộ mã tự zoom thêm liên tục
  cho khỏi lộ mép và báo dòng `compose: plate L1 shows its edge` trong `qc` của `make.py`. Bắt sớm hơn bằng
  `inline.py --preflight` (mục 2a): nó in luôn `overscan` cần có. Lia cuộn tranh: `compose-api.md` §3.
- Rung: `shake: { amp: 1.5–3, freq: 0.5–0.7, roll: ≤ 0.1 }` (noise có seed, không ngẫu nhiên thật).
- Một cú đẩy nhỏ ở sự kiện chính: `events: [{ at: CUES.<sự kiện>, zoom: 0.02–0.04, dur: 0.5, kick: 2–3 }]`.
- Shot đầu: `ease: 'out'` (nhanh nhất ở khung 0: luật hook của cinecode); các shot sau `inOut`. Hai shot liền nhau
  không trùng cả `shot_size` lẫn `camera` (CONVENTIONS §6).

**Không khí:** dải sương ở 2–3 độ sâu, **ngược chiều nhau** (`speed` âm/dương); tàn lửa blend `lighter`; quầng
sáng `screen`; sương mở khung 2 s đầu (khung 0 đã thấy cảnh qua khe sương: không bao giờ mở từ trắng hay đen).
Số liệu preset (tốc độ, alpha, số hạt, biên độ) lấy từ `styles/<id>/motion.md`; thiếu thì dùng số của template.

**Tất định (bắt buộc):** mọi thứ là hàm của `(t, SEED)`: không `Math.random`, `Date`, `performance.now`, không giữ
trạng thái giữa các khung (`inline.py` từ chối). Ảnh hay texture mới phải nạp trong `loadPlates` (trước READY).
Kiểm (`cd "$FILM"`): `node tools/capture.mjs --url film.html --verify --params "w=1920&h=1080"` → phải in
`deterministic: yes`.

## 2a. Preflight trước mỗi lần render (miễn phí, node, không ghi gì)

```bash
python3 $FILM_LAB/tools/compose/inline.py $FILM/film.html --preflight
```

Chạy bộ mã đã chèn trong film.html với canvas giả, đọc cỡ từng file plate, vẽ mọi shot của `SCENES` ở 12 khung/giây
thời gian phim. `ERROR` (thoát 1, sửa trước khi `make.py stills`): khoá lạ trong `PLATES` (gõ sai), thiếu điểm/hộp neo
mà rig hay `place` cần, thiếu file plate hoặc khung `seq`, L1 lộ mép dưới chuyển động máy quay (kèm `overscan` cần
có), `figure` vượt 25 % khung, shot ném lỗi, cảnh báo của bộ mã làm khung khác với mã (rig đứng yên, giá trị bị chặn).
`WARN` (thoát 0, xem qua): khoá lạ trong tham số một lời gọi, số ngoài khoảng ghi trong `compose-api.md`, hình người
bị đẩy vào quá 25 % khung, film.html mang bộ mã cũ. Chi tiết: `compose-api.md` §9.

## 3. Cử động trong một ảnh phẳng (rig của lớp)

Khai trong `PLATES.<id>.rig`, chỉnh theo shot bằng tham số của `st.plate(id, {...})` (chi tiết: `compose-api.md` §4):
- **strip-warp** (đuôi, tóc, vạt áo): vùng = hộp neo; dải 4 px (px sân khấu) lệch theo sóng chạy từ gốc ra ngọn,
  biên độ tăng về ngọn. `amp` tính bằng px **ảnh** ở ngọn (mặc định 16): giữ ngọn lệch ≤ 2–3 % chiều dài bộ phận
  (`styles/<id>/motion.md`), vd. đuôi dài 1000 px ảnh → `amp` ≤ 20–30; `speed` 0.3–0.6 vòng/s. Hộp chỉ chứa phần được
  cử động và nền trong suốt quanh nó; gốc nối vào thân với độ lệch 0 nên không có đường nối.
- **eyelid** (mắt nhắm/mở, kể cả mắt trên lưng): hộp neo của mắt; mảng da lấy ngay trên mắt trượt xuống làm mí.
  `blinks: [{ at, dur: 0.3 }]` hoặc `keys: [[t, 1], [t2, 0]]` (mắt mở dần một lần).
- **breath**: phóng dọc 0,8 % quanh chân (`pivot: 'feet'`), chu kỳ 3–4 s.

Trước khi chuyển sang clip Seedance trong cùng shot (chỉ `method: seedance`), đưa rig về nghỉ trong 0,5 s cuối
(`warp: { tail: { amp: 34 * (1 - COMPOSE.smooth((t - T + 0.5) / 0.5)) } }`), để cú chuyển không giật.

## 3a. Phương pháp `layers`: cử động và không khí bằng code

`pose-cycle` chỉ khi `method: layers`; `cloth`, `foliage`, `smoke`, `fire` là code nên tập `seedance` cũng dùng được khi
style khai báo chúng. Chữ ký và tham số: `references/compose-api.md` (khói, lửa, tán cây),
`references/layers-character.md` (vải, tư thế); số liệu của style: `styles/<id>/motion.md`.
- **cloth** (rig `cloth` trên L4: áo choàng, tay áo, đai, tóc): sóng chạy từ mép dính vào thân ra mép tự do, mép dính
  đứng yên; mọi vùng vải của một shot chung một hướng gió, lệch pha.
- **pose-cycle** (rig `poses` trên L4): mỗi thời điểm vẽ đúng **một** plate tư thế, cắt thẳng trên lưới 8–12 fps, canh
  theo điểm neo chân; không nội suy vị trí hay góc xoay của thân. Dịch chuyển chậm của cả hình là việc của máy quay.
- **foliage** (rig `sway` trên vùng tán cây, bụi, cỏ của L2/L3): nghiêng nhẹ tăng theo chiều cao, gốc đứng yên. Theo
  shot: `st.plate('L2', { sway: false })` giữ yên mọi cây (đuôi `warp` cùng lớp vẫn động), `{ sway: { tan: {...} } }`.
- **smoke** (`COMPOSE.smoke.plume`): cột khói từ một điểm gốc có độ sâu; nhiều cột lệch pha. Vẽ sau lớp chứa nguồn khói.
- **fire** (`COMPOSE.fire.flames`, `COMPOSE.fire.glow`): lưỡi lửa blend `lighter` + ánh hắt lên lớp gần; đi cùng
  `embers`. Không bao giờ chớp cả khung.
- Mỗi shot giữ khung: ít nhất hai chuyển động độc lập cộng máy quay. Trước G3 chạy danh sách kiểm
  `references/layers-method.md` §5.

## 4. Clip Seedance (cử động lớn)

**Chỉ khi `method: seedance`** (hoặc `EPISODE.md` không có khóa `method`). Với `method: layers` bỏ qua cả mục này.

Chỉ khi shot cần cử động code không làm được; mỗi clip tính phí: theo `references/seedance-layer.md`. Tóm tắt:
khung đầu = nhân vật trên nền key phẳng đúng vị trí trên sân khấu 16:9 (`tools/compose/keyframe.py`, miễn phí) →
`ark.py video` model `dreamina-seedance-2-5-260628`, 720p 5 s (~2,5 phút, chạy nền), không `--ratio` (khung đầu 16:9 quyết định tỉ lệ), `--no-audio`
khi âm thanh do code làm, `--ledger`/`--budget` và `FILM_AGENT` → tách nền cả clip bằng một lệnh
`python3 tools/layers/matte_seq.py <clip>.mp4 --start-frame <khung đầu> --strict` (chroma + khử loang màu, in số đo
nhấp nháy và dòng `PLATES`; `--method rembg` chỉ để dự phòng: viền nhấp nháy) → chuỗi PNG
`out/<project>/ep<NN>/clips/<tên-clip>/000001.png` → lớp `seq` trong `PLATES`. Request 502 không tự thử lại.

## 5. Âm thanh

- Theo `styles/<id>/sound.md` (thang âm, nhạc cụ) và cinecode `references/sound.md` §5: gió (ambience của từng
  shot), tiếng tàn lửa, whoosh trầm khi sương dâng (tối đa 2 whoosh/riser mỗi 30 s), khoảng lặng trước sự kiện, tiếng
  kéo trầm, cồng ở tiêu đề. Hiệu ứng vật lý dùng bản thu (`tools/sounds.py search|get`, `asset_search.py search
  --type sound`, mỗi file một dòng `LICENSES.csv`) đặt trên bus `sfx`/`ambience` của `audio/mix.json`; code chỉ cho
  âm theo chuyển động hay rơi đúng điểm cắt. Không đủ thì `make.py` giữ bản nháp (`SOUND THIN`, `SOUND ALL CODE`).
- Liệt kê mọi sự kiện trên hình trong `review/sound-audit.md` của thư mục phim (`make.py` đọc file này): bảng
  thời điểm · sự kiện · âm · bus, và dòng `events N · sounded M · silent by choice K`. Chép bản chữ sang
  `projects/<project>/ep<NN>-<slug>/review/sound-audit.md` (đạo diễn đẩy lên Drive `03_KichBan/ep<NN>-<slug>/review/`).
- **Nhạc luôn do người dùng chọn** (câu hỏi của cinecode: bản thu giấy phép mở ★ · nhạc của họ · code · không), ghi
  vào dòng `Music:` của `STATE.md` kèm `(user)`. Không tự viết `score()` khi họ chưa chọn code.
- **Nhạc code và foley theo sự kiện: `tools/audio/score.py`** (local, miễn phí, không sample; `tools/audio/README.md`).
  Dùng khi người dùng đã chọn nhạc **code** (phần `music`: guqin/pipa/koto, cồng, trống khung, drone) và, với mọi lựa
  chọn nhạc, cho foley phải rơi đúng khung hình (phần `foley`: `hoof`, `brush_air`, `ink_drop`, `ember`, `whoosh`…
  theo bảng của `styles/<id>/sound.md`). Viết `projects/<project>/<tập>/score.json` (mẫu `templates/episode/score.json`;
  `t` = khung tiếp xúc / fps, `shot` = id shot, `silence` = khoảng lặng thật), chạy `--dry-run` cho tới khi hết ERROR,
  rồi `--out <media>/audio` (bản sau: `<media>/audio/v<NN>`, không ghi đè). Dán `mix-snippet.json` vào `audio/mix.json`:
  `music.wav` → bus `music`, `foley.wav` → bus `foley`, `ambience.wav` → bus `ambience`; `preview.wav` chỉ để nghe thô,
  không phải bản master. **Vẫn liệt kê mọi sự kiện** trong `review/sound-audit.md` (chép từ bảng cue của `--dry-run`) và
  ghi một dòng `LICENSES.csv` cho các stem (`tools/audio`, tự tổng hợp). Không có sáo/tiêu và không có sampler.
- Âm thanh được đo, không nghe: mỗi lần giao bản nháp nhờ người dùng nghe, nêu các giây quan trọng.
- Lời bình chỉ lấy từ các bản đọc của `tools/tts/vieneu_tts.py` trong `<media>/vo/` (do `film-narrator` render,
  `--check` đã đạt). **Không bao giờ** dùng `tools/tts.py` hay `keys.py` của cinecode: đường đó đi tìm khóa Gemini,
  trái quy tắc khóa của lab. Chưa có bản đọc thì giao bản nháp không lời bình và **báo rõ** cho đạo diễn, không tìm
  cách khác để có giọng.

## 6. Render và giao

0. `inline.py --preflight` (mục 2a) không còn `ERROR`.
1. `cd "$FILM"`, rồi `python3 tools/make.py stills --at <các giây chính>` (`tools/make.py` của cinecode, trong thư mục
   phim) → tự xem (Read ảnh `$FILM/review/stills-N.jpg`) rồi gửi người dùng. Kiểm: đủ lớp, sương, parallax (so khung đầu và cuối: nền gần như đứng yên, tiền cảnh/nhân vật lớn dần),
   chủ thể không bị mép cắt, mắt/đuôi đúng thời điểm.
2. `python3 tools/make.py draft` (960x540, đủ âm, chạy nền với `run_in_background`, rồi `make.py wait`). Đo trên
   container cloud (CPU, 2 worker): ~10 khung/s ở 1080p, nhanh hơn ở 960x540; 8 s phim ≈ 20 s render + kiểm.
   Phim 60 s ≈ 2–3 phút.
3. Sau khi người dùng duyệt bản nháp: `python3 tools/make.py final` (kiểm tất định, 1920x1080, master −14 LUFS).
4. Chép bản dựng sang tên chuẩn: `$FILM_LAB/out/<project>/ep<NN>/renders/ep<NN>_draft_v<NN>.mp4` /
   `ep<NN>_final_v<NN>.mp4` (phiên bản luôn tăng, không ghi đè); ghi `EPISODE.md` Nhật ký.

**"TOO STILL":** `make.py` đo phần thay đổi còn lại sau khi trừ chuyển động máy quay (ngưỡng 1,0 mức xám, mẫu 4
khung/s, ảnh thu nhỏ). Cử động nhỏ trên lớp tranh nhạt màu gần như không lọt ngưỡng: shot thử 8 s qua được ở 2 s
đầu (sương mở khung) nhưng sau đó chỉ đo được 0,2–0,45, và tăng gấp đôi đuôi, sương, tàn lửa cũng chỉ 0,5–0,8. Vì
vậy một shot chỉ có lớp tranh giữ khung dài sẽ bị báo. Cách xử lý trong phim thật: cắt shot ngắn lại (3–5 s), thêm một hành động thật (`method: seedance`: clip Seedance; `method: layers`: `pose-cycle`, `cloth`, khói hoặc lửa; cả hai: một vật
lớn đi ngang khung, sương trước dày quét qua chủ thể), hoặc ghi vào `STATE.md` là cố ý (khoảng lặng trước sự kiện)
và nói với người dùng trong một dòng. `make.py` chỉ giữ một lượt sửa; bản sau được giao kèm điều còn lại.

## 7. Lưu trữ (CONVENTIONS §9, §11)

- Gói mỗi shot: `python3 $FILM_LAB/tools/bundle.py $FILM_LAB/out/<project>/ep<NN> --shot s<NN>` → một zip (lớp tranh, clip mp4, dòng
  `prompts.csv`, điểm neo của shot) → người dùng duyệt tải lên Drive
  `ClaudeFilmLab/<ProjectName>/04_SanXuat/ep<NN>-<slug>/<YYYY-MM-DD>/` (đạo diễn tải; compositor không tải lên Drive).
  Khung PNG đã tách nền không cần gói (tách lại miễn phí từ mp4). Tập `blender`: gói có `renders3d/s<NN>*/beauty.mp4`
  + `render.json` (không chuỗi PNG, `references/blender-method.md` §3); khôi phục = giải nén gói trong
  `$FILM_LAB/out/<project>/ep<NN>/`.
- Phần chữ của phim (film.html, STATE.md của cinecode, review/, audio/mix.json…) nằm trong `out/` nên **không nằm
  trong bản làm việc `projects/`** và không được đẩy theo file: gói kèm bằng `python3 $FILM_LAB/tools/bundle.py $FILM_LAB/out/<project>/ep<NN> --shot s<NN> --with-film` (chỉ file chữ, bỏ
  render và media) sau mỗi bản nháp được duyệt.
- Bản dựng (`renders/`) và âm thanh (`audio/`) không chờ duyệt: xong một bản là báo đạo diễn ngay để đẩy vào
  `04_SanXuat/ep<NN>-<slug>/_ChuaDuyet/` (container cloud bị thu hồi là mất; CONVENTIONS §11.6 "Media chưa duyệt").
  Duyệt xong đạo diễn chuyển bản nháp vào `04_SanXuat/ep<NN>-<slug>/<YYYY-MM-DD>/`, bản cuối vào `05_ThanhPham/ep<NN>-<slug>/`.
- Container bị thu hồi khi phiên rảnh: thay đổi trong `tools/compose/` hay skill (lõi) phải commit + push trước khi dừng;
  dữ liệu của tập không bao giờ commit.

## 8. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `deterministic: NO` | ảnh nạp muộn, `Math.random`/`Date`, trạng thái giữa khung | nạp trong `loadPlates`; chỉ dùng `COMPOSE.rng/noise`, `rng()` của cinecode; `inline.py` để kiểm |
| `Chrome did not start ... --no-sandbox` | container chạy bằng root | `CHROME_PATH=$FILM_LAB/tools/compose/chrome-root.sh` |
| `page threw while loading ... plate L4: could not load` | sai đường dẫn tương đối | đường dẫn tính từ film.html: `../../plates/<file>` (L1, matte `none`) hoặc `../../plates/matte/<file>` (lớp đã tách nền) |
| dòng `compose: plate L1 shows its edge` | L1 không đủ lớn cho chuyển động | tăng `overscan` tới số `inline.py --preflight` in ra, giảm `zoom`/`pan`, hoặc ảnh L1 lớn hơn. Cảnh báo của bộ mã là các dòng `compose:` trong phần `qc` mà `make.py` in ra, không phải console của trình duyệt |
| vạch dọc trên đuôi | hộp warp chứa cả phần thân xa gốc | thu hộp lại, đặt `tail_root` đúng chỗ nối |
| `cliché: lens flare` | chữ "flare" trong phần FILM | đừng dùng từ đó trong mã/ghi chú của FILM, hoặc ghi lý do trên director card |
| `anchors ... scaled` | khoá `size` (hoặc `_size`) trong `anchors.json` khác cỡ ảnh: điểm được đo trên ảnh khác cỡ | đo lại các điểm trên đúng ảnh đã duyệt (`anchors.py set`; `anchors.py` không ghi `size`, khoá đó chỉ có khi sửa tay) rồi xoá khoá `size`; giữ `size` chỉ khi cố ý dùng điểm đo trên bản nhỏ hơn |
| `--preflight` in `ERROR plate L4: rig.warp.<tên> needs anchor box ...` | hộp neo chưa đánh dấu hoặc sai tên | `anchors.py set ... <tên>_tl x y` và `<tên>_br x y`, rồi `inline.py $FILM/film.html` (đọc lại anchors) |
| `--preflight` in `ERROR plate <id>: unknown key ...` | gõ sai khoá trong `PLATES` (bộ mã bỏ qua khoá lạ, không báo) | sửa theo danh sách khoá in kèm; `compose-api.md` §1, §4 |

Thử nhanh bộ mã không tốn phí: `python3 $FILM_LAB/tools/compose/demo_plates.py $FILM_LAB/out/demo`, khởi tạo một phim
Quick trong `$FILM_LAB/out/demo/film/`, `inline.py <film.html> --init --anchors $FILM_LAB/out/demo/anchors.json`;
template chạy nguyên trạng trên lớp thử và `--preflight` báo `0 error(s), 0 warning(s)`.
