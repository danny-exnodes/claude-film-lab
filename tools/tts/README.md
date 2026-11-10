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
| `resemble-perth` (watermark) | 1.0.1 | MIT | cần torch CPU; khi có, thư viện tự gắn watermark ẩn vào mọi bản đọc → **giữ nguyên** |

**Không dùng:**
- VieNeu-TTS **0.3B** (quy tắc dự án: CC BY-NC theo issue #8; không dùng cho bản cuối dù model card hiện ghi apache-2.0).
- Dòng cũ **0.5B / GGUF Q4/Q8** (`pnnbao-ump/VieNeu-TTS`, `-q4-gguf`, `-q8-gguf`): model card ghi apache-2.0 nhưng
  file giọng mẫu `voices.json` (cả trên HF lẫn trong gói `vieneu`) ghi **CC BY-NC 4.0, "non-commercial use only"** →
  giọng mẫu (kể cả "Vĩnh – nam miền Nam") không dùng được cho kênh kiếm tiền. SDK 3.8 đã chuyển mặc định sang v3 Turbo
  (ONNX); dòng 0.5B chỉ còn qua chế độ `standard` cần thêm extra. Tool không nối dòng này.
- **Nhân bản giọng** (`ref_audio`): chỉ khi có bản ghi được phép dùng (giọng người dùng hoặc diễn viên đã ký đồng ý).
  Hiện chưa có → chỉ dùng giọng mẫu.

Ghi model/phiên bản/giấy phép của từng bản đọc: có sẵn trong `tts-log.json` (chép sang `LICENSES.csv` của tập).

## Cài đặt (mỗi phiên cần lồng tiếng; không nằm trong hook khởi động vì nặng)

```bash
pip install vieneu==3.8.3                       # ~2 phút; lần chạy đầu tải ~300 MB model vào ~/.cache/huggingface
# watermark (khuyến nghị cho bản cuối; torch CPU ~1 GB, ~3 phút):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu && pip install resemble-perth==1.0.1
python3 tools/tts/vieneu_tts.py --list-voices --gender male --region nam   # kiểm tra
```
Thiếu `vieneu` → tool in hướng dẫn cài và thoát mã 3. Thiếu watermark → tool vẫn chạy nhưng in `watermark OFF`.
Lỗi `External data path escapes model directory` → `docs/RUNBOOK.md`.

## Dùng

```bash
# Toàn bộ lời bình của tập (id VO1, VO2… theo thứ tự các dòng [mm:ss])
python3 tools/tts/vieneu_tts.py --script projects/son-hai-kinh/ep01-<slug>/script.md \
    --out out/son-hai-kinh/ep01/vo --voice "Thái Sơn" --pron projects/son-hai-kinh/pronunciation.csv

# Từ vo-lines.json của cinecode, chỉ render lại vài dòng
python3 tools/tts/vieneu_tts.py --lines audio/vo-lines.json --out audio/vo --voice "Thái Sơn" --only VO3 VO7

# Xem trước chữ sẽ đọc (đã chuẩn hóa) và khung giờ, không nạp model
python3 tools/tts/vieneu_tts.py --script .../script.md --pron .../pronunciation.csv --dry-run

# Nghe thử nhiều giọng cùng câu (cổng duyệt giọng): male-nam | male | female | all | "Tên 1,Tên 2"
python3 tools/tts/vieneu_tts.py --audition male-nam --text "Câu một." --text "Câu hai." --out out/<p>/ep<NN>/vo/audition
```

Tùy chọn chính: `--voice` (tên giọng mẫu), `--speed` (v3 Turbo không có tốc độ gốc → đổi sau bằng ffmpeg `atempo`,
giữ cao độ, nên trong 0,9–1,1; v3 Nano có tốc độ gốc), `--seed` (mặc định 1234: cùng seed + chữ + giọng = cùng bản đọc),
`--precision int8|fp32` (int8 mặc định, cần CPU có VNNI; fp32 chậm hơn, "độ trung thực tối đa" theo tác giả),
`--numbers nam|bac` (đọc số kiểu Nam: *ngàn, lẻ* – mặc định; kiểu Bắc: *nghìn, linh*), `--length` (độ dài tập, mặc
định lấy `length_s` trong `EPISODE.md` cạnh `script.md`), `--strict` (thoát mã 1 nếu có dòng quá khung).

**Đầu vào `script.md`:** cùng quy tắc với `tools/check_episode.py`: chỉ dòng `[mm:ss] lời` (cho phép `- ` đầu dòng) là
lời bình; tiêu đề `#`, trích dẫn `>`, chú thích `<!-- -->`, khối code, front matter, đường kẻ bị bỏ qua.

**Đầu ra trong `--out`:** `<id>.wav` (mono, PCM 24-bit, tần số gốc của model: 48 kHz với v3 Turbo) và `tts-log.json`
(danh sách, mỗi id một mục, render lại thì thay mục cũ): `id, text, spoken` (chữ sau chuẩn hóa), `file, duration_s,
start_s, slot_s, fit, voice, model, model_revision, precision, version, licence, codec, watermark, sample_rate, seed,
speed`. Bảng in ra so độ dài thật với khung giờ của kịch bản (từ mốc dòng này tới mốc dòng sau, dòng cuối tới
`length_s`): `OVER +x s` = dòng dài hơn khung → rút lời hoặc dời mốc sau. Chế độ `--audition` ghi
`<giọng>_<id>.wav` và `audition-log.json` (độ dài, RMS, đỉnh, số mẫu bị clip, khoảng lặng đầu/cuối, tốc độ render).

## Chuẩn hóa chữ

Thứ tự: bảng phát âm → viết tắt (`TCN`, `SCN`, `v.v.`) → số La Mã/thứ tự (`thế kỷ IV` → *thế kỷ thứ tư*, `thứ 1` →
*thứ nhất*, `chương 21`) → ngày `12/4/2024`, giờ `7h30` → khoảng `300-400` (*đến*) → số thập phân `3,5`, hàng nghìn
`3.000`, năm và số thường → đơn vị sau số (`km, m, cm, mm, kg, g, ha, l, ml, m², km², km/h, °C, %`). Dấu tiếng Việt
giữ nguyên; `**đậm**`/`*nghiêng*` bị bỏ ký hiệu. Thư viện còn tự chuẩn hóa thêm phần còn sót.

**Bảng phát âm** `--pron` (CSV UTF-8, header `term,doc`, dòng `#` là chú thích): thay nguyên từ, cụm dài trước. Dùng
cho tên Hán Việt model hay đọc sai hoặc cần đọc theo âm đã chọn trong `research.md`. Đặt ở bản làm việc dự án
`projects/<project>/pronunciation.csv` (dữ liệu dự án, lưu Drive, không commit):

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
