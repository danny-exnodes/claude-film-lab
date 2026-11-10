# Quy ước và schema (v1)

Hợp đồng chung cho mọi skill, agent, công cụ trong repo. Đổi schema = đổi file này trước, rồi mới đổi code.
Quyết định cho các đề xuất ở issue #1–#7 được ghi ở cuối file.

## 1. Cấu trúc thư mục

```
claude-film-lab/
├── CLAUDE.md · README.md · CHANGELOG.md · requirements.txt
├── .claude/
│   ├── settings.json · hooks/session-start.sh
│   ├── skills/film-pipeline/ · film-script/ · film-prompt-layers/ · film-compose-shot/   # skill lõi
│   ├── agents/film-<vai>.md                                                               # subagent theo vai
│   └── agent-memory/<agent>/MEMORY.md                                                     # bài học (memory: project)
├── styles/<style-id>/            # style pack: STYLE.md, style.yaml, prompts/, motion.md, sound.md, examples.md
├── series/<series>/              # CHỈ CHỮ: SERIES.md, characters/, locations/, ep<NN>-<slug>/
├── templates/episode/            # EPISODE.md, budget.yaml, shots.csv, prompts.csv mẫu
├── formats/                      # CINECODE_FORMATS (định dạng cinecode đã lưu, xem §9)
├── tools/                        # ark.py, doctor.sh, check_episode.py, bundle.py, layers/, compose/
├── tests/                        # python3 -m unittest discover -s tests
├── lambda/ · docs/
└── out/<series>/ep<NN>/          # git bỏ qua: plates/, clips/, film/, renders/, ledger.csv
```

## 2. Đặt tên

| Loại | Mẫu | Ví dụ |
|---|---|---|
| Skill lõi | `film-<bước>` (ASCII, kebab-case) | `film-script` |
| Skill theo kỹ thuật dựng | `film-compose-<kỹ thuật>` | `film-compose-3d` |
| Agent | `film-<vai>` | `film-reviewer` |
| Style id | kebab-case không dấu | `thuy-mac`, `moc-ban` |
| Series / nhân vật / bối cảnh | slug không dấu | `son-hai-kinh`, `bac-thi`, `nui-co` |
| Thư mục tập (chữ) | `series/<series>/ep<NN>-<slug>/` | `series/son-hai-kinh/ep01-bac-thi/` |
| Thư mục tập (media) | `out/<series>/ep<NN>/` | `out/son-hai-kinh/ep01/` |
| Shot id | `s<NN>` (2 chữ số, tăng dần) | `s03` |
| Lớp tranh | `ep<NN>_s<NN>_<lớp>_<chủ-thể>_v<NN>.<png\|jpg>` | `ep01_s03_L4_bac-thi_v02.png` |
| Mã lớp | `L1` nền · `L2` tầng giữa · `L3` tiền cảnh · `L4` nhân vật · `P<n>-<bộ-phận>` · `FX` | `P1-duoi` |
| Clip AI | `ep<NN>_s<NN>_<model-ngắn>_v<NN>.mp4` | `ep01_s03_seedance25_v01.mp4` |
| Bản dựng | `ep<NN>_<draft\|final>_v<NN>.mp4` | `ep01_draft_v03.mp4` |

Regex chuẩn (dùng trong `tools/check_episode.py`):
- lớp: `^ep\d{2}_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_[a-z0-9-]+_v\d{2}\.(png|jpg)$`
- clip: `^ep\d{2}_s\d{2}_[a-z0-9]+_v\d{2}\.mp4$`
- bản dựng: `^ep\d{2}_(draft|final)_v\d{2}\.mp4$`

Phiên bản luôn tăng, không ghi đè. Media lưu trong `out/<series>/ep<NN>/{plates,clips,renders}/`.

## 3. Style pack: `styles/<id>/style.yaml`

