# Lồng tiếng Việt với VieNeu-TTS (`tools/tts/vieneu_tts.py`)

Đọc lời bình tiếng Việt **chạy local trên CPU**, không khóa API, không tính phí theo ký tự. Kế hoạch: issue #8.
Tool chỉ render bản đọc thô; hậu kỳ giọng (EQ, nén, reverb, master -14 LUFS) làm ở khâu dựng (cinecode `sound.md` §4b).

## Model và giấy phép (đã kiểm 2026-11-10)

| Thành phần | Phiên bản | Giấy phép | Ghi chú |
|---|---|---|---|
| `vieneu` (PyPI) | 3.8.3 | Apache-2.0 | SDK; bản tối thiểu không cần torch, chạy ONNX Runtime trên CPU |
| **VieNeu-TTS v3 Turbo** `pnnbao-ump/VieNeu-TTS-v3-Turbo` | rev `61b85e3d` | **Apache-2.0** | **dùng cho bản cuối**. 48 kHz, 25 giọng mẫu (Bắc/Trung/Nam). Model card: giọng mẫu và audio tạo ra **được dùng thương mại**, người nói gốc đã đồng ý cho AI |
| Codec `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano(-ONNX)` | – | Apache-2.0 | tải tự động |
| `sea-g2p` (phiên âm) | 0.10.0 | Apache-2.0 | phụ thuộc của `vieneu` |
| VieNeu-TTS v3 Nano `pnnbao-ump/VieNeu-TTS-v3-Nano` | – | Apache-2.0 (bản preview) | `--mode v3nano`: nhanh hơn, chất lượng thấp hơn → chỉ để **nháp nhịp** |
| `resemble-perth` (watermark) | 1.0.1 | MIT | cần torch CPU (`torch==2.15.0+cpu` đã đo); khi có, thư viện tự gắn watermark ẩn vào mọi bản đọc → **bắt buộc cho bản cuối** (`--require-watermark`) |

