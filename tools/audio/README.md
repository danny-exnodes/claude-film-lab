# Âm thanh tổng hợp tại chỗ (`tools/audio/`)

Nhạc cụ gảy dây, foley thủ tục và trình dựng điểm nhạc cho một tập, **chạy local, miễn phí**: chỉ `numpy` + `scipy`
(đã có sẵn), không sample, không mạng, không API tính phí. Kế hoạch: issue #33.

| File | Việc |
|---|---|
| `pluck.py` | dây gảy mô hình vật lý (Karplus-Strong mở rộng): `guqin`, `pipa`, `koto`; `pluck()`, `strum()` |
| `sfx.py` | viên gạch (lọc, đường bao, nhiễu có seed, `compress`, `limit`, `add`) và foley đặt tên theo bảng của `styles/thuy-mac/sound.md` |
| `score.py` | CLI: đọc `score.json` của tập, kiểm tra, dựng stem `music` / `foley` / `ambience` + bản nghe thử + log |

## Nó là gì và không là gì

- **Là** lựa chọn "code" có chất lượng khá cho nhạc và cho foley rơi đúng khung hình. Thay cho việc viết Web Audio
  trong `film.html` (cinecode giữ bản nháp `SOUND THIN` / `SOUND ALL CODE`).
- **Nhạc vẫn do người dùng chọn** (câu hỏi của cinecode: bản thu giấy phép mở · nhạc của họ · code · không). Tool này
  không tự bật: chỉ viết phần `music` của `score.json` khi dòng `Music:` trong `STATE.md` ghi `code (user)`. Phần
  `foley` (âm theo sự kiện trên hình) thì dùng được ở mọi lựa chọn nhạc.
- **Không phải sampler**: không có bản thu nhạc cụ thật. `drone` (đàn kéo trầm) và `gong` (cồng nhỏ) là **xấp xỉ tổng
  hợp**, không phải nhạc cụ kéo/gõ thật. **Không có sáo/tiêu (xiao)**: sáo thổi đầu không phải dây gảy, nằm ngoài phạm
  vi; câu nhạc dài của tiêu trong `sound.md` cần bản thu có giấy phép hoặc để trống.
- **Không master**: `preview.wav` chỉ để nghe thô. Bản cuối vẫn qua `mix.py` + `master_audio.py` của cinecode (−14 LUFS).
- Âm thanh được **đo, không nghe**: tool in đỉnh/RMS từng stem; vẫn nhờ người dùng nghe các giây quan trọng.

## Lệnh

```bash
python3 tools/audio/score.py projects/<project>/<tập>/score.json --dry-run            # kiểm tra + bảng cue theo thời gian, không ghi gì
python3 tools/audio/score.py projects/<project>/<tập>/score.json --out out/<project>/<id>/audio
python3 tools/audio/score.py .../score.json --out out/<project>/<id>/audio/v02 --stems   # thêm stems/<danh sách>-<tên>.wav
python3 tools/audio/score.py .../score.json --out ... --seed 11                        # bản khác của mọi chi tiết ngẫu nhiên
```

- Mã thoát: **0** xong · **2** lỗi đầu vào hoặc bị từ chối (in **mọi** lỗi, không ghi gì).
- File đầu ra đã tồn tại thì bị từ chối (như các tool khác): dựng bản mới vào thư mục mới (`audio/v02`) hoặc `--overwrite`.
- `--bits 16|24` (mặc định 24). Mọi file: stereo, 48 kHz, PCM, ghi bằng module `wave` chuẩn.
- Cùng `score.json` + cùng seed → file **giống hệt từng byte**. Không có trạng thái ngẫu nhiên toàn cục: mỗi sự kiện
  lấy seed từ seed của điểm nhạc + vị trí của nó trong danh sách (`"seed": N` trên sự kiện để ghim âm đó khi đổi thứ tự).
- `numba` là tuỳ chọn và **mặc định tắt**: mọi thứ chạy bằng numpy/scipy (nốt guqin 4 s ≈ 0,1 s; nốt có trượt/rung
  ≈ 0,1 s). `FILM_AUDIO_ENGINE=numba` bật nhân numba cho nốt có cao độ đổi; kết quả lệch bản numpy ở vài bit cuối
  (≈ 2e-9) nên không còn giống từng byte với máy không bật. `score-log.json` ghi `engine`.

Đầu ra trong `--out`:

| File | Nội dung |
|---|---|
| `music.wav` | mọi sự kiện của danh sách `music` |
| `foley.wav` | sự kiện của `foley` không phải nền |
| `ambience.wav` | nền (`wind`, `fire`, `drone` đặt trong `foley`) |
| `preview.wav` | ba stem cộng lại rồi giới hạn đỉnh 0,9: **nghe thô, không phải bản master** |
| `score-log.json` | mỗi file: đỉnh dBFS, RMS, thời lượng, số sự kiện, DC; seed, phiên bản tool, engine, sha256 của điểm nhạc, cửa sổ lặng (`exact_zero`), bảng cue, ghi chú giấy phép `synthesised by tools/audio, no samples` |
| `mix-snippet.json` | các `layers` để dán vào `audio/mix.json` của phim |
| `stems/<music\|foley>-<tên>.wav` | chỉ với `--stems`: mỗi nhạc cụ/âm một file (cộng lại bằng stem tương ứng) |