```yaml
id: thuy-mac                      # = tên thư mục
name: Thủy mặc
status: stable                    # stable | draft
base: cinecode:ink-wash           # recipe cinecode kế thừa (KIT/styles/<id>.md) hoặc null
style_block: >-                   # câu phong cách đặt đầu MỌI prompt ảnh
  ...
negative: [text, signature, ...]  # gửi qua --negative (chưa xác minh model có áp dụng) VÀ viết thành ràng buộc trong prompt
palette: {ink: "#1A1714", ...}    # tên -> hex
light: "upper-left, warm low sun on the right"
matte:                            # cách tách alpha theo lớp (tools/layers/matte.py)
  key_bg: "#FF00FF"               # nền phẳng khi method=chroma
  paper_bg: "#FFFFFF"             # nền phẳng khi method=luminance
  per_layer:                      # method: none | luminance | chroma | rembg ; low/high: ngưỡng cleanup 0-255
                                  # bg (tuỳ chọn): màu nền phẳng mà prompt của lớp yêu cầu (mặc định: key_bg với chroma,
                                  # paper_bg với luminance; rembg nên dùng nền phẳng sáng, ghi rõ ở đây)
    L1: {method: none}
    L2: {method: luminance, low: 8, high: 245}
    L3: {method: luminance, low: 8, high: 245}
    L4: {method: rembg, low: 60, high: 200, bg: "#FFFFFF"}
    P:  {method: rembg, low: 60, high: 200, bg: "#FFFFFF"}
layers:                           # quy cách tạo ảnh
  L1: {size: 2K, opaque: true, note: "..."}
  L2: {size: 2K, note: "..."}
  L3: {size: 2K, note: "..."}
  L4: {size: 2K, note: "..."}
  P:  {size: 2K, note: "..."}
models: {image: seedream-5-0-lite-260128, draft: dola-seedream-5-0-flash-260915,
         pro: dola-seedream-5-0-pro-260628, video: dreamina-seedance-2-5-260628}
motion: [mist-bands, embers, sun-glow, strip-warp]   # id module trong tools/compose/
sound: {scale: "D minor pentatonic", instruments: [...], notes: "..."}
type: {latin: "Cormorant Garamond", cjk: "Noto Serif CJK TC"}
```
Prompt mẫu trong `styles/<id>/prompts/*.txt` dùng chỗ trống `{style_block}`, `{subject}`, `{constraints}`, `{light}`.
Thêm trường phái mới = chép `styles/_template/`, không sửa skill.

## 4. Series và tập

`series/<series>/SERIES.md` (đầu file là khối YAML):
```yaml
---
series: son-hai-kinh
title: Sơn Hải Kinh
style: thuy-mac
audience: ...
language: vi
format: {width: 1920, height: 1080, fps: 24}
---
```
`characters/<slug>/CHARACTER.md`: nguồn nguyên văn + link, cách đọc tên, bảng giải phẫu (mỗi đặc điểm một dòng, ghi nguồn hay diễn giải), prompt khóa, link Drive ảnh khóa.

Thư mục tập `series/<series>/ep<NN>-<slug>/`:

| File | Ai viết | Nội dung |
|---|---|---|
| `EPISODE.md` | đạo diễn | trạng thái tập (§5). **Không đặt tên `STATE.md`** – tên đó thuộc cinecode |
| `budget.yaml` | đạo diễn | trần chi phí (§7) |
| `research.md` | film-researcher | nguyên văn, link, cách đọc tên |
| `script.md` | film-writer | lời bình theo chương, mỗi câu có mốc `[mm:ss]`. Mọi dòng không phải tiêu đề `#`, dòng trống, chú thích `<!-- -->` hay trích dẫn `>` đều bị coi là lời bình: ghi chú, bảng, metadata phải đặt trong `>` |
| `shots.csv` | film-writer | §6 |
| `prompts.csv` | film-art-director / film-plate-maker | §6 |
| `anchors.json` | film-plate-maker | điểm neo theo file lớp |
| `review/` | film-reviewer, compositor | `qc-<v>.md`, `sound-audit.md`, `check-<v>.txt` |
| `publish.md` | film-publisher | tiêu đề, mô tả, chương, credit, tag |

## 5. `EPISODE.md`

Khối YAML đầu file + phần chữ:
```yaml
---
series: son-hai-kinh
episode: 1
slug: bac-thi
style: thuy-mac
length_s: 60
stage: 2                 # 0..11 theo docs/WORKFLOW.md
gates: {G1: null, G2: null, G3: null, G4: null}   # ngày duyệt YYYY-MM-DD hoặc null
media: out/son-hai-kinh/ep01
drive: "AI Film Lab/son-hai-kinh/ep01"
---
```
Các mục chữ bắt buộc: `## Ghi chú người dùng (nguyên văn)`, `## Đã khóa (không làm lại)`, `## Việc tiếp theo`, `## Nhật ký` (mỗi khâu một dòng: ngày, khâu, kết quả, commit).

## 6. CSV (RFC 4180, UTF-8, có header, trường có dấu phẩy/xuống dòng phải đặt trong ngoặc kép)

`shots.csv`:
`shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of`
- `shot` = `s<NN>`; `from_s`/`to_s` số giây (thập phân được), liên tục: `from_s` = `to_s` shot trước; shot đầu từ 0; shot cuối kết thúc = `length_s`.
- Thời lượng mỗi shot 3–13 s. `shot_size` ∈ `extreme-wide, wide, medium, close, extreme-close, insert`.
- `camera` = một chuyển động (`static, push-in, pull-out, pan-left, pan-right, tilt-up, tilt-down, drift, handheld`).
  Hai shot liền nhau không cùng cả `shot_size` lẫn `camera`.
- `layers` = mã lớp cách nhau bởi `;` (vd. `L1;L2;L3;L4;P1-duoi`). `code_motion`, `ai_motion` cách nhau bởi `;`; `ai_motion` trống = không dùng Seedance.
- `reuse_of` = shot id dùng lại tài sản, hoặc trống.