**Không dùng:**
- VieNeu-TTS **0.3B** (quy tắc dự án: CC BY-NC theo issue #8; không dùng cho bản cuối dù model card hiện ghi apache-2.0).
- Dòng cũ **0.5B / GGUF Q4/Q8** (`pnnbao-ump/VieNeu-TTS`, `-q4-gguf`, `-q8-gguf`): model card ghi apache-2.0 nhưng
  file giọng mẫu `voices.json` (cả trên HF lẫn trong gói `vieneu`) ghi **CC BY-NC 4.0, "non-commercial use only"** →
  giọng mẫu (kể cả "Vĩnh – nam miền Nam") không dùng được cho kênh kiếm tiền. SDK 3.8 đã chuyển mặc định sang v3 Turbo
  (ONNX); dòng 0.5B chỉ còn qua chế độ `standard` cần thêm extra. Tool không nối dòng này.
- **Nhân bản giọng** (`ref_audio`): chỉ khi có bản ghi được phép dùng (giọng người dùng hoặc diễn viên đã ký đồng ý).
  Hiện chưa có → chỉ dùng giọng mẫu.

Ghi model/phiên bản/giấy phép của từng bản đọc: có sẵn trong `tts-log.json` (chép sang `LICENSES.csv` của tập).

## Cài đặt (setup script của môi trường; không nằm trong hook khởi động vì torch nặng ~1 GB)

`docs/setup-script.sh` (bước 3b) cài sẵn theo `requirements-tts.txt`: `vieneu==3.8.3`, rồi torch CPU (`torch==2.15.0`,
`torchaudio`, từ kho wheel CPU), rồi `resemble-perth==1.0.1` chỉ khi torch đã cài được (không bao giờ kéo bản CUDA).
Mỗi bước lỗi chỉ là WARN. `FILM_TTS=0` bỏ bước này; `FILM_TTS_PREFETCH=1` tải trước model v3 Turbo (~300 MB).
`tools/doctor.sh` (cả `--quick`) in hai dòng `tts` (phiên bản `vieneu` so với ghim, model đã có trong cache chưa) và
`tts-watermark` (`perth` + `torch`); thiếu là WARN, riêng `tools/doctor.sh --episode <tập>` báo FAIL thiếu watermark khi
tập đã qua G3 và có lời bình.

Cài tay (môi trường cũ chưa có bước 3b):
```bash
pip install --break-system-packages --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 torchaudio   # ~1 GB, ~3 phút
pip install --break-system-packages -r requirements-tts.txt     # vieneu + resemble-perth; lần chạy đầu tải ~300 MB model
python3 tools/tts/vieneu_tts.py --list-voices --gender male --region nam   # kiểm tra
```
Thiếu `vieneu` → tool in hướng dẫn cài và thoát mã 3. Thiếu watermark → tool vẫn chạy và in `watermark OFF`, trừ khi có
`--require-watermark` (thoát mã 4 **trước** khi nạp model). Mọi lần render không phải nghe thử đều dùng cờ này: bản đọc
thiếu watermark phải đọc lại cả tập và trộn lại âm thanh. `status.py --gate G4` kiểm `watermark: true` ở mọi mục của
`<media>/vo/tts-log.json` (tập không có log lời bình: không áp dụng).
Lỗi `External data path escapes model directory` → `docs/RUNBOOK.md`.

**Máy chủ lab Windows** (WSL không có `pip`, ổ C: đầy): VieNeu cài trong venv trên D:, cache pip/Hugging Face cũng trên D:
(`docs/setup-local-windows.md`). `FILM_TTS_PYTHON=<python của venv>` làm `python3 tools/tts/vieneu_tts.py …` tự chạy lại
bằng python đó (cùng tham số; giá trị sai → mã 2); `tools/doctor.sh` dòng `tts`/`tts-watermark` kiểm venv đó khi biến có mặt.

## Dùng

```bash
# Toàn bộ lời bình của tập (id VO1, VO2… theo thứ tự các dòng [mm:ss])
python3 tools/tts/vieneu_tts.py --script projects/son-hai-kinh/ep01-<slug>/script.md \
    --out out/son-hai-kinh/ep01/vo --voice "Thái Sơn" --pron projects/son-hai-kinh/pronunciation.csv --require-watermark

# Từ vo-lines.json của cinecode, chỉ render lại vài dòng
python3 tools/tts/vieneu_tts.py --lines audio/vo-lines.json --out audio/vo --voice "Thái Sơn" --only VO3 VO7

# Xem trước (không nạp model): chữ sẽ đọc sau chuẩn hóa, khung giờ, độ dài ước lượng, token chưa đọc được
python3 tools/tts/vieneu_tts.py --script .../script.md --pron .../pronunciation.csv --dry-run --strict

# Kiểm bản đọc đã xong chưa (không nạp model): mọi dòng của kịch bản có bản đọc khớp chữ, giọng, mode, seed, vừa khung
# theo mốc hiện tại (--strict) và có watermark (--require-watermark)
python3 tools/tts/vieneu_tts.py --script .../script.md --out out/<p>/ep<NN>/vo --voice "Thái Sơn" --check --strict --require-watermark

# Nghe thử nhiều giọng cùng câu (cổng duyệt giọng): male-nam | male | female | all | "Tên 1,Tên 2"
python3 tools/tts/vieneu_tts.py --audition male-nam --text "Câu một." --text "Câu hai." --out out/<p>/ep<NN>/vo/audition
```

### Các chế độ

| Chế độ | Nạp model | Việc làm |
|---|---|---|
| render (`--script` / `--lines` / `--text` + `--out`) | có | đọc từng dòng ra `<id>.wav`, ghi `tts-log.json` sau **mỗi** dòng. Mỗi `--out` chỉ một lần render một lúc (khoá `<out>/.tts-log.lock`; lần thứ hai thoát mã 2 trước khi nạp model) |
| `--only <id…>` | có | chỉ đọc lại các id đã nêu; từ chối (mã 2) nếu dòng khác đang `STALE`, trừ khi thêm `--allow-stale` |
| `--dry-run` | không | in chữ sau chuẩn hóa, bảng khung giờ với độ dài **ước lượng** (số âm tiết / `--rate`, mặc định 4 âm tiết/giây), `WARN` token chưa đọc được; có `--out` thì báo thêm `STALE`/`ORPHAN`. Không ghi gì |
| `--check` | không | **tiêu chí xong** của khâu lồng tiếng: mã 0 chỉ khi mọi dòng của `--script`/`--lines` có `<id>.wav` và mục log khớp chữ hiện tại, `--voice`, `--mode`, `--seed`, độ dài > 0, và không còn `ORPHAN`; ngược lại liệt kê từng dòng, mã 1. Không có `--voice` thì chỉ đòi cả tập dùng một giọng. Khung tính lại từ mốc **hiện tại** của kịch bản: bản đọc dài hơn khung là `WARN VO<n>: OVER`, thành lỗi với `--strict`. `--require-watermark`: mọi mục phải có `watermark: true` |
| `--audition` | có | mỗi giọng đọc các câu `--text`, ghi `audition-log.json` |
| `--list-voices` | có | liệt kê giọng mẫu |

### Mã thoát

| Mã | Nghĩa |
|---|---|
| 0 | xong, không có gì phải sửa |
| 1 | một bản đọc hoặc một phép kiểm không đạt: `EMPTY` (luôn luôn, không cần `--strict`); với `--strict`: `OVER`, `CLIPPED`, token chưa đọc được (dừng **trước** khi nạp model), `NOSLOT` khi đầu vào là `--script`; `--dry-run --strict`: ước lượng vượt khung quá 15 %; `--check` không đạt; ffmpeg lỗi khi đổi tốc độ (`ERROR VO<n>: ffmpeg atempo=... failed`: bản đọc trước đó của dòng còn nguyên, các dòng sau chưa đọc) |
| 2 | lỗi đầu vào, **chưa render gì**: `script.md:<n>: <lý do>`, `vo-lines.json` sai, file không đọc được, tham số sai (`--speed` ngoài 0,9–1,1, `--only` id lạ, thiếu `--out`), `--only` để lại dòng `STALE`, thiếu ffmpeg khi `--speed` ≠ 1, một lần render khác đang giữ `--out` |
| 3 | chưa cài `vieneu` |
| 4 | `--require-watermark` mà watermark tắt: `resemble-perth` không import được (kiểm **trước** khi nạp model), hoặc model lên mà không gắn watermark. Chưa render gì |

Tùy chọn chính: `--voice` (tên giọng mẫu), `--speed` (**chỉ nhận 0,9–1,1**, ngoài khoảng là lỗi tham số; v3 Turbo không có
tốc độ gốc → đổi sau bằng ffmpeg `atempo`, giữ cao độ, tool kiểm có ffmpeg trước khi nạp model; v3 Nano có tốc độ gốc.
Dòng quá khung thì rút lời hoặc dời mốc, không tăng tốc để che), `--seed` (mặc định 1234: cùng seed + chữ + giọng = cùng
bản đọc), `--precision int8|fp32` (int8 mặc định, cần CPU có VNNI; fp32 chậm hơn, "độ trung thực tối đa" theo tác giả),
`--numbers nam|bac` (đọc số kiểu Nam: *ngàn, lẻ* – mặc định; kiểu Bắc: *nghìn, linh*), `--length` (độ dài tập, mặc
định lấy `length_s` trong `EPISODE.md` cạnh `script.md`), `--rate` (âm tiết/giây cho ước lượng của `--dry-run`),
`--strict` (xem bảng mã thoát), `--require-watermark` (mọi lần render không phải nghe thử).

**Đầu vào `script.md`:** cùng quy tắc với `tools/check_episode.py`: chỉ dòng `[mm:ss] lời` (cho phép `- ` đầu dòng) là
lời bình; tiêu đề `#`, trích dẫn `>`, chú thích `<!-- -->`, khối code, front matter, đường kẻ bị bỏ qua. **Không dòng
lời bình nào bị bỏ qua lặng lẽ**: dòng thiếu mốc, mốc sai dạng (`[0:05]`), giây > 59, mốc không có lời, mốc không sau
mốc trước, `length_s`/`--length` không lớn hơn mốc cuối → in `script.md:<n>: <lý do>` ra stderr và thoát mã 2, kể cả
với `--dry-run` và `--check`; không có cờ nào bỏ qua được.

**Đầu vào `--lines`:** object `{"lines": [{"id": "VO1", "text": "…", "start_s": 0, "slot_s": 5}]}`. `id` thành tên file
nên phải khớp `^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$` và không trùng (bỏ trống thì là `VO<thứ tự>`); `text` không rỗng;
`start_s`/`slot_s` là số nếu có; danh sách rỗng là lỗi. Sai → một dòng trên stderr, mã 2.

**Đầu ra trong `--out`:** `<id>.wav` (mono, PCM 24-bit, tần số gốc của model: 48 kHz với v3 Turbo) và `tts-log.json`:
danh sách **theo thứ tự kịch bản** (id kịch bản không còn biết xếp cuối), mỗi id một mục, render lại thì thay mục cũ,
ghi sau mỗi dòng nên chạy dở vẫn giữ phần đã đọc. Các trường tool thật sự ghi:

| Nhóm | Trường |
|---|---|
| Dòng | `id`, `text`, `text_sha` (12 ký tự hex đầu của sha256 chữ NFC), `spoken` (chữ sau chuẩn hóa), `chars`, `file` |
| Khung giờ | `start_s`, `slot_s`, `duration_s`, `seconds` (làm tròn 2 số), `fit` (`ok (x s spare)` / `OVER +x s` / rỗng khi không có khung) |
| Chất lượng đo được | `status` (`ok` / `EMPTY` / `OVER` / `CLIPPED` / `NOSLOT`: lỗi nặng nhất), `flags` (mọi lỗi), `rms_dbfs`, `peak_dbfs`, `clipped` (số mẫu chạm đỉnh), `lead_silence_s`, `tail_silence_s` |
| Nguồn gốc | `engine`, `mode`, `voice`, `model`, `model_revision`, `precision`, `version`, `licence`, `codec`, `watermark`, `sample_rate`, `seed`, `speed` |

`EMPTY` = ngắn hơn 0,2 s hoặc RMS dưới −50 dBFS (model không đọc được dòng) → luôn thoát mã 1. `OVER` = dài hơn khung
(từ mốc dòng này tới mốc dòng sau, dòng cuối tới `length_s`) → rút lời hoặc dời mốc sau. `NOSLOT` = không biết khung
(thường là dòng cuối khi thiếu `length_s`) → thêm `--length` hoặc `length_s` trong `EPISODE.md`.

**Bản đọc cũ (`--script`/`--lines`):** sau khi sửa kịch bản, tool so cả kịch bản với log: `STALE <id>: text changed
since render` (chữ của dòng đã đổi; mục cũ chưa có `text_sha` thì so bằng `text`), `ORPHAN <id>: not in script` và
`ORPHAN <id>: <id>.wav has no log entry and is not in script` (wav còn lại sau khi log hỏng bị cất đi).
Render **không** `--only` chuyển wav mồ côi vào `<out>/_stale/` và bỏ mục của chúng (không bao giờ xoá audio). `--only`
không đụng tới wav mồ côi và từ chối chạy khi một dòng ngoài danh sách đang `STALE`. Sau khi chèn/xoá dòng, id `VO<n>`
dịch đi → render lại cả tập rồi `--check`.

**`tts-log.json` hỏng** (không đọc được hoặc không phải danh sách): trước khi nạp model, tool đổi tên thành
`tts-log.json.bad-<giờ UTC>`, báo ra stderr rồi chạy tiếp với log rỗng.

Chế độ `--audition` ghi `<giọng>_<id>.wav` và `audition-log.json` (độ dài, RMS, đỉnh, số mẫu bị clip, khoảng lặng
đầu/cuối, tốc độ render).

## Chuẩn hóa chữ

Thứ tự: bảng phát âm → viết tắt (`TCN`, `SCN`, `v.v.`) → số La Mã/thứ tự và khoảng của chúng (`thế kỷ IV` → *thế kỷ
thứ tư*, `thế kỷ XIV–XV` → *thế kỷ thứ mười bốn đến thứ mười lăm*, `thứ 1` → *thứ nhất*, `thứ 2` → *thứ hai*, `chương
3–5` → *chương ba đến năm*) → tháng (`tháng 4` → *tháng tư*, `tháng 4/2024`) → ngày (`12/4/2024`, `2-9-1945`, `ngày 1/5`)
→ giờ (`8h30`, `21h`) → phân số (`3/4` → *ba phần tư*, `1/2` → *một phần hai*) → khoảng (`3–5`, `300-400` → *đến*) →
số âm (`-5°C` → *âm năm độ xê*; chỉ khi dấu trừ dính liền số) → số thập phân `3,5`, hàng nghìn `3.000`, năm và số
thường → đơn vị sau số (`km, m, cm, mm, kg, g, ha, l, ml, m², km², km/h, °C, %`). `a/b` đứng một mình là **phân số**;
muốn đọc là ngày/tháng thì viết `ngày 1/5` (hoặc `hôm`, `mùng`, `mồng`). Số đọc theo quy tắc: *mốt* sau *mươi* từ 21
(*hai mươi mốt*), *lăm* sau mọi hàng chục (*mười lăm, hai mươi lăm*), *lẻ/linh* cho hàng chục 0 (*một trăm lẻ năm*),
*mười* cho 10, *mươi* từ 20. Bảng ca kiểm thử: `tests/test_tts.py` `TestNormalizeTable`. Dấu tiếng Việt giữ nguyên;
`**đậm**`/`*nghiêng*` bị bỏ ký hiệu. Thư viện còn tự chuẩn hóa thêm phần còn sót.

**Token chưa đọc được:** sau chuẩn hóa, từ nào còn chứa chữ số (`3.5 km` → `ba.5`, `1e6` → `mộte6`), chữ Hán, `《 》`
hoặc một trong `& + = ^ $ / °` thì `--dry-run` và render in `WARN <id>: unread token '<tok>': add it to
pronunciation.csv or rewrite the line`; `--strict` biến nó thành mã 1 (render dừng trước khi nạp model). Sửa bằng cách
thêm dòng vào bảng phát âm hoặc viết lại câu trong kịch bản (qua biên kịch, không sửa tay ở khâu lồng tiếng).

**Bảng phát âm** `--pron` (CSV UTF-8, header `term,doc`, dòng `#` là chú thích): thay nguyên từ, cụm dài trước. Dùng
cho tên Hán Việt model hay đọc sai hoặc cần đọc theo âm đã chọn trong `research.md`. Đặt ở bản làm việc dự án
`projects/<project>/pronunciation.csv` (dữ liệu dự án, không commit; trên Drive là `02_KinhThu/pronunciation.csv`, cạnh
`SERIES.md`, CONVENTIONS §11.3; `tools/drive_sync.py plan` lập lệnh đẩy như mọi file chữ; dự án mới chép mẫu
`templates/project/pronunciation.csv`):

```csv
term,doc
# tên riêng: viết theo âm muốn nghe
Chiêu Diêu,Chiêu Diêu
```

## Tốc độ CPU đo được (4 vCPU Xeon 2,1 GHz, AVX-512 VNNI, không GPU, 2026-11-10)

| Backbone | 54 s lời (10 câu, giọng Đức Trí) | Tốc độ | Nạp model |
|---|---|---|---|
| int8 (mặc định) | 33,5 s tính toán | **1,6 s audio / 1 s** | ~7 s (cache sẵn), lần đầu +tải ~300 MB |
| fp32 | 47,5 s tính toán | 1,15 s audio / 1 s | như trên |

1 phút lời ≈ 40 s (int8) hoặc ≈ 55 s (fp32), RAM đỉnh ~1 GB (int8, có watermark).

## Chọn giọng

Chọn bằng tai ở cổng duyệt (issue #8): render audition, người dùng nghe và chọn, ghi giọng đã chọn vào `SERIES.md`
của dự án để mọi tập dùng chung. Giọng nam miền Nam có sẵn (v3 Turbo 3.8.3, theo nhãn của thư viện):
`Thái Sơn` (kể chuyện), `Đức Trí` (đọc truyện), `Minh Triết` (tin tức), `Adam` (tự nhiên).
Nhãn vùng miền do thư viện ghi, không phải đo được (bản v3 Nano lại ghi `Đức Trí` là "Nam · Bắc" → nghe kỹ giọng
miền); tên giọng có thể đổi giữa các bản SDK (có alias) → ghim phiên bản.

Không nghe được thì kiểm khách quan: thời lượng, RMS, đỉnh, clip (`audition-log.json`), và đọc ngược bằng ASR
(PhoWhisper-small, chỉ để QA, không nằm trong repo) để bắt từ bị nuốt/đọc sai.
