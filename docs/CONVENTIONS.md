# Quy ước và schema (v1)

Hợp đồng chung cho mọi skill, agent, công cụ trong repo. Đổi schema = đổi file này trước, rồi mới đổi code.
Quyết định thiết kế được ghi ở §10.

**Repo = lõi dùng lại** (công cụ, skill, agent, style pack, mẫu, quy trình, cài đặt). **Dữ liệu của từng dự án phim**
(kinh thư, nhân vật, bối cảnh, nghiên cứu, kịch bản, shot list, `EPISODE.md`, ngân sách, prompt, tiến độ, tài liệu gốc,
media) **nằm trên Google Drive** `ClaudeFilmLab/<ProjectName>/` (§11) và không bao giờ được commit. Trong phiên, dự án
được kéo về bản làm việc `projects/<project>/` (git bỏ qua); media ở `out/<project>/` (git bỏ qua).

## 1. Cấu trúc thư mục

```
claude-film-lab/
├── CLAUDE.md · README.md · CHANGELOG.md · requirements.txt
├── .claude/
│   ├── settings.json · hooks/session-start.sh
│   ├── skills/film-pipeline/ · film-script/ · film-prompt-layers/ · film-compose-shot/   # skill lõi
│   ├── agents/film-<vai>.md                                                               # subagent theo vai
│   └── agent-memory/<agent>/MEMORY.md                                                     # bài học (memory: project; agent cần Write/Edit trong tools)
├── styles/<style-id>/            # style pack dùng lại: STYLE.md, style.yaml, prompts/, motion.md, sound.md, examples.md
├── templates/episode/            # EPISODE.md, budget.yaml, shots.csv, prompts.csv mẫu
├── templates/project/            # PROJECT.md, SERIES.md, README_CauTruc.md, TienDo_SanXuat.csv mẫu (§11)
├── formats/                      # CINECODE_FORMATS (định dạng cinecode đã lưu, xem §9)
├── tools/                        # ark.py, doctor.sh, check_episode.py, bundle.py, drive_sync.py, episode_id.py, rename_episode.py, layers/, compose/
├── tests/                        # python3 -m unittest discover -s tests
├── lambda/ · docs/
├── projects/<project>/           # git bỏ qua – bản làm việc CHỈ CHỮ kéo từ Drive (§11):
│   ├── PROJECT.md                #   manifest: slug, tên, style, ID thư mục Drive
│   ├── SERIES.md · characters/<c>/CHARACTER.md · locations/<l>/LOCATION.md · style/
│   ├── <thư mục tập>/            #   ep<NN>-<slug> hoặc q<NN>-t<NN>-<slug> (§2): EPISODE.md, budget.yaml, script.md, ...
│   └── sources/                  #   tài liệu gốc dạng chữ, kéo về khi cần
└── out/<project>/                # git bỏ qua – media: <id>/{plates,clips,film,renders,bundles}/, <id>/ledger.csv,
                                  #   ảnh khóa characters/<c>/, locations/<l>/, tài liệu gốc dạng ảnh sources/
```
`<project>` = slug dự án (ASCII kebab-case, vd. `son-hai-kinh`), cũng là giá trị `series:` trong `SERIES.md`/`EPISODE.md`.
`<ProjectName>` = tên thư mục dự án trên Drive (PascalCase không dấu, vd. `SonHaiKinh`). Một dự án = một series phim.

## 2. Đặt tên

**Mã tập `<id>`** – hai cách đánh số, đều hợp lệ (`tools/episode_id.py`):

| Dự án | `<id>` (thư mục media, tiền tố file) | Thư mục tập (chữ) | `EPISODE.md` | Hiển thị (YouTube, tiến độ) |
|---|---|---|---|---|
| không chia quyển | `ep<NN>` – `ep01` | `ep<NN>-<slug>` – `ep01-bac-thi` | `episode: 1` | Tập 1 |
| chia quyển (quyển → nhiều tập, đánh số tập trong quyển) | `q<NN>t<NN>` – `q01t01` | `q<NN>-t<NN>-<slug>` – `q01-t01-nam-son-kinh` | `book: 1`, `episode: 1` | Quyển 1 · Tập 1 |

Một dự án chọn một cách và giữ nguyên. Thư mục tập, `book`/`episode`, thư mục media và tiền tố mọi file phải cùng một
mã (`check_episode.py` báo ERROR khi lệch). Đổi mã một tập đang làm (vd. `ep01` → `q01t01`):
`python3 tools/rename_episode.py ep01 q01t01 --project-dir projects/<p>/ep01-<slug> --media out/<p>/ep01`
(chạy thử, in từng bước) rồi thêm `--apply`; công cụ đổi tên thư mục tập, thư mục media, mọi file/thư mục bắt đầu bằng
`ep01_`, sửa tham chiếu trong file chữ (prompts.csv, shots.csv, anchors.json, `prompts/*.txt`, ledger.csv, khoá
`drive.folders` trong `PROJECT.md`) và `book`/`episode`/`media`/`drive` của `EPISODE.md`. Trên Drive đổi tên thư mục
`03_KichBan`/`04_SanXuat`/`05_ThanhPham/<thư mục tập>` bằng `update_file` (ID giữ nguyên), rồi đẩy file chữ đã đổi.