`prompts.csv`:
`file,shot,layer,model,size,prompt_file,refs,seed,usage,approved,drive_link`
- `file` theo quy ước tên §2; `prompt_file` đường dẫn tương đối tới file prompt đã dùng (lưu trong thư mục tập, `prompts/`).
- `refs` cách nhau bởi `;`; `usage` = JSON usage Ark nguyên văn; `approved` ∈ `yes, no, ''`.

## 7. Ngân sách và ledger (`tools/ark.py --budget/--ledger`)

`budget.yaml`:
```yaml
images: 40               # tổng số ảnh tối đa (mọi model)
video_seconds: 60        # tổng giây video tối đa
models:                  # (tuỳ chọn) trần riêng theo model, đơn vị ảnh hoặc giây video
  dola-seedream-5-0-pro-260628: 6
```
`ledger.csv` (đặt ở `out/<series>/ep<NN>/ledger.csv`), header:
`ts,kind,model,size,seconds,count,status,out,task_id,usage,agent,note`
- `kind` ∈ `image, video`; `status` ∈ `ok, failed, cut-502, refused-budget`; `ts` ISO 8601 UTC; `agent` lấy từ biến môi trường `FILM_AGENT` (trống = phiên chính).
- Mỗi lần gọi API tạo ảnh/video (kể cả lỗi) ghi đúng một dòng; ghi bằng khoá file (`fcntl.flock`) vì agent chạy song song.
- Trước khi gọi API: cộng ledger (`status` ∈ ok, failed, cut-502 – mọi lần có thể đã bị tính phí) + yêu cầu hiện tại; vượt bất kỳ trần nào → từ chối, ghi `refused-budget`, thoát mã 3.
- Request 502 bị proxy cắt: ghi `cut-502`, không thử lại.
- Giới hạn đã biết: khoá chỉ bao quanh lúc đọc/ghi ledger, không giữ trong lúc gọi API, nên N agent chạy song song có thể
  vượt trần tối đa N−1 request. Chấp nhận ở v1 (tối đa 3 agent tạo ảnh song song, §10); đặt trần có dư tương ứng.
- File bắt buộc theo khâu (`tools/check_episode.py`): `script.md`, `shots.csv` từ khâu 3; `prompts.csv` từ khâu 5
  (được viết dần từ khâu 3). Trước đó thiếu file chỉ là WARN.

## 8. Quy trình và cổng duyệt
Xem `docs/WORKFLOW.md` (khâu 0–11, cổng G1–G4). Cổng duyệt luôn ở phiên chính; agent không hỏi người dùng, không tự qua cổng.

## 9. Lưu trữ
- Chữ: git. Media: `out/` (git bỏ qua) – mất khi container bị thu hồi.
- Lưu Drive theo **gói mỗi shot**: `python3 tools/bundle.py out/<series>/ep<NN> --shot s03` → một file zip, một lần duyệt tải lên
  Drive `AI Film Lab/<series>/ep<NN>/<YYYY-MM-DD>/`. Bản dựng duyệt (`renders/*.mp4`) tải lên riêng từng file.
- cinecode lưu định dạng ở `~/.cinecode/formats`; hook đặt `CINECODE_FORMATS=<repo>/formats` để định dạng sống qua các phiên.

## 10. Quyết định cho issue #1–#7 (v1.0.0)
| Đề xuất | Quyết định |
|---|---|
| Style pack tự viết motion/sound | Kế thừa recipe cinecode qua `base:`; style pack chỉ ghi phần riêng (prompt Seedream, lớp, matte, model) |
| `STATE.md` cho tập | Đổi thành `EPISODE.md` |
| `key_bg #FF00FF` + rembg cho mọi lớp | `matte.per_layer`: thủy mặc dùng `luminance` cho L2/L3 (giữ vệt mực loang), `rembg` cho L4/P |
| Ngân sách ghi bằng prompt | `ark.py --budget/--ledger` chặn trong công cụ |
| `cost_note` | `usage` JSON nguyên văn (API không trả tiền) |
| Lưu Drive từng file | Gói zip theo shot (`tools/bundle.py`); S3 khi Lambda sẵn sàng |
| Reviewer có Bash giới hạn | Reviewer không có Bash; số đo do `tools/check_episode.py` ghi ra `review/check-<v>.txt` |
| Song song plate-maker | Tối đa 3 agent song song; ledger dùng khoá file |
| Kiểm tra kịch bản bằng mắt | `tools/check_episode.py` kiểm schema, thời lượng, nhịp, tên file |
| Ảnh `--ref` nặng | `ark.py` nén ref thành JPEG q90, cạnh ≤ 2048 trước khi gửi |
| ctext.org | Chặn truy cập tự động; dùng zh.wikisource.org |