Stem nào cộng lại vượt đỉnh 0,97 thì cả stem được hạ bằng một hệ số (WARN, `gain_db` trong log): hạ `gain` của sự kiện.

## `score.json`

Dữ liệu dự án: nằm ở `projects/<project>/<tập>/score.json` (không commit, đẩy lên Drive cùng file chữ của tập).
Mẫu: `templates/episode/score.json` (JSON không có chú thích: dùng khóa `"note"` để ghi chú, có ở gốc, ở từng sự kiện
và từng khoảng lặng).

```json
{"length_s": 60, "seed": 7, "tempo": 90, "scale": ["D", "F", "G", "A", "C"],
 "music":   [{"t": 3.0, "inst": "guqin", "pitch": "D3", "dur": 4, "vel": 0.7, "pan": -0.2, "shot": "s01"}],
 "foley":   [{"t": 12.4, "sound": "hoof", "gain": 0.6, "pan": 0.1, "shot": "s03"}],
 "silence": [{"from": 20.0, "to": 23.5}]}
```

| Khóa gốc | Ý nghĩa |
|---|---|
| `length_s` | bắt buộc, độ dài (s), tối đa 600; tập dài hơn thì chia nhiều điểm nhạc |
| `seed` | số nguyên ≥ 0 (mặc định 0); `--seed` ghi đè |
| `tempo` | tuỳ chọn (20–300 BPM): sự kiện được ghi `"beat": n` thay cho `"t"` (`t = beat × 60 / tempo`). Chọn tempo có phách là số nguyên khung hình: ở 24 fps là 80, 90, 96, 120, 144 |
| `scale` | tuỳ chọn, tên nốt (`"D"` hoặc `"D3"`): nốt nhạc ngoài thang là **WARN** (luật D thứ ngũ cung của style) |
| `music`, `foley` | danh sách sự kiện |
| `silence` | khoảng **lặng số thật**: sự kiện nào còn kêu trong đó là **ERROR**, trừ khi có `"allow_in_silence": true` (vd. một tiếng cồng duy nhất). Nền (gió, drone) phải tách thành hai sự kiện quanh khoảng lặng |

Khóa chung của sự kiện: `t` (giây) hoặc `beat`, `dur`, `gain` (tuyến tính, mặc định 1, tối đa 4), `pan` (−1..1),
`shot` (id shot, in trong bảng cue), `note`, `seed`, `allow_in_silence`. Khóa lạ là ERROR.

**`music`** – `inst`:

| `inst` | Khóa riêng |
|---|---|
| `guqin`, `pipa`, `koto` | `pitch` (`"D3"`, `"F#4"`, `"Bb2"` hoặc số MIDI, C4 = 60) **hoặc** `pitches` (rải dây: cần `dur`; `spread` giây giữa các dây, `up`), `vel` 0..1, `harmonic` (`true`/`2` = cao hơn nốt ghi một quãng tám, `3` = quãng tám + quãng năm, `4` = hai quãng tám), `bend` `[[giây, nửa cung], …]` (giữ giá trị cuối), `vib` `[Hz, độ sâu nửa cung, bắt đầu s]`, `glide` `[nốt đích, giây]`, `trem` (số lần gảy lại mỗi giây, cần `dur`), `release`, và tham số preset `t60`, `damp`, `pos`, `bright`, `bmix`, `noise` |
| `gong`, `drum`, `drum_roll`, `drone` | như foley cùng tên, `vel` thay cho `intensity`; vào stem `music` |

Độ dài một nốt gảy = `dur` + `release` (0,25 s; bồi âm 0,8 s); bỏ `dur` thì nốt ngân theo `t60` của preset
(guqin 7 s, pipa 2,8 s, koto 3,5 s). Nốt còn ngân quá `length_s` bị tắt dần ở cuối (WARN).

**`foley`** – `sound` (mọi âm: `dur`, `intensity` 0..1, `pitch`):

| `sound` | Mặc định | Dùng cho | Khóa riêng |
|---|---|---|---|
| `wind` | 10 s, **nền** | gió núi rất thấp (sương không có tiếng riêng) | `fade_s` |
| `fire` | 10 s, **nền** | lửa: ù trầm + lách tách có seed | `fade_s` |
| `drone` | 8 s, **nền** | nền kéo trầm trên D; `pitch` là **tên nốt** (mặc định `D2`) | `fade_s` |
| `brush_air` | 0,5 s | "gió bút": đuôi/lông lay (`strip-warp`), vạt áo (`cloth`); đỉnh ở 40 % độ dài | |
| `whoosh` | 1,2 s | khói/sương dâng (tối đa 2 mỗi 30 s) | `rise` (false = hạ xuống) |
| `hoof` | 0,6 s | móng guốc trên đá: gõ gỗ khô + đuôi vang núi | |
| `ink_drop` | 0,5 s | mắt mở/nhắm: "tink" + tiếng ướt | |
| `gong` | 4 s | cồng nhỏ một tiếng: đóng triện, lộ diện | |
| `drum` | 0,8 s | trống khung một tiếng: bước chân dị thú | |
| `drum_roll` | 2 s | trống khung dồn | `rate` (lần/giây), `swell` |
| `ember` | 0,25 s | một tàn lửa nổ | |
| `thump` | 0,4 s | va chạm nặng, mềm | |
| `footstep` | 0,3 s | bước chân | `surface`: `earth` \| `stone` |
| `cloth_flap` | 0,4 s | vải phần phật (không dùng cho đuôi/lông: đó là `brush_air`) | |
| `water_ring` | 1,5 s | giọt nước và vòng sóng | |