| Loại | Mẫu | Ví dụ |
|---|---|---|
| Skill lõi | `film-<bước>` (ASCII, kebab-case) | `film-script` |
| Skill theo kỹ thuật dựng | `film-compose-<kỹ thuật>` | `film-compose-3d` |
| Agent | `film-<vai>` | `film-reviewer` |
| Style id | kebab-case không dấu | `thuy-mac`, `moc-ban` |
| Dự án (series) / nhân vật / bối cảnh | slug không dấu | `son-hai-kinh`, `bac-thi`, `nui-co` |
| Thư mục dự án trên Drive | `ClaudeFilmLab/<ProjectName>/` (PascalCase không dấu) | `ClaudeFilmLab/SonHaiKinh/` |
| Bản làm việc dự án | `projects/<project>/` (git bỏ qua) | `projects/son-hai-kinh/` |
| Thư mục tập (chữ) | `projects/<project>/ep<NN>-<slug>/` · `projects/<project>/q<NN>-t<NN>-<slug>/` | `projects/son-hai-kinh/ep01-bac-thi/` · `projects/son-hai-kinh/q01-t01-nam-son-kinh/` |
| Thư mục tập (media) | `out/<project>/<id>/` | `out/son-hai-kinh/ep01/` · `out/son-hai-kinh/q01t01/` |
| Shot id | `s<NN>` (2 chữ số, tăng dần) | `s03` |
| Lớp tranh | `<id>_s<NN>_<lớp>_<chủ-thể>_v<NN>.<png\|jpg>` | `ep01_s03_L4_bac-thi_v02.png` · `q01t01_s03_L4_bac-di_v02.png` |
| Mã lớp | `L1` nền · `L2` tầng giữa · `L3` tiền cảnh · `L4` nhân vật · `P<n>-<bộ-phận>` · `FX` | `P1-duoi` |
| Clip AI | `<id>_s<NN>_<model-ngắn>_v<NN>.mp4` | `ep01_s03_seedance25_v01.mp4` · `q01t01_s03_seedance25_v01.mp4` |
| Bản dựng | `<id>_<draft\|final>_v<NN>.mp4` | `ep01_draft_v03.mp4` · `q01t01_draft_v01.mp4` |

Regex chuẩn (dùng trong `tools/check_episode.py`; `<ID>` = `(?:ep\d{2}|q\d{2}t\d{2})`):
- mã tập: `^(?:ep\d{2}|q\d{2}t\d{2})$`; thư mục tập: `^(?:ep\d{2}|q\d{2}-t\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$`
- lớp: `^<ID>_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_[a-z0-9-]+_v\d{2}\.(png|jpg)$`
- clip: `^<ID>_s\d{2}_[a-z0-9]+_v\d{2}\.mp4$`
- bản dựng: `^<ID>_(draft|final)_v\d{2}\.mp4$`
- khung đầu Seedance (trong `clips/`): `^<ID>_s\d{2}_start_v\d{2}\.png$`
- khung của clip: thư mục `clips/<tên clip không đuôi>/` (tên khớp regex clip, bỏ `.mp4`) chỉ chứa `^\d{6}\.png$`
  và thư mục con tùy chọn `raw/` (khung gốc tách bằng ffmpeg, cũng `^\d{6}\.png$`)
- dòng clip trong `prompts.csv`: `file` theo regex clip, `layer` = mã lớp mà clip thay (thường `L4`), `shot` khớp tên file