`pitch` của foley là hệ số (0,25–4; 1 = gốc), riêng `drone` là tên nốt. Mọi hàm trả về mono float32 48 kHz, đúng
`round(dur × 48000)` mẫu, đỉnh < 1,0 (cường độ 0 → 0,45; 1 → 0,9).

**Đồng bộ**: đỉnh của tiếng va chạm nằm ngay đầu file nên `t` = khung tiếp xúc (`khung / fps`). `brush_air` và `whoosh`
có đỉnh muộn: đặt `t` sớm hơn (`brush_air`: 0,4 × `dur`; `whoosh`: 0,72 × `dur`) để đỉnh rơi 2–3 khung trước chuyển động.

## Nối vào mix của cinecode

`mix.py` của cinecode đọc `audio/mix.json`: `{"duration", "out", "layers": [{"file", "at", "gain_db", "bus", …}]}`,
cộng thêm theo bus: dialogue 0, foley −1, sfx −2, ambience −3, music −4 dB (đã đối chiếu với `scripts/mix.py` của bản
cinecode đang ghim; `tests/test_audio.py` chạy `mix.py --list` trên snippet). `score.py` in và ghi `mix-snippet.json`:

```json
{"layers": [{"file": "/…/out/<project>/<id>/audio/music.wav", "at": 0.0, "gain_db": 0, "bus": "music"},
            {"file": "/…/audio/foley.wav", "at": 0.0, "gain_db": 0, "bus": "foley"},
            {"file": "/…/audio/ambience.wav", "at": 0.0, "gain_db": 0, "bus": "ambience"}]}
```

Dán các layer vào `layers` của `audio/mix.json` trong thư mục phim (đường dẫn tuyệt đối: container mới thì dựng lại
stem rồi dán lại), chỉnh `gain_db` theo số đo (`qc.py`), giữ nhạc thấp hơn lời ~8 dB. Stem foley đi bus `foley`
(tiếp xúc khóa theo khung hình); bản thu tải về vẫn đi bus `sfx`. Stem không có sự kiện nào thì không được đưa vào snippet.
Vẫn **liệt kê mọi sự kiện** trong `review/sound-audit.md` (bảng cue của `--dry-run` là nguồn chép: thời điểm · âm · shot).
Ghi trong `LICENSES.csv` của phim một dòng cho các stem: nguồn `tools/audio`, giấy phép "tự tổng hợp, không sample".

## Dùng trong Python

```python
import sys; sys.path.insert(0, "tools/audio")
import pluck, sfx
x = pluck.pluck("guqin", "D3", 4, vel=.7, bend=[(0.6, 0), (1.2, 2)], vib=(5, .25, 1.4), seed=1)
buf = sfx.stereo(30.0)                      # (N, 2) float32
sfx.add(buf, x, at=3.0, gain=.8, pan=-.2)
sfx.add(buf, sfx.hoof(intensity=.7, seed=3), at=12.4, gain=.6)
```

## Số đo kiểm chứng (không nghe được nên đo)

`tests/test_audio.py` kiểm: tần số cơ bản của nốt gảy lệch < 1 % (đo được < 0,01 % cho D2–A5, cả ba preset; cuối
đoạn trượt D3 → E3 đo 164,82 Hz so với 164,81), bồi âm 2/3/4 đúng bội số, t60 đo ở A3: guqin 5,8 s / pipa 2,6 s /
koto 3,3 s (preset 7 / 2,8 / 3,5), trọng tâm phổ pipa (≈ 1050 Hz) cao hơn guqin (≈ 480 Hz) ở D4, không clip, không DC,
cửa sổ lặng toàn số 0, ba stem cộng lại bằng `preview.wav` khi chưa chạm bộ giới hạn.

## Nguồn và giấy phép

`pluck.py` và các viên gạch của `sfx.py` phỏng theo `core/audio/pluck.py` và `core/audio/sfx.py` của
[lemomo-ai/lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar), Copyright (c) 2026 LemoLab, **MIT License**
(nguyên văn giấy phép: `THIRD_PARTY.md` ở gốc repo; phần đã đổi ghi ở đầu từng file). Không lấy phim mẫu, nhân vật,
điểm nhạc hay tài sản nào của repo đó (CC BY). Sampler của họ không được chuyển sang. Foley đặt tên trong `sfx.py`
viết riêng cho lab này. Âm thanh tạo ra là của dự án, không kèm nghĩa vụ ghi công.