Phiên bản luôn tăng, không ghi đè. Media lưu trong `out/<project>/<id>/{plates,clips,renders}/`.
Khung của clip đã tách nền: `clips/<tên clip không đuôi>/000001.png` (6 chữ số, bắt đầu từ 1); khung gốc trước khi
tách nền: `clips/<tên clip không đuôi>/raw/000001.png`.
Thư mục film cinecode của tập: `out/<project>/<id>/film/<tên>/` (có `STATE.md` riêng của cinecode).

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
  paper_bg: "#FFFFFF"             # nền phẳng prompt yêu cầu khi method=luminance; matte.py tự ước lượng màu giấy
                                  # thật từ viền ảnh (--paper auto, mặc định), paper_bg chỉ để tham khảo
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
motion: [mist-bands, embers, sun-glow, strip-warp]   # id trong sổ đăng ký tools/compose/motions.json
sound: {scale: "D minor pentatonic", instruments: [...], notes: "..."}
type: {latin: "Cormorant Garamond", cjk: "Noto Serif CJK TC"}
```
Prompt mẫu trong `styles/<id>/prompts/*.txt` dùng chỗ trống `{style_block}`, `{subject}`, `{constraints}`, `{light}`.
Thêm trường phái mới = chép `styles/_template/`, không sửa skill.

## 4. Dự án (series) và tập

Đường dẫn dưới đây là của bản làm việc `projects/<project>/`; nơi lưu thật trên Drive xem bảng ánh xạ §11.3.
Dự án mới: chép `templates/project/` (§11.5).

`projects/<project>/PROJECT.md`: manifest dự án (§11.2). `projects/<project>/SERIES.md` (đầu file là khối YAML):
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
`series:` = slug dự án = tên thư mục `projects/<project>/`. `characters/<slug>/CHARACTER.md`: nguồn nguyên văn + link,
cách đọc tên, bảng giải phẫu (mỗi đặc điểm một dòng, ghi nguồn hay diễn giải), prompt khóa, link Drive ảnh khóa.
`locations/<slug>/LOCATION.md`: như CHARACTER.md cho bối cảnh. `style/`: ghi chú phong cách riêng của dự án và prompt
mẫu đã duyệt (style pack dùng chung vẫn ở `styles/<id>/` trong repo).

Thư mục tập `projects/<project>/ep<NN>-<slug>/` (dự án chia quyển: `projects/<project>/q<NN>-t<NN>-<slug>/`, §2):

| File | Ai viết | Nội dung |
|---|---|---|
| `EPISODE.md` | đạo diễn | trạng thái tập (§5). **Không đặt tên `STATE.md`** – tên đó thuộc cinecode |
| `budget.yaml` | đạo diễn | trần chi phí (§7) |
| `research.md` | film-researcher | nguyên văn, link, cách đọc tên; tài liệu gốc dùng tới ghi theo tên file trong `01_TaiLieuGoc/` (§11.4) |
| `script.md` | film-writer | lời bình theo chương, mỗi câu có mốc `[mm:ss]`. Mọi dòng không phải tiêu đề `#`, dòng trống, chú thích `<!-- -->` hay trích dẫn `>` đều bị coi là lời bình: ghi chú, bảng, metadata phải đặt trong `>` |
| `shots.csv` | film-writer | §6 |
| `prompts.csv` | film-art-director / film-plate-maker | §6 |
| `anchors.json` | film-plate-maker | điểm neo theo file lớp: `{"<file lớp>": {"<tên>": [x, y]}}` (pixel); vùng chữ nhật lưu bằng cặp điểm `<tên>_tl` / `<tên>_br`; `tools/layers/anchors.py` ghi, `tools/compose` đọc |
| `review/` | film-reviewer, compositor | `qc-<v>.md`, `sound-audit.md`, `check-<v>.txt` |
| `publish.md` | film-publisher | tiêu đề, mô tả, chương, credit, tag |
| `prompts/` | film-art-director / film-animator | prompt đã dùng, mỗi ảnh/clip một file `.txt` |

## 5. `EPISODE.md`

Khối YAML đầu file + phần chữ:
```yaml
---
series: son-hai-kinh
book: 1                  # tuỳ chọn: chỉ khi dự án chia quyển; bỏ dòng này với cách đánh số ep<NN>
episode: 1               # số tập (trong quyển nếu có book)
slug: bac-thi
style: thuy-mac
length_s: 60
stage: 2                 # 0..11 theo docs/WORKFLOW.md
gates: {G1: null, G2: null, G3: null, G4: null}   # ngày duyệt YYYY-MM-DD hoặc null
media: out/son-hai-kinh/q01t01
drive: "ClaudeFilmLab/SonHaiKinh/03_KichBan/q01-t01-bac-thi"   # thư mục chữ của tập trên Drive (§11)
---
```
`series` = slug dự án; mã tập `<id>` = `q<book>t<episode>` khi có `book`, không thì `ep<episode>` (2 chữ số);
`media` = `out/<project>/<id>`; `drive` = `ClaudeFilmLab/<ProjectName>/03_KichBan/<thư mục tập>` (`ep<NN>-<slug>` hoặc
`q<NN>-t<NN>-<slug>`; ID thư mục lấy từ `PROJECT.md`, không tìm theo tên). `media`/`drive` lệch quy ước → WARN;
`book`/`episode` lệch tên thư mục tập, hoặc thư mục media/tiền tố file khác mã tập → ERROR.
Các mục chữ bắt buộc: `## Ghi chú người dùng (nguyên văn)`, `## Đã khóa (không làm lại)`, `## Việc tiếp theo`, `## Nhật ký`
(mỗi khâu một dòng: ngày, khâu, kết quả, giờ đẩy Drive – `chưa` nếu chưa đẩy).

## 6. CSV (RFC 4180, UTF-8, có header, trường có dấu phẩy/xuống dòng phải đặt trong ngoặc kép)

`shots.csv`:
`shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of`
- `shot` = `s<NN>`; `from_s`/`to_s` số giây (thập phân được), liên tục: `from_s` = `to_s` shot trước; shot đầu từ 0; shot cuối kết thúc = `length_s`.
- Thời lượng mỗi shot 3–13 s. `shot_size` ∈ `extreme-wide, wide, medium, close, extreme-close, insert`.
- `camera` = một chuyển động (`static, push-in, pull-out, pan-left, pan-right, tilt-up, tilt-down, drift, handheld`).
  Hai shot liền nhau không cùng cả `shot_size` lẫn `camera`.
- `layers` = mã lớp cách nhau bởi `;` (vd. `L1;L2;L3;L4;P1-duoi`). `code_motion`, `ai_motion` cách nhau bởi `;`; `ai_motion` trống = không dùng Seedance.
- `reuse_of` = shot id dùng lại tài sản, hoặc trống.
- `code_motion` và `motion:` của style dùng id trong `tools/compose/motions.json` (mist-bands, embers, sun-glow,
  strip-warp, eyelid, breath, parallax, push-in); id lạ là WARN.

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
`ledger.csv` (đặt ở `out/<project>/<id>/ledger.csv`; bản gốc trên Drive `04_SanXuat/<thư mục tập>/ledger.csv`, kéo về đầu
phiên trước khi tạo ảnh để trần ngân sách tính đúng, §11.6), header:
`ts,kind,model,size,seconds,count,status,out,task_id,usage,agent,note`
- `kind` ∈ `image, video`; `status` ∈ `pending, ok, failed, cut-502, refused-budget`; `ts` ISO 8601 UTC; `agent` lấy từ biến môi trường `FILM_AGENT` (trống = phiên chính).
- Ngân sách không phải tuỳ chọn: `ark.py image|video` từ chối (thoát mã 2, không gọi API, không ghi ledger) nếu thiếu
  budget **hoặc** ledger (cờ `--budget/--ledger` hoặc env `FILM_BUDGET/FILM_LEDGER`); `--budget` không có ledger là lỗi.
  Ngoại lệ duy nhất: cờ `--no-budget` (in một dòng cảnh báo, ledger tuỳ chọn) – chỉ để thử nhanh ở phiên chính, agent không dùng.
- Mỗi request ghi dòng bằng khoá file (`fcntl.flock`, agent chạy song song):
  - trước lệnh POST tạo ảnh/video: một dòng `pending`, `note` = `req=<uuid4 hex>`;
  - video: có task id là ghi ngay dòng `pending` thứ hai có `task_id` (cùng `req=`) và in task id ra – còn lại cả khi bị SIGKILL;
  - khi xong: một dòng cuối `ok`, `failed` hoặc `cut-502` cùng `req=` (`note` = `req=<id>; <chi tiết>`).
  SIGTERM/SIGINT → dòng `failed` (`interrupted by SIGTERM`, video có `task_id`); SIGKILL → chỉ còn `pending`, vẫn tính là đã tính phí.
- Cách đếm: gom các dòng theo `req=` (dòng không có `req=` nhưng có `task_id` thì gom theo `task_id`); mỗi request tính
  **một lần** theo dòng cuối (`ok/failed/cut-502`) mới nhất, chưa có dòng cuối thì theo dòng `pending` (coi như đã tính phí).
  Dòng không có cả `req=` lẫn `task_id` (ledger cũ) mỗi dòng tính một lần như trước. `refused-budget` không tính.
- Trước khi gọi API: tổng đã dùng + yêu cầu hiện tại; vượt bất kỳ trần nào → từ chối, ghi `refused-budget` (không có `pending`), thoát mã 3.
- Kiểm và giữ chỗ là **một bước nguyên tử**: một khoá `LOCK_EX` trên `ledger.csv` bao quanh việc đọc ledger, cộng tổng
  và ghi dòng `pending` (hoặc `refused-budget`), rồi mới mở khoá. Việc chậm (nén ảnh `--ref`, đọc khung đầu, tạo thư mục,
  đọc `budget.yaml`) làm trước khi lấy khoá; lệnh gọi API làm sau khi mở khoá (khoá không giữ trong lúc gọi API).
  Nhờ vậy N agent chạy song song trong cùng container không vượt trần.
- Request 502 bị proxy cắt: ghi `cut-502`, không thử lại.
- Thư mục chứa file đầu ra được tạo trước khi kiểm ngân sách và gọi API. Lưu ảnh lỗi → `failed`, note `save-failed`;
  tải video lỗi → `failed`, note `download-failed` (cả hai vẫn tính phí); ark.py in URL đầy đủ và task id để tải tay (link có hạn).
- `ark.py video --resume-task <task_id> [out.mp4] --ledger L`: không tạo task, không kiểm ngân sách, không ghi `pending`;
  poll tiếp + tải về, ghi dòng cuối cho task đó với `req=` lấy từ ledger (`out` mặc định lấy từ ledger). Cần ledger, không cần budget.
- File bắt buộc theo khâu (`tools/check_episode.py`): `script.md`, `shots.csv` từ khâu 3; `prompts.csv` từ khâu 5
  (được viết dần từ khâu 3). Trước đó thiếu file chỉ là WARN.

## 8. Quy trình và cổng duyệt
Xem `docs/WORKFLOW.md` (khâu 0–11, cổng G1–G4). Cổng duyệt luôn ở phiên chính; agent không hỏi người dùng, không tự qua cổng.

## 9. Lưu trữ
- **Mã lõi** (repo này): git, commit + push. **Dữ liệu dự án** (chữ và media): Google Drive `ClaudeFilmLab/<ProjectName>/`
  là nguồn gốc (§11); `projects/<project>/` (chữ) và `out/<project>/` (media) chỉ là bản làm việc, git bỏ qua, mất khi
  container bị thu hồi → đẩy chữ lên Drive sau mỗi khâu và trước khi dừng phiên (§11.6).
- Không bao giờ commit dữ liệu dự án vào repo (kể cả "tạm"). Ví dụ trong style pack (`styles/<id>/examples.md`) chỉ
  chép prompt đã duyệt, không chép kịch bản hay kinh thư.
- Media lưu Drive theo **gói mỗi shot**: `python3 tools/bundle.py out/<project>/<id> --shot s03` → một file zip, một lần
  duyệt tải lên `ClaudeFilmLab/<ProjectName>/04_SanXuat/<thư mục tập>/<YYYY-MM-DD>/`. Bản nháp duyệt
  (`renders/*_draft_*.mp4`) cũng vào `04_SanXuat/…/<YYYY-MM-DD>/`; bản cuối (`renders/*_final_*.mp4`) vào
  `05_ThanhPham/<thư mục tập>/`, tải riêng từng file.
- cinecode lưu định dạng ở `~/.cinecode/formats`; hook đặt `CINECODE_FORMATS=<repo>/formats` để định dạng sống qua các phiên.

## 10. Quyết định thiết kế
| Đề xuất | Quyết định |
|---|---|
| Kinh thư, kịch bản, tập phim nằm trong repo (`series/`) | **Repo chỉ là lõi dùng lại**; dữ liệu mỗi dự án nằm trên Drive `ClaudeFilmLab/<ProjectName>/`, bản làm việc `projects/<project>/` git bỏ qua (§11, sau v1.0.0) |
| Style pack tự viết motion/sound | Kế thừa recipe cinecode qua `base:`; style pack chỉ ghi phần riêng (prompt Seedream, lớp, matte, model) |
| `STATE.md` cho tập | Đổi thành `EPISODE.md` |
| `key_bg #FF00FF` + rembg cho mọi lớp | `matte.per_layer`: thủy mặc dùng `luminance` cho L2/L3 (giữ vệt mực loang), `rembg` cho L4/P |
| Ngân sách ghi bằng prompt | `ark.py --budget/--ledger` chặn trong công cụ |
| `cost_note` | `usage` JSON nguyên văn (API không trả tiền) |
| Lưu Drive từng file | Media: gói zip theo shot (`tools/bundle.py`); S3 khi Lambda sẵn sàng. File chữ của dự án: từng file, bản mới thay bản cũ theo §11.6 |
| Reviewer có Bash giới hạn | Reviewer không có Bash; số đo do `tools/check_episode.py` ghi ra `review/check-<v>.txt` |
| Song song plate-maker | Tối đa 3 agent song song; ledger dùng khoá file |
| Kiểm tra kịch bản bằng mắt | `tools/check_episode.py` kiểm schema, thời lượng, nhịp, tên file |
| Ảnh `--ref` nặng | `ark.py` nén ref thành JPEG q90, cạnh ≤ 2048 trước khi gửi |
| ctext.org | Chặn truy cập tự động; dùng zh.wikisource.org |

## 11. Dự án trên Drive

Mọi dữ liệu của một dự án phim nằm trên Google Drive, dưới thư mục gốc của lab `ClaudeFilmLab`
(ID `19yQarw7ATu90uzXjboGP4sy5FzlQhd0y`), mỗi dự án một thư mục. Drive là **nguồn gốc**; `projects/<project>/` và
`out/<project>/` chỉ là bản làm việc trong container. Đồng bộ do Claude làm bằng connector Google Drive
(`search_files`, `download_file_content`, `create_file`, `update_file`); không có CLI. Việc nhớ thì giao cho
`tools/drive_sync.py` (cục bộ, không gọi mạng): chụp dấu sau khi kéo, lập danh sách lệnh connector cho file đã đổi,
ghi lại file đã đẩy (§11.6).

### 11.1 Cấu trúc

```
ClaudeFilmLab/<ProjectName>/            PascalCase không dấu, vd. SonHaiKinh
├── 00_QuanLy/      PROJECT.md (manifest, §11.2) · README_CauTruc (Google Doc cho người đọc) · TienDo_SanXuat (Google Sheet, mỗi tập một dòng)
├── 01_TaiLieuGoc/  _ChoPhanLoai/ (hộp thư đến) · SachThamKhao/<MaSach>_<NoiDung>/ · NguyenVan/ · HinhAnhThamKhao/ · DanhMuc.csv
├── 02_KinhThu/     SERIES.md · pronunciation.csv · NhanVat/<slug>/CHARACTER.md (+ ảnh khóa) · BoiCanh/<slug>/LOCATION.md (+ ảnh khóa) · PhongCach/
├── 03_KichBan/<thư mục tập>/            EPISODE.md, budget.yaml, research.md, script.md, shots.csv, prompts.csv, anchors.json, prompts/, review/, publish.md
├── 04_SanXuat/<thư mục tập>/            ledger.csv · <YYYY-MM-DD>/ gói shot (tools/bundle.py), bản nháp đã duyệt
├── 05_ThanhPham/<thư mục tập>/          bản cuối, thumbnail, tài liệu xuất bản
└── 99_LuuTru/      bản cũ và thứ bỏ đi (chuyển vào đây, không xoá)
```
- Thư mục cấp 1 đánh số `NN_TenKhongDau` để giữ thứ tự; `<thư mục tập>` dùng đúng tên thư mục tập của bản làm việc
  (`ep<NN>-<slug>` hoặc `q<NN>-t<NN>-<slug>`, §2) ở cả `03_KichBan`, `04_SanXuat`, `05_ThanhPham`; `<id>` = mã tập.
- File chữ (`.md`, `.csv`, `.yaml`, `.json`, `.txt`) lưu **nguyên dạng**, không chuyển sang Google Docs/Sheets
  (`disableConversionToGoogleType: true`) để kéo về được y nguyên. Chỉ `README_CauTruc` (Doc) và `TienDo_SanXuat`
  (Sheet) là file Google cho người đọc.
- `HinhAnhThamKhao/` chỉ để tham khảo không khí: **không** dùng làm `--ref`, không đưa vào phim.
- `PhongCach/` giữ ghi chú phong cách riêng của dự án và prompt đã duyệt; style pack dùng chung ở `styles/<id>/` (repo).

### 11.2 `PROJECT.md` (manifest)

Đọc **đầu tiên** mỗi phiên: ánh xạ mọi đường dẫn của bản làm việc sang ID thư mục Drive. Mẫu: `templates/project/PROJECT.md`.
```yaml
---
project: son-hai-kinh            # slug: projects/<project>/, out/<project>/, series: trong SERIES.md và EPISODE.md
title: Sơn Hải Kinh
style: thuy-mac                  # style mặc định, styles/<id>/
drive:
  name: SonHaiKinh               # tên thư mục dự án trên Drive (<ProjectName>)
  lab_root: 19yQarw7ATu90uzXjboGP4sy5FzlQhd0y   # ClaudeFilmLab
  root: <ID thư mục ClaudeFilmLab/<ProjectName>>
  folders:                       # đường dẫn logic (tính từ thư mục dự án, dấu /) -> ID thư mục
    00_QuanLy: <id>
    02_KinhThu/NhanVat/bac-thi: <id>
    03_KichBan/ep01-bac-thi: <id>
    03_KichBan/ep01-bac-thi/prompts: <id>
    04_SanXuat/ep01-bac-thi: <id>
    # dự án chia quyển: 03_KichBan/q01-t01-nam-son-kinh, 04_SanXuat/q01-t01-nam-son-kinh, ...
    # ... mọi thư mục đã tạo, kể cả thư mục con
  files:                         # chỉ file Google cố định (file chữ đổi ID mỗi lần đẩy, §11.6)
    00_QuanLy/README_CauTruc: <id>
    00_QuanLy/TienDo_SanXuat: <id>
---
```
- Có ID thì dùng ID, không tìm thư mục theo tên. Tạo thư mục mới (`create_file`, mimeType
  `application/vnd.google-apps.folder`, `parentId` từ manifest) → ghi ID vào `drive.folders` ngay và đẩy `PROJECT.md`.
- Thư mục `<YYYY-MM-DD>/` trong `04_SanXuat` cũng ghi vào `folders` (`04_SanXuat/ep01-bac-thi/2026-11-10: <id>`).

### 11.3 Ánh xạ Drive ↔ bản làm việc

| Đường dẫn logic trên Drive | Bản làm việc | Kéo / đẩy |
|---|---|---|
| `00_QuanLy/PROJECT.md` | `projects/<project>/PROJECT.md` | kéo đầu tiên; đẩy khi thêm thư mục |
| `00_QuanLy/TienDo_SanXuat` (Sheet) | `projects/<project>/TienDo_SanXuat.csv` | kéo bằng xuất CSV; cập nhật sau mỗi khâu (§11.6) |
| `00_QuanLy/README_CauTruc` (Doc) | – | tạo một lần từ `templates/project/README_CauTruc.md` |
| `01_TaiLieuGoc/<…>` | chữ: `projects/<project>/sources/<…>` · ảnh, PDF: `out/<project>/sources/<…>` | kéo khi cần; chỉ thêm, không sửa file gốc |
| `01_TaiLieuGoc/DanhMuc.csv` (ngoại lệ: được sửa) | `projects/<project>/sources/DanhMuc.csv` (mẫu `templates/project/DanhMuc.csv`) | thêm một dòng cho mỗi tài liệu mới; đẩy như file chữ (§11.6) |
| `02_KinhThu/SERIES.md` | `projects/<project>/SERIES.md` | kéo đầu phiên; đẩy khi đổi |
| `02_KinhThu/pronunciation.csv` | `projects/<project>/pronunciation.csv` (bảng phát âm Hán Việt `term,doc` cho `tools/tts/vieneu_tts.py --pron`, dùng chung mọi tập; mẫu `templates/project/pronunciation.csv`) | như trên |
| `02_KinhThu/NhanVat/<c>/CHARACTER.md` | `projects/<project>/characters/<c>/CHARACTER.md` | như trên |
| `02_KinhThu/NhanVat/<c>/<ảnh khóa>` | `out/<project>/characters/<c>/` | kéo khi cần làm `--ref`; đẩy sau G2 |
| `02_KinhThu/BoiCanh/<l>/LOCATION.md` · ảnh | `projects/<project>/locations/<l>/LOCATION.md` · `out/<project>/locations/<l>/` | như nhân vật |
| `02_KinhThu/PhongCach/` | `projects/<project>/style/` | kéo đầu phiên; đẩy khi đổi |
| `03_KichBan/<thư mục tập>/` (cả `prompts/`, `review/`) | `projects/<project>/<thư mục tập>/` | kéo tập đang làm; đẩy sau mỗi khâu |
| `04_SanXuat/<thư mục tập>/ledger.csv` | `out/<project>/<id>/ledger.csv` | **kéo đầu phiên** (ngân sách cộng dồn từ ledger); đẩy sau mỗi khâu có tạo ảnh/video |
| `04_SanXuat/<thư mục tập>/<YYYY-MM-DD>/` | `out/<project>/<id>/bundles/*.zip`, `renders/*_draft_*.mp4` | chỉ đẩy, sau khi duyệt |
| `05_ThanhPham/<thư mục tập>/` | `out/<project>/<id>/renders/*_final_*.mp4`, thumbnail | chỉ đẩy, sau G4 |
| `99_LuuTru/` | – | không kéo |

Công cụ chỉ thấy bản làm việc: `check_episode.py episode projects/<project>/<thư mục tập>`,
`bundle.py out/<project>/<id>` (tự tìm `projects/<project>/<thư mục tập>/`).

### 11.4 Đặt tên tài liệu gốc

- File trong `01_TaiLieuGoc/`: `<masach>_<noidung>_<NN>_<chitiet>.<ext>`, chữ thường ASCII không dấu, trong mỗi phần
  dùng `-` (vd. `shk-banminhhoa_mucluc_03_tr002-003.jpg`, `shk-quachphac_namsonkinh_01_co-son.txt`). Thư mục sách:
  `SachThamKhao/<MaSach>_<NoiDung>/`. Giữ nguyên file gốc, không nén lại, không sửa.
- Tài liệu mới (người dùng gửi vào chat hoặc thả vào `_ChoPhanLoai/`): Claude đổi tên theo quy tắc, chuyển vào thư
  mục đúng (`update_file` với `title` và `parentId`), ghi một dòng vào `01_TaiLieuGoc/DanhMuc.csv`
  (`file,thu_muc,mo_ta,nguon,ngay_them`) và báo người dùng.
- `research.md` dẫn tài liệu gốc bằng tên file này (kèm link Drive), nguồn trên mạng bằng link + ngày truy cập.

### 11.5 Mở dự án mới (khâu 0 của dự án)

1. Người dùng chốt: tên dự án, `<project>` (slug), `<ProjectName>`, style mặc định.
2. Tạo thư mục `ClaudeFilmLab/<ProjectName>/` và cây §11.1 bằng `create_file` (folder), ghi từng ID.
3. Bản làm việc: chép `templates/project/{PROJECT.md, SERIES.md, TienDo_SanXuat.csv, pronunciation.csv}` vào
   `projects/<project>/`, điền slug, tên, style và ID. Đẩy `PROJECT.md` lên `00_QuanLy/`, `SERIES.md` và
   `pronunciation.csv` lên `02_KinhThu/` (file chữ, không chuyển đổi).
4. `README_CauTruc.md` (thay `<ProjectName>`) → `create_file` với `contentMimeType: text/markdown`, **để** chuyển sang
   Google Doc; `TienDo_SanXuat.csv` → `text/csv`, chuyển sang Google Sheet. Ghi hai ID vào `drive.files`, đẩy lại `PROJECT.md`.

### 11.6 Kéo về, đẩy lên, phiên bản mới

**Kéo (đầu mỗi phiên, trước mọi việc):**
1. `PROJECT.md`: ID thư mục lấy từ người dùng hoặc tìm một lần `parentId = '<lab_root>'` → `<ProjectName>` →
   `00_QuanLy`; tải `PROJECT.md` về `projects/<project>/PROJECT.md`.
2. Với mỗi thư mục cần (bảng §11.3: kinh thư, tập đang làm, ledger): `search_files` với
   `parentId = '<id>' and trashed = false`, tải từng file chữ (`download_file_content`, giải base64) về đúng đường dẫn;
   thư mục con chưa có trong manifest thì thêm ID vào `PROJECT.md`. `TienDo_SanXuat` tải với `exportMimeType: text/csv`.
3. Một thư mục có hai file cùng tên (lần đẩy trước bị ngắt giữa chừng): lấy file `modifiedTime` mới nhất, chuyển file
   cũ vào `99_LuuTru/` theo bước 3 của mục đẩy.
4. Chụp dấu bản vừa kéo và ghi giờ kéo (UTC):
   `python3 tools/drive_sync.py snapshot projects/<project> --include-out out/<project>` (từ thư mục gốc repo).
   Lệnh ghi `projects/<project>/.pulled.sha256` (định dạng `sha256sum`: `<hex>  <đường dẫn>`, đường dẫn như
   `find projects/<project>` in ra, media dạng `out/<project>/…`; không có file nào bắt đầu bằng `.`) và
   `projects/<project>/.pulled.at` (`2026-11-10T15:30:00Z`). Tương đương bằng shell khi không chạy được công cụ:
   `find projects/<project> -type f ! -name '.*' -print0 | sort -z | xargs -0 sha256sum > projects/<project>/.pulled.sha256`
   và `date -u +%Y-%m-%dT%H:%M:%SZ > projects/<project>/.pulled.at`. Mọi lần tải lên trong phiên ghi một dòng
   `<giờ UTC> <đường dẫn bản làm việc> <ID Drive mới>` vào `projects/<project>/.pushed.log` (`drive_sync.py record`).

**Đẩy (sau mỗi khâu, sau mỗi lần sửa theo ghi chú, và trước khi dừng phiên – container bị thu hồi khi rảnh):**
1. Lập danh sách: `python3 tools/drive_sync.py plan projects/<project> --include-out out/<project>` (`--json` để đọc
   bằng máy). Mỗi file mới/đã đổi có: thư mục đích (đường dẫn logic + ID từ `PROJECT.md`, hoặc
   `MISSING – create folder <đường dẫn> under <ID cha> first`), `title`, `contentMimeType`, tham chiếu
   `sha256:<hex>:<đường dẫn tuyệt đối>` cho `create_file`, lệnh `record`, câu truy vấn `search_files` tìm bản cũ cùng
   tên mới trong `99_LuuTru/` (bước 3). File đã đổi (CHANGED) luôn có bản cũ. File mới (NEW, không có dòng trong
   `.pulled.sha256`) cũng được in bước này, ghi nhãn `if a file with this title already exists in the folder (first
   push), archive it`: Drive có thể đã có file cùng tên (lần đẩy đầu sau khi người dùng tải tay lên, hoặc mất dấu) –
   vẫn chạy `search_files` sau khi tải lên, có kết quả nào khác ID vừa tạo thì chuyển vào `99_LuuTru/`, không có thì bỏ
   qua; nhờ vậy không sinh bản trùng. Cùng ánh xạ §11.3 cho media (`ledger.csv`, gói shot theo ngày
   trong tên zip, bản nháp, bản cuối, ảnh khóa); `plates/`, `clips/` không đẩy riêng (nằm trong gói shot).
   `TienDo_SanXuat.csv` được tách riêng (`[sheet]`, bước 5), không tải lên như file chữ. File không có ánh xạ (UNMAPPED)
   hay thư mục thiếu ID → mã thoát 1: tạo thư mục (`create_file` folder, `parentId` = ID cha), ghi ID vào
   `drive.folders`, chạy lại `plan`. File gốc trong `sources/` đã sửa thì không lập (chỉ `DanhMuc.csv` được sửa).
   Shell tương đương: các dòng `>` của
   `find projects/<project> -type f ! -name '.*' ! -name TienDo_SanXuat.csv -print0 | sort -z | xargs -0 sha256sum | diff projects/<project>/.pulled.sha256 - | grep '^>'`,
   cộng `out/<project>/<id>/ledger.csv` nếu khâu vừa rồi có tạo ảnh/video.
2. Mỗi file (đúng các tham số `plan` in ra): `create_file` vào thư mục tương ứng (ID từ manifest), `title` = tên file, `base64Content` =
   `sha256:<hex>:<đường dẫn tuyệt đối>` (hex từ `sha256sum`), `contentMimeType` (`.md` `text/markdown`, `.csv` `text/csv`,
   `.json` `application/json`, `.yaml`/`.txt` `text/plain`), `disableConversionToGoogleType: true`. Tải lên thành công →
   ngay lập tức `python3 tools/drive_sync.py record projects/<project> --uploaded <đường dẫn> --id <ID mới>`
   (thay đúng dòng của file trong `.pulled.sha256`, thêm dòng vào `.pushed.log`).
3. **Quy tắc phiên bản (chọn vì đơn giản và chắc):** connector không ghi đè được nội dung file (`update_file` chỉ sửa
   tên, thư mục, thuộc tính), nên lịch sử phiên bản của Drive không dùng được. Mỗi lần đẩy là **file mới**; chỉ sau khi
   tải lên thành công, tìm bản cũ ngay lúc đó bằng `search_files` (`parentId = '<id thư mục>' and title = '<tên file>'
   and trashed = false`) – không dựa vào ID nhớ từ lúc kéo, vì đẩy nhiều lần trong phiên hoặc ngữ cảnh bị nén sẽ làm
   mất ID – rồi **mọi kết quả trừ ID vừa tạo** được `update_file` chuyển vào `99_LuuTru/` (`parentId`) và đổi tên
   `<đường dẫn logic của thư mục, '/' → '__'>__<tên không đuôi>_<YYYYMMDD-HHMM>.<đuôi>` (giờ UTC lúc thay), vd.
   `03_KichBan__ep01-bac-thi__script_20261110-1530.md`. Kết quả: mỗi thư mục luôn có đúng một bản hiện hành mỗi tên;
   mọi bản cũ nằm ở `99_LuuTru/`, tìm lại được theo tên. Tải lên trước, chuyển sau: bị ngắt giữa chừng chỉ để lại
   bản trùng (bước 3 của mục kéo xử lý), không bao giờ mất bản nào.
4. Người dùng sửa trên Drive: trước khi đẩy, file trên Drive có `modifiedTime` sau `.pulled.at` **và** ID không có
   trong `.pushed.log` (không phải bản chính phiên này đẩy) → tải về, so với bản làm việc, gộp (giữ chữ của người
   dùng), xung đột thì hỏi người dùng; rồi mới đẩy. Với file NEW, mọi kết quả `search_files` có ID không nằm trong
   `.pushed.log` là bản chưa từng kéo về (tải tay, mất dấu) → cũng tải về, so, gộp trước.
5. `TienDo_SanXuat` (Sheet): sửa dòng của tập trong `projects/<project>/TienDo_SanXuat.csv` (cột theo
   `templates/project/TienDo_SanXuat.csv`). Có công cụ sửa Google Sheets thì sửa đúng dòng đó tại chỗ (giữ link); không
   có thì tải CSV lên **có** chuyển đổi (Sheet mới tên `TienDo_SanXuat` trong `00_QuanLy/`), chuyển Sheet cũ vào
   `99_LuuTru/` theo bước 3, cập nhật `drive.files` và đẩy `PROJECT.md`.
6. Cập nhật dấu **chỉ cho các file đã tải lên thành công** (`record` ở bước 2 thay đúng dòng của file đó trong
   `.pulled.sha256`; file người dùng từ chối tải giữ dấu cũ để lần sau vẫn hiện trong danh sách – không chạy lại
   `snapshot` sau khi đẩy). `plan` chạy lại phải in `Nothing to push.` (trừ file cố ý chưa đẩy); ghi giờ đẩy vào cột cuối dòng
   `## Nhật ký` của EPISODE.md.
7. Mỗi lần tải lên người dùng duyệt: gom file của một khâu đẩy một lượt, báo trước danh sách.

**Media:** gói shot, bản nháp, bản cuối, ảnh khóa chỉ đẩy sau khi người dùng duyệt (§9); đã có trên Drive thì kéo về
khi cần, không tạo lại bằng API.

### 11.7 Không xoá

Không xoá, không `trash_file` gì trên Drive. Thứ không dùng nữa (bản cũ, tập huỷ, ảnh hỏng đã lỡ tải lên) chuyển vào
`99_LuuTru/` bằng `update_file` (`parentId`), đổi tên theo §11.6 bước 3 nếu có thể trùng tên.
