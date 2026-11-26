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
├── templates/research/           # RESEARCH-BRIEF.md, ICONOGRAPHY.md, DESIGN-OPTIONS.md, LOCATION-REFS.md (khâu 3a)
├── formats/                      # CINECODE_FORMATS (định dạng cinecode đã lưu, xem §9)
├── tools/                        # ark.py, doctor.sh, check_episode.py, bundle.py, drive_sync.py, episode_id.py, rename_episode.py,
│                                 #   refs_fetch.py, assets.py, netfetch.py (tải có giấy phép), layers/, compose/,
│                                 #   toon/, audio/, tts/, blender/ (render 3D local), comfy/ (clip AI local)
├── tests/                        # python3 -m unittest discover -s tests
├── lambda/ · docs/
├── projects/<project>/           # git bỏ qua – bản làm việc CHỈ CHỮ kéo từ Drive (§11):
│   ├── PROJECT.md                #   manifest: slug, tên, style, ID thư mục Drive
│   ├── SERIES.md · characters/<c>/CHARACTER.md · locations/<l>/LOCATION.md · style/
│   │                             #   khâu 3a: characters/<c>/{ICONOGRAPHY,DESIGN-OPTIONS}.md, locations/<l>/LOCATION-REFS.md
│   ├── <thư mục tập>/            #   ep<NN>-<slug> hoặc q<NN>-t<NN>-<slug> (§2): EPISODE.md, budget.yaml, script.md, ...
│   └── sources/                  #   tài liệu gốc dạng chữ, kéo về khi cần
└── out/<project>/                # git bỏ qua – media: <id>/{plates,clips,film,renders,bundles}/, <id>/ledger.csv,
                                  #   ảnh khóa characters/<c>/, locations/<l>/, tài liệu gốc dạng ảnh sources/,
                                  #   assets/: refs/<c>/ (ảnh sách, ảnh tham chiếu + _credits.jsonl), asset CC0
                                  #   hdri/, textures/<id>/, models/<id>/ + ASSETS_MANIFEST.csv (tools/assets.py)
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
| Shot id | `s<NN>` (2 chữ số) hoặc `s<NNN>` (3 chữ số, tập trên 99 shot), tăng dần; một tập một độ dài | `s03` · `s103` |
| Lớp tranh | `<id>_s<NN>_<lớp>_<chủ-thể>_v<NN>.<png\|jpg>` | `ep01_s03_L4_bac-thi_v02.png` · `q01t01_s03_L4_bac-di_v02.png` |
| Mã lớp | `L1` nền · `L2` tầng giữa · `L3` tiền cảnh · `L4` nhân vật · `L4b`…`L4z` tư thế · `P<n>-<bộ-phận>` · `FX` | `P1-duoi` · `L4b` |
| Clip AI | `<id>_s<NN>_<model-ngắn>_v<NN>.mp4` | `ep01_s03_seedance25_v01.mp4` · `q01t01_s03_seedance25_v01.mp4` |
| Bản dựng | `<id>_<draft\|final>_v<NN>.mp4` | `ep01_draft_v03.mp4` · `q01t01_draft_v01.mp4` |
| Clip local (ComfyUI, `video_engine: comfy`) | như clip AI, model ngắn `h3`, kèm file `.json` cạnh clip (`<clip>.mp4.json` hoặc `<tên clip không đuôi>.json`) | `ep01_s03_h3_v01.mp4` + `ep01_s03_h3_v01.mp4.json` |
| Shot 3D (`method: blender`, chữ) | `<thư mục tập>/shots3d/s<NN>.json` | `shots3d/s03.json` |
| Render Blender (media) | `out/<project>/<id>/renders3d/s<NN>/` (render lại `s<NN>_v<NN>/`), `s<NN>_preview/`, `s<NN>_keys/`, `turntable-<asset>/` | `renders3d/s03/beauty/0001.png` |
| Style frame (khâu 3b, media) | `out/<project>/<id>/styleframes/<id>_sf<NN>_<chủ-đề>_v<NN>.png` (nâng chất: `…_edit_v<NN>.png`); contact sheet `<id>_contact_v<NN>.png`, bảng màu `<id>_palette_v<NN>.png` trong `<thư mục tập>/review/styleframes/` | `ep01_sf03_dan-te_v01.png` |

Regex chuẩn (một định nghĩa trong `tools/episode_id.py`, dùng chung cho `check_episode.py`, `status.py`, `bundle.py`,
`drive_sync.py`, `layers/anchors.py`, `layers/matte.py`; `<ID>` = `(?:ep\d{2}|q\d{2}t\d{2})`, `<S>` = `s(?:\d{2}|\d{3})`,
`<L>` = `(?:L[1-4]|L4[b-z]|P\d+-[a-z0-9-]+|FX)`):
- mã tập: `^(?:ep\d{2}|q\d{2}t\d{2})$`; thư mục tập: `^(?:ep\d{2}|q\d{2}-t\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$`
- shot: `^s(\d{2}|\d{3})$`; một tập dùng một độ dài (cả `s<NN>` hoặc cả `s<NNN>`), trộn hai độ dài là ERROR
- lớp: `^<ID>_<S>_<L>_[a-z0-9-]+_v\d{2}\.(png|jpg)$`
- clip: `^<ID>_<S>_[a-z0-9]+_v\d{2}\.mp4$`
- bản dựng: `^<ID>_(draft|final)_v\d{2}\.mp4$`
- khung đầu Seedance (trong `clips/`): `^<ID>_<S>_start_v\d{2}\.png$`
- khung của clip: thư mục `clips/<tên clip không đuôi>/` (tên khớp regex clip, bỏ `.mp4`) chỉ chứa `^\d{6}\.png$`
  và thư mục con tùy chọn `raw/` (khung gốc tách bằng ffmpeg, cũng `^\d{6}\.png$`)
- dòng clip trong `prompts.csv`: `file` theo regex clip, `layer` = mã lớp mà clip thay (thường `L4`), `shot` khớp tên file
- file cạnh clip local (trong `clips/`): `^<ID>_<S>_[a-z0-9]+_v\d{2}(\.mp4)?\.json$`
- `shots3d/`: `^s(\d{2}|\d{3})\.json$`; `renders3d/`: thư mục `^(s(\d{2}|\d{3})(_(preview|keys))?|turntable-[a-z0-9][a-z0-9_-]*)(_v\d{2})?$`
  (tên khác → WARN). Nội dung một render: `beauty/0001.png…`, `depth/`, `normal/`, `line/`, `mask/<asset>/`, `beauty.mp4`,
  `render.json` (`tools/blender/README.md`)
- `graded/`: render đã grade bằng `tools/compose/grade.py`, `s<NN>[_v<NN>]/` (chuỗi PNG, cùng tên khung với `beauty/`)
  hoặc `s<NN>[_v<NN>].mp4`; dựng lại được từ render + khối `grade:`, không vào gói shot

Plate tư thế của `method: layers` (shot có `pose-cycle`): mã lớp `L4b`, `L4c`… (`L4` là tư thế gốc), file
`<id>_s<NN>_L4b_<chủ-thể>_v<NN>.png`; cùng khung vẽ, cùng điểm neo chân và cùng cách tách nền với `L4` (`matte.py`
tự dùng `matte.per_layer.L4` cho `L4b`…, trừ khi style có khóa `L4b` riêng; `anchors.py` nhận file `L4b`). Tập
`seedance` có `L4b` trong `layers` → WARN. Chi tiết: `.claude/skills/film-compose-shot/references/layers-method.md`.
Khóa `L4b:` trong `PLATES` mà `matte_seq.py` in ra cho clip Seedance là tên lớp trong film.html, không phải mã lớp.

Phiên bản luôn tăng, không ghi đè. Media lưu trong `out/<project>/<id>/{plates,clips,renders}/`.
Stem âm thanh của `tools/audio/score.py`: `out/<project>/<id>/audio/` (`music.wav`, `foley.wav`, `ambience.wav`,
`preview.wav`, `score-log.json`, `mix-snippet.json`); bản dựng lại vào `audio/v<NN>/`.
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
Tách alpha (`matte`): ảnh tạo ra giữ nguyên ở `plates/<tên>`, bản RGBA đã tách là `plates/matte/<cùng tên>.png` (OUT mặc
định của `tools/layers/matte.py`, không bao giờ ghi đè ảnh gốc); cột `file` của `prompts.csv` và khóa trong `anchors.json`
vẫn là tên gốc, không kèm `matte/`.
Prompt mẫu trong `styles/<id>/prompts/*.txt` dùng chỗ trống `{style_block}`, `{subject}`, `{constraints}`, `{light}`.
Thêm trường phái mới = chép `styles/_template/`, không sửa skill.

**Style vẽ bằng code (`engine: code`, cho tập `method: code`).** Không model tạo ảnh nào: bắt buộc `id, name, status,
base, engine: code, render, palette`; không `style_block, negative, light, matte, layers, models, prompts/` (có thì WARN).
```yaml
engine: code
render:
  engine: canvas2d          # canvas2d | three, phải khớp look trong tools/toon/looks.json
  look: flat-toon           # flat-toon | ink-silhouette | rubber-hose | blueprint | clay-3d | lowpoly-90s | cardboard | popup-paper
  post: [riso]              # hậu kỳ theo thứ tự: riso | pixel-16 | ascii; một mục có thể là {id: riso, cell: 7, ...}
  hold: 2                   # 1 = 24 hình/s, 2 = bước đôi, 3–4 = stop-motion
  palette: {sky: "#F4EEDF"} # ghi đè màu của look: "#RRGGBB" hoặc "rgba(...)"
  opts: {}                  # tuỳ chọn của look (bpm, reveal, rim...); camera: {...}; env: {...} (tools/toon/project.js)
```
Mười pack có sẵn và cách dùng: `.claude/skills/film-compose-shot/references/code-method.md`. Thêm pack = chép `styles/_template-code/`.

**Style render bằng Blender (`engine: blender`, cho tập `method: blender`).** Như `engine: code`: bắt buộc `id, name,
status, base, engine: blender, render, palette`; không khóa của model ảnh (có thì WARN).
```yaml
engine: blender
render:
  look: ink-wash            # look của Blender: grey-layout | clay | toon-ink | ink-wash | realistic (tools/blender/looks.json khi có)
  engine: eevee             # eevee (mặc định, cần GPU) | cycles
  line: 2.0                 # độ dày nét Line Art ở 1080p, 0 = không nét
  mist: 0.35                # sương theo độ sâu, 0–1
  palette: {paper: "#EFE6D3"}   # "#RRGGBB"
```
Ba pack có sẵn: `styles/thuy-mac-blender/`, `styles/toon-3d-blender/`, `styles/chan-thuc-blender/` (chân thực: Cycles,
HDRI, PBR; draft); cách dùng:
`.claude/skills/film-compose-shot/references/blender-method.md`.

**Grade (`grade:`, tuỳ chọn, mọi engine).** Tham số của `tools/compose/grade.py`: grade hai lớp (cảnh / chủ thể theo pass
mask) áp lên khung đã render ở khâu 7–10; thiếu khóa = không đổi gì. Khóa và khoảng: `blender-method.md` §7; khóa lạ hay
ngoài khoảng là ERROR của `check_episode.py style`.
```yaml
grade:
  seed: 7                   # vân giấy, cố định
  scene:   {saturation: {...}, keep_red: {...}, hue_pull: {<tên>: {to: "#RRGGBB", amount}}, tone: {...},
            split: {...}, mist: {...}, paper: {...}, vignette: {...}}
  subject: {saturation: {...}, tone: {...}, layer: {opacity, mist_keep, edge, rim, rim_width}}   # ghi đè scene trong mask
```

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
owner_refs: {source: "Sách tranh SHK (Lương Siêu / Sam Trạch / An Lạc)", required: true}   # tuỳ chọn
---
```
`series:` = slug dự án = tên thư mục `projects/<project>/`. `characters/<slug>/CHARACTER.md`: nguồn nguyên văn + link,
cách đọc tên, bảng giải phẫu (mỗi đặc điểm một dòng, ghi nguồn hay diễn giải), prompt khóa, link Drive ảnh khóa; sinh
vật chính của tập `blender`/`code` thêm mục `## Concept đã duyệt` (file concept chủ dự án chọn, ngày, nguồn/diễn giải –
khâu 3a, `film-pipeline`).
`owner_refs` (tuỳ chọn): tư liệu riêng của chủ dự án (sách tranh…). `required: true` → ở khâu 1 mỗi tập, đạo diễn liệt kê
mọi sinh vật/thần vào bảng `## Sinh vật của tập` (§5) và xin ảnh chụp trang tương ứng **trước** vòng nghiên cứu bổ sung;
ảnh nằm ở `out/<project>/assets/refs/<slug>/book/`, nguồn ghi trong `out/<project>/assets/refs/<slug>/REFS.md` (không
lên git, không lên Drive). Sách không có con nào thì chủ dự án xác nhận "không". Ảnh sách có bản quyền: chỉ là chuẩn
tinh thần và chất lượng, không chép, không đưa vào phim; thiết kế của lab là bản riêng. `status.py` in dòng `OWNER_REFS`;
G1/G2 cần ảnh (hoặc "không") cho mọi sinh vật của bảng.
Khâu 3a (`film-iconographer`, mẫu `templates/research/`): `characters/<slug>/ICONOGRAPHY.md` (văn bản ≥ 3 nguồn, bảng
bộ phận × nguồn, bảng ảnh có giấy phép) và `DESIGN-OPTIONS.md` (2–3 hướng, Prompt EN, Edit EN, giải phẫu cho 3D) mỗi
sinh vật chính; `locations/<slug>/LOCATION-REFS.md` mỗi bối cảnh. Ảnh tham chiếu (media, không lên git, không lên
Drive): `out/<project>/assets/refs/<slug>/iconography/` và `out/<project>/assets/refs/locations/<slug>/`, tải bằng
`tools/refs_fetch.py`, mỗi ảnh một dòng `_credits.jsonl` (giấy phép, tác giả, link).
`locations/<slug>/LOCATION.md`: như CHARACTER.md cho bối cảnh. `style/`: ghi chú phong cách riêng của dự án và prompt
mẫu đã duyệt (style pack dùng chung vẫn ở `styles/<id>/` trong repo).

Thư mục tập `projects/<project>/ep<NN>-<slug>/` (dự án chia quyển: `projects/<project>/q<NN>-t<NN>-<slug>/`, §2):

| File | Ai viết | Nội dung |
|---|---|---|
| `EPISODE.md` | đạo diễn | trạng thái tập (§5). **Không đặt tên `STATE.md`** – tên đó thuộc cinecode |
| `budget.yaml` | đạo diễn | trần chi phí (§7). `tools/check_episode.py` kiểm: thiếu file là ERROR từ khâu 0; chỉ bốn khóa `images`, `video_seconds`, `models`, `ledger_required` (khóa lạ là ERROR: gõ sai tên trần = không có trần); `images` và `video_seconds` bắt buộc, là số ≥ 0 |
| `research.md` | film-researcher | nguyên văn, link, cách đọc tên; tài liệu gốc dùng tới ghi theo tên file trong `01_TaiLieuGoc/` (§11.4) |
| `RESEARCH-BRIEF.md` | đạo diễn | (khâu 3a) phân công và chuẩn nghiên cứu hình tượng cho `film-iconographer`; mẫu `templates/research/RESEARCH-BRIEF.md` |
| `script.md` | film-writer | lời bình theo chương, mỗi câu có mốc `[mm:ss]`; hai mốc liền nhau cách nhau tối thiểu 3 s. Dòng không phải lời bình: tiêu đề `#`, dòng trống, trích dẫn `>`, chú thích `<!-- -->` (kể cả chú thích nằm trong dòng: bị bỏ, phần chữ còn lại vẫn là lời bình), khối code ` ``` `/`~~~`, khối YAML đầu file, đường kẻ `---`/`***`/`___`. Mọi dòng khác đều bị coi là lời bình: ghi chú, bảng, metadata phải đặt trong `>`. Lời bình không dùng dấu gạch ngang (`—`, `–`, `--`: ERROR; trong `>` là WARN), không để chữ Hán hay ký hiệu markdown (`\|`, `` ` ``, `](`, `<`, `>`: WARN, TTS không đọc được) |
| `shots.csv` | film-writer | §6 |
| `prompts.csv` | film-art-director / film-plate-maker | §6 |
| `anchors.json` | film-plate-maker | điểm neo theo file lớp: `{"<file lớp>": {"<tên>": [x, y]}}` (pixel); vùng chữ nhật lưu bằng cặp điểm `<tên>_tl` / `<tên>_br`; `tools/layers/anchors.py` ghi, `tools/compose` đọc |
| `score.json` | film-compositor | (tuỳ chọn) nhạc code và foley theo sự kiện cho `tools/audio/score.py`: `length_s`, `seed`, `scale`, `music`, `foley`, `silence` (`tools/audio/README.md`; mẫu `templates/episode/score.json`). Dữ liệu dự án: không commit, đẩy lên Drive như file chữ khác. Phần `music` chỉ khi người dùng đã chọn nhạc code |
| `review/` | film-reviewer, compositor, film-dop | `qc-<v>.md`, `sound-audit.md`, `check-v<N>.txt`, `dop-pass.md` (khâu 2b); `styleframes/` (khâu 3b: contact sheet, bảng màu, bản sao khung chuẩn) |
| `CAMERA-BIBLE.md` | film-dop | (khâu 2b) ngôn ngữ máy quay của tập: thang cỡ cảnh (tam viễn), kỹ thuật nối, tham chiếu, nhịp theo chương, cận và toàn cảnh mỗi sinh vật chính; mẫu `templates/episode/CAMERA-BIBLE.md` |
| `STYLE-FRAMES.md` | film-3d-artist / đạo diễn | (khâu 3b, tập `blender`/`code`) 5–8 style frame, bảng màu, quy tắc đối chiếu, khung chuẩn chủ dự án chọn (§5); mẫu `templates/episode/STYLE-FRAMES.md` |
| `publish.md` | film-publisher | tiêu đề, mô tả, chương, credit, tag |
| `prompts/` | film-art-director / film-animator | prompt đã dùng, mỗi ảnh/clip một file `.txt` |
| `shots3d/s<NN>.json` | film-3d-artist | (`method: blender`) một `shot3d.json` mỗi shot không dùng lại: model, máy quay, look; schema phiên bản 1 trong `tools/blender/README.md` (kiểm bằng `tools/blender/spec.py`), mẫu `templates/episode/shot3d.json`. Bắt buộc từ khâu 5; `seconds` và `camera.move` khớp `shots.csv` (lệch → WARN) |
| `ASSETS.md` | film-3d-artist | (`method: blender`) nguồn và giấy phép mỗi model 3D (preset hoặc GLB) và asset CC0 nào dùng ở shot nào (sổ chung của dự án: `out/<project>/assets/ASSETS_MANIFEST.csv`, `tools/assets.py`); có thể nằm ở thư mục dự án cho cả series; mẫu `templates/episode/ASSETS.md`. Thiếu: WARN ở khâu 3, ERROR từ khâu 4 |

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
method: layers           # cách dựng: layers | seedance | code | blender (xem dưới)
video_engine: comfy      # tuỳ chọn, chỉ với seedance | blender: clip khâu 6 bằng seedance (mặc định) hoặc comfy
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
`method` = cách dựng của tập, chọn cùng người dùng ở khâu 0, sau G1 không tự đổi (phải hỏi người dùng):
`layers` = chỉ dùng model ảnh, tách lớp, ghép lớp và làm chuyển động từng thành phần bằng code, không gọi Seedance;
`seedance` = cử động nhân vật bằng clip Seedance; `code` = nhân vật và cảnh vẽ hoàn toàn bằng code (`tools/toon/`), không
gọi model nào; `blender` = model 3D render bằng Blender trên máy chủ lab (`tools/blender/`, phiên local), không model ảnh.
Không phân biệt hoa thường; giá trị khác → ERROR `method must be layers, seedance, code or blender`. Thiếu khóa = `seedance` (tập cũ giữ nguyên nghĩa) kèm một WARN; tập mới chép từ
mẫu ghi `layers`. Với `layers`, `tools/check_episode.py` báo ERROR khi: một shot có `ai_motion` (§6), `video_seconds` > 0,
hoặc `models.<id>` > 0 với id chứa `seedance` trong `budget.yaml` (§7). Với `code`: ERROR khi `images`, `video_seconds` hoặc
bất kỳ `models.<id>` > 0, khi một shot có `ai_motion`, khi mã lớp không phải `C-<slug>`/`M-<slug>`/`E-<slug>`/`FX[-<tên>]`/`T`, hoặc khi
style của tập không phải `engine: code` (và ngược lại: style `engine: code` chỉ cho tập `code`); không cần `prompts.csv`
(có thì WARN). Nhân vật khóa ở G2 là `characters/<slug>/character.json` + `review/turntable-<slug>.png`.
Với `blender`: ERROR khi `images` hoặc `models.<id>` (không phải seedance) > 0, khi `video_seconds`/`models.<seedance>` > 0
mà tập không ghi `video_engine: seedance` hoặc không shot nào có `ai_motion`, khi một shot có `ai_motion` mà thiếu
`video_engine`, khi mã lớp không phải `A-<asset>`/`E-<slug>`/`FX[-<tên>]`/`T`, khi style không phải `engine: blender` (và
ngược lại); không cần `prompts.csv` (có thì WARN); `shots3d/`, `ASSETS.md`, `renders3d/` theo §2 và §4. Model khóa ở G2 là
`ASSETS.md` + turntable `renders3d/turntable-<asset>/` + một shot mẫu `renders3d/s<NN>_preview/`.
`video_engine` = engine của khâu 6: `seedance` (mặc định, `ark.py video`, trả tiền) hoặc `comfy` (`tools/comfy/comfy.py run`,
MiniMax H3 local, miễn phí, chỉ trên máy chủ lab). Chỉ đi với `seedance` và `blender` (với `layers`/`code` là ERROR; giá trị
khác `seedance`/`comfy` là ERROR). Với `comfy`, `video_seconds` để 0 được (tập `seedance` + `comfy` có `video_seconds` > 0 →
WARN: không dùng tới). Phiên cloud (`CLAUDE_CODE_REMOTE=true`) mở tập `blender` hoặc `comfy` → WARN: khâu 4–6 cần phiên local.
Một khóa ghi hai lần trong khối YAML (vd. `method: layers` rồi `method: seedance`) là ERROR: YAML lặng lẽ giữ giá trị sau
(cũng vậy với `budget.yaml`).
Các mục chữ bắt buộc: `## Ghi chú người dùng (nguyên văn)`, `## Đã khóa (không làm lại)`, `## Việc tiếp theo`, `## Nhật ký`
(mỗi khâu một dòng: ngày, khâu, kết quả, giờ đẩy Drive – `chưa` nếu chưa đẩy).

Mục `## Sinh vật của tập` (mẫu có sẵn; bảng trống khi tập không có sinh vật): mỗi sinh vật/thần một dòng
`| slug | Tên | Chính | Ảnh sách | Concept |`. `slug` = `characters/<slug>/` = mã model `A-<slug>` (blender) / `C-<slug>`
(code); `Chính` = `có` | `không`; `Ảnh sách` = `có` (ảnh trang sách trong `out/<project>/assets/refs/<slug>/book/`) |
`không` (chủ dự án xác nhận sách không có) | `chờ`; `Concept` = `chờ` | `duyệt <ngày> <file>` (chỉ chữ đầu được đọc).
Concept được tính là duyệt khi bảng ghi `duyệt` **và** `characters/<slug>/CHARACTER.md` (thư mục tập hoặc dự án) có mục
`## Concept đã duyệt` không trống. `tools/check_episode.py`: giá trị lạ, thiếu cột → WARN; ô `Chính` trống hay thiếu → tính là sinh vật chính + WARN; `owner_refs.required` mà còn
`chờ` từ khâu 2 → WARN; tập `blender`/`code` có sinh vật chính chưa duyệt concept → WARN ở khâu 3–4, ERROR từ khâu 5
(sau G2). `tools/status.py` in mục `CREATURES` (và `OWNER_REFS` khi bắt buộc); `--gate G2` của tập `blender`/`code` cần
bảng này và concept duyệt cho mọi sinh vật chính (`[MISSING]` khi thiếu).

Style frame (khâu 3b, tập `blender`/`code`): file `STYLE-FRAMES.md` trong thư mục tập (mẫu
`templates/episode/STYLE-FRAMES.md`). Bảng `## Khung` một dòng mỗi khung (5–8, mỗi chương một; ngoài khoảng đó → WARN).
Bảng `## Khung chuẩn đã duyệt` `| Vai | Khung | Ngày | Lời chủ dự án |`: `Vai` = `không khí` hoặc slug của bảng
`## Sinh vật của tập` (`A-`/`C-`/`M-` đứng trước được bỏ qua); một dòng chỉ tính khi có `Khung` và ngày `YYYY-MM-DD`.
Duyệt đủ = có dòng `không khí` và một dòng cho mỗi sinh vật chính. Không phải cổng mới (G1–G4 giữ nguyên): `tools/status.py`
in mục `STYLE FRAMES`, `--gate G2` của tập `blender`/`code` cần duyệt đủ (`[MISSING] approved style frames`);
`tools/check_episode.py` WARN từ khâu 3 khi chưa duyệt đủ (file thiếu, thiếu dòng, ô sai), INFO khi tập đã ghi ngày G2 và
ở khâu ≥ 5 (tập làm trước khi có bước này vẫn hợp lệ). Tập `layers`/`seedance` không cần file này.

## 6. CSV (RFC 4180, UTF-8, có header, trường có dấu phẩy/xuống dòng phải đặt trong ngoặc kép)

`shots.csv`:
`shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of`
- `shot` = `s<NN>` (`s01`…`s99`) hoặc `s<NNN>` (`s001`…`s999`, tập trên 99 shot); cả tập một độ dài, trộn là ERROR. `from_s`/`to_s` số giây (thập phân được), liên tục: `from_s` = `to_s` shot trước; shot đầu từ 0; shot cuối kết thúc = `length_s`.
- Thời lượng mỗi shot 3–13 s. `shot_size` ∈ `extreme-wide, wide, medium, close, extreme-close, insert`.
- `camera` = một chuyển động (`static, push-in, pull-out, pan-left, pan-right, tilt-up, tilt-down, drift, handheld`).
  Hai shot liền nhau không cùng cả `shot_size` lẫn `camera` (ERROR).
- Tập `blender`/`code`: mỗi sinh vật chính của bảng `## Sinh vật của tập` (§5) có ≥ 1 shot cận chi tiết (`close`,
  `extreme-close`, `insert`) và ≥ 1 shot `extreme-wide` (nhỏ giữa non sông); sinh vật nằm trong shot khi cột `layers`
  có `A-<slug>` (blender) hoặc `C-<slug>`/`M-<slug>` (code), kể cả biến thể `A-<slug>-<hậu tố>` khi `<slug>-<hậu tố>`
  không phải slug của sinh vật khác; shot `reuse_of` không có lớp dùng lớp của shot gốc. Thiếu (hoặc sinh vật không có
  trong shot nào) → WARN. Tập `layers`/`seedance` không kiểm (mã lớp không nêu tên sinh vật). `film-dop` soát luật này ở
  khâu 2b (`CAMERA-BIBLE.md`).
- `layers` = mã lớp cách nhau bởi `;` (vd. `L1;L2;L3;L4;P1-duoi`). `code_motion`, `ai_motion` cách nhau bởi `;`; `ai_motion` trống = không dùng Seedance.
  Tập `method: layers` (§5): `ai_motion` phải trống ở mọi shot, có giá trị là ERROR nêu tên shot; cử động viết ở
  `code_motion` (cử động lớn = `pose-cycle`: đổi bậc giữa 2–4 tranh tư thế), hoặc đổi tập sang `method: seedance`.
  Tập `method: code`: `layers` = `C-<nhân vật>` hoặc `M-<model>` (model 3D, đạo cụ), `E-<bối cảnh>`, `FX` hoặc
  `FX-<hiệu ứng>`, `T` (chữ trên hình); `camera` nhận thêm `orbit, dolly, crane, track` và mọi id `engine: toon` có
  `module` `toon/project.js` trong `motions.json`; `code_motion` dùng id `engine: toon` của `motions.json` (`walk-cycle`,
  `run-cycle`, `jump`, `turn`, `wave`, `cheer`, `point`, `bounce`, `look-at`, `blink`…; checker đọc thẳng sổ đăng ký, id
  mới thêm vào đó là hợp lệ ngay); id compose rig lớp tranh (`PLATES.<id>.rig…`: `cloth`, `strip-warp`…) là WARN;
  `ai_motion` trống. Ngược lại, id `engine: toon` ở tập `layers`/`seedance` là WARN.
  Tập `method: blender`: `layers` = `A-<asset>` (model 3D, id trong `shot3d.json`), `E-<bối cảnh>`, `FX[-<hiệu ứng>]`, `T`;
  `camera` ∈ `static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track` (tên chuyển động của `shot3d.json`);
  `code_motion` = hiệu ứng compose phủ lên render (id rig lớp tranh là WARN); `ai_motion` chỉ khi có `video_engine`.
- `reuse_of` = shot id dùng lại tài sản, hoặc trống.
- Từ khâu 8 (G3), tập `seedance` hoặc `blender`: shot có `ai_motion` phải có clip (Seedance hoặc H3 local) `<id>_<shot>_<model>_v<NN>.mp4` trong `clips/` (shot có
  `reuse_of` dùng clip của shot gốc; clip `approved=no` không tính), thiếu là ERROR.
- `code_motion` và `motion:` của style dùng id trong `tools/compose/motions.json` (mist-bands, embers, sun-glow,
  strip-warp, eyelid, breath, parallax, push-in; `figure` = người nhỏ vẽ bằng code trong cảnh rộng, không cần lớp
  tranh); id lạ là WARN.

`prompts.csv`:
`file,shot,layer,model,size,prompt_file,refs,seed,usage,approved,drive_link`
- `file` theo quy ước tên §2; `prompt_file` đường dẫn tương đối tới file prompt đã dùng (lưu trong thư mục tập, `prompts/`).
- `refs` cách nhau bởi `;`; `usage` = JSON usage Ark nguyên văn; `approved` ∈ `yes, no, ''`.
- Mỗi cặp (shot, lớp) chỉ một ảnh `approved=yes` và một clip `approved=yes` (dòng clip ghi lớp nó thay, nên L4 duyệt +
  clip duyệt là hợp lệ); hai bản duyệt là ERROR. File trong `plates/` (không tính `plates/matte/`) không có dòng nào
  trong `prompts.csv` → một WARN liệt kê (ảnh trả tiền chưa ghi prompt, hoặc file thử để nhầm chỗ).

## 7. Ngân sách và ledger (`tools/ark.py --budget/--ledger`)

`budget.yaml`:
```yaml
images: 40               # tổng số ảnh tối đa (mọi model)
video_seconds: 60        # tổng giây video tối đa; tập `method: layers` (§5) phải ghi 0
models:                  # (tuỳ chọn) trần riêng theo model, đơn vị ảnh hoặc giây video
  dola-seedream-5-0-pro-260628: 6
ledger_required: true    # (tuỳ chọn) từ chối khi file ledger chưa có: buộc kéo ledger từ Drive trước; bật từ khâu 4
```
`ledger.csv` (đặt ở `out/<project>/<id>/ledger.csv`; bản gốc trên Drive `04_SanXuat/<thư mục tập>/ledger.csv`, kéo về đầu
phiên trước khi tạo ảnh để trần ngân sách tính đúng, §11.6), header:
`ts,kind,model,size,seconds,count,status,out,task_id,usage,agent,note`
- `kind` ∈ `image, video`; `status` ∈ `pending, ok, failed, cut-502, abandoned, failed-unsent, refused-budget`; `ts` ISO 8601 UTC; `agent` lấy từ biến môi trường `FILM_AGENT` (trống = phiên chính).
- **Dòng local** (engine chạy trên máy chủ lab): `model` bắt đầu bằng `comfy:` (`tools/comfy/comfy.py run`: `comfy:h3-i2v`,
  `comfy:h3-r2v`; `status` thêm `interrupted`, `task_id` = prompt id, `usage` = `gpu_s=<n>`, `note` = `req=<hex>;seed=<n>`)
  hoặc `blender:`. Cùng cách ghi `pending` + dòng cuối, nhưng **không tính vào trần nào** (`images`, `video_seconds`,
  `models`); `tools/status.py` liệt kê chúng riêng (`LOCAL`) và không báo OPEN/MISSING cho chúng.
- Ngân sách không phải tuỳ chọn: `ark.py image|video` từ chối (thoát mã 2, không gọi API, không ghi ledger) nếu thiếu
  budget **hoặc** ledger (cờ `--budget/--ledger` hoặc env `FILM_BUDGET/FILM_LEDGER`); `--budget` không có ledger là lỗi.
  Ngoại lệ duy nhất: cờ `--no-budget` (in một dòng cảnh báo, ledger tuỳ chọn) – chỉ để thử nhanh ở phiên chính. Có biến
  `FILM_AGENT` (agent) thì `--no-budget` và `--force` bị từ chối, mã 2, không gửi gì.
- Mỗi request ghi dòng bằng khoá file (`fcntl.flock`, agent chạy song song):
  - trước lệnh POST tạo ảnh/video: một dòng `pending`, `note` = `req=<uuid4 hex>`;
  - video: có task id là ghi ngay dòng `pending` thứ hai có `task_id` (cùng `req=`) và in task id ra – còn lại cả khi bị SIGKILL;
  - khi xong: một dòng cuối `ok`, `failed` hoặc `cut-502` cùng `req=` (`note` = `req=<id>; <chi tiết>`). Phản hồi không
    có dữ liệu ảnh → `failed` (`no image in the response`). Phản hồi nhiều ảnh: ảnh thứ n lưu `<stem>-<n><ext>`, file
    đó đã có (hoặc là `out` của dòng khác trong lô) thì `<stem>-<n>-<8 ký tự đầu của req><ext>`: không ghi đè file nào.
  SIGTERM/SIGINT → dòng `failed` (`interrupted by SIGTERM`, video có `task_id`); SIGKILL → chỉ còn `pending`, vẫn tính là đã tính phí.
- Cách đếm: gom các dòng theo `req=` (dòng không có `req=` nhưng có `task_id` thì gom theo `task_id`); mỗi request tính
  **một lần** theo dòng cuối (`ok/failed/cut-502`) mới nhất, chưa có dòng cuối thì theo dòng `pending` (coi như đã tính phí).
  Dòng không có cả `req=` lẫn `task_id` (ledger cũ) mỗi dòng tính một lần như trước. `refused-budget` không tính.
  `abandoned` (dòng cuối do `ledger-close` ghi) vẫn tính; `failed-unsent` (job Lambda chưa gửi gì) đóng request và
  **không** tính. `req=` chỉ nhận cả cụm chữ hex thường, sau đó là `;`, khoảng trắng hoặc hết `note`.
- Request mồ côi (dòng `pending` không bao giờ có dòng cuối: agent bị giết khi đang gọi API ảnh, job Lambda đã
  `prepare` mà không Invoke): `ark.py ledger-close --req <id> --ledger L --status abandoned [--note …]` ghi dòng
  `abandoned` (vẫn tính vào trần, `tools/status.py` không còn báo OPEN). Từ chối (mã 2, không ghi) khi request
  không có dòng `pending` hoặc đã có dòng cuối. Video còn `task_id` thì thử `video --resume-task` trước;
  `ark.py video --resume-pending --ledger L` chạy `--resume-task` cho mọi task video đang mở của ledger, lần lượt.
- Trước khi gọi API: tổng đã dùng + yêu cầu hiện tại; vượt bất kỳ trần nào → từ chối, ghi `refused-budget` (không có `pending`), thoát mã 3.
- Kiểm và giữ chỗ là **một bước nguyên tử**: một khoá `LOCK_EX` trên `ledger.csv` bao quanh việc đọc ledger, cộng tổng
  và ghi dòng `pending` (hoặc `refused-budget`), rồi mới mở khoá. Việc chậm (nén ảnh `--ref`, đọc khung đầu, tạo thư mục,
  đọc `budget.yaml`) làm trước khi lấy khoá; lệnh gọi API làm sau khi mở khoá (khoá không giữ trong lúc gọi API).
  Nhờ vậy N agent chạy song song trong cùng container không vượt trần.
- Request 502 bị proxy cắt: ghi `cut-502`, không thử lại.
- Mã thoát của `image` / `video` / `lambda-job prepare`: **2** = bị từ chối tại chỗ, không gửi gì, không ghi dòng ledger,
  không tạo thư mục đầu ra → sửa lệnh; **3** = vượt trần (dòng `refused-budget`); **1** = request đã rời máy → xem dòng
  ledger của nó (có thể đã tính phí), không tự chạy lại.
- `budget.yaml` chỉ nhận bốn khoá `images`, `video_seconds`, `models`, `ledger_required`; khoá lạ (vd. `image:`), trần
  không phải số ≥ 0, file thiếu/rỗng/hỏng → mã 2. Request phải nằm dưới một trần (ảnh: `images` hoặc `models.<model>`;
  video: `video_seconds` hoặc `models.<model>`), không thì mã 2 `has no cap for ...`.
- File đầu ra đã tồn tại (kích thước > 0) → mã 2 `output exists`, kèm gợi ý `_v<NN>` còn trống: phiên bản chỉ tăng, không
  ghi đè file đã trả tiền (`--overwrite` chỉ cho thử nhanh ngoài tập). Ledger có header khác chuẩn → mã 2
  `ledger header mismatch`: sửa header hoặc kéo lại từ Drive, không xoá file.
- Thư mục chứa file đầu ra được tạo sau các kiểm tra tại chỗ ở trên, trước khi ghi `pending` và gọi API. Lưu ảnh lỗi → `failed`, note `save-failed`;
  tải video lỗi → `failed`, note `download-failed` (cả hai vẫn tính phí); ark.py in URL đầy đủ và task id để tải tay (link có hạn).
- `ark.py video --resume-task <task_id> [out.mp4] --ledger L`: không tạo task, không kiểm ngân sách, không ghi `pending`;
  poll tiếp + tải về, ghi dòng cuối cho task đó với `req=` lấy từ ledger (`out` mặc định lấy từ ledger). Cần ledger, không cần budget.
- `ledger_required: true` trong `budget.yaml`: `ark.py` thoát mã 2 (không gọi API, không ghi gì) khi file ledger chưa
  tồn tại hoặc rỗng – một ledger trống sẽ tính lại mọi trần từ 0. Kéo ledger của tập từ Drive trước; chỉ khi Drive chưa
  có (tập chưa tạo ảnh/video nào) mới tạo ledger rỗng có header bằng `python3 tools/ark.py ledger-merge -o <ledger>`.
- **Ảnh qua Lambda** (pro, 4K; `lambda/README.md`) dùng cùng ledger và cùng cách đếm:
  `ark.py lambda-job prepare` làm đúng bước nguyên tử ở trên (dòng `pending`, `note` = `req=<id>; lambda`, vượt trần →
  `refused-budget`, mã 3) và in payload có `job_id` = `<id>`; `ark.py lambda-job finish` đọc `jobs/<id>.json` của worker
  và ghi dòng cuối `ok`/`failed` cùng `req=` (`usage` của job, `note` = `req=<id>; lambda; seconds=<s>`); job `failed`
  có `sent: false` → `failed-unsent` (không tính); job còn `running` quá `deadline` + 60 s → báo worker đã chết, mã 1,
  `--give-up` ghi `failed` (vẫn tính); status không phải object JSON hay `--image` không phải ảnh (trang lỗi S3) → mã 2,
  không ghi gì; `worker_sha256` khác `lambda/ark_image_worker.py` của repo → WARN. Không gọi
  Lambda bằng payload tự viết: request không có dòng `pending` là request đi vòng qua ngân sách.
- **Tạo ảnh theo lô** (`ark.py image-batch JOBS.csv --budget B --ledger L [--parallel N] [--dry-run] [--only ID …] [--fast]`):
  mỗi dòng CSV (`id,prompt,out,size,model,ref,seed,negative`; `prompt` dạng `@file` đọc từ file cạnh CSV, `ref` cách nhau
  bởi `;`, `model` trống = model mặc định hoặc flash khi có `--fast`) là **một** request `image` với đúng các dòng
  `pending` + dòng cuối ở trên, không thử lại. Kiểm mọi dòng trước khi gửi (mã 2, liệt kê hết lỗi theo `id`); dòng đã có
  file đầu ra thì **bỏ qua** (`skip <id>: output exists`) nên chạy lại sau khi bị ngắt không trả tiền hai lần, không có
  `--overwrite`; cả lô vượt một trần → **một** dòng `refused-budget` (`note` = `batch of N: …`), mã 3, không gửi gì; rồi
  chạy tối đa `--parallel` request cùng lúc (mặc định 3, tối đa 4), từng request vẫn qua bước nguyên tử. Một dòng lỗi
  không dừng các dòng khác; bị từ chối ngân sách giữa chừng, HTTP 401/403, lỗi số dư tài khoản hoặc SIGINT/SIGTERM
  (mã 130/143) thì thôi không bắt đầu dòng mới, dòng đang chạy vẫn ghi dòng cuối. Mã 1 = có request đã rời máy và lỗi.
  `--dry-run` chỉ kiểm và in kế hoạch, không ghi ledger. Chi tiết: `ark.py image-batch --help`.
- **Gộp ledger** (`ark.py ledger-merge A.csv B.csv … -o OUT.csv`): hợp các dòng của nhiều bản ledger, khử trùng theo
  `(req, status, task_id)` (hai bản khác nhau ở cột khác: giữ dòng tính nhiều hơn; kết quả không phụ thuộc thứ tự
  đầu vào); dòng cũ không có `req=` gộp theo bội: mỗi dòng giống hệt giữ số lần nhiều nhất trong một bản (hai dòng
  giống hệt trong một bản là hai request); sắp theo `ts`, `pending` trước dòng cuối của cùng thời điểm; ghi `OUT`
  dưới `LOCK_EX`. Mọi dòng của mọi bản (kể cả `OUT`) được kiểm trước: header, số ô, `ts`, `kind`, `status`, `count`,
  `seconds`, `req=`; lỗi in `<file>:<dòng>: <lý do>`, mã 2, không ghi gì. Bản gộp phải tính mỗi request ít nhất bằng
  từng bản (trừ request đã đóng `failed-unsent`), không thì mã 2 `the copies disagree`: sửa tay rồi gộp lại. Các dòng đang có trong `OUT` **luôn được giữ**, dù `OUT` có nằm trong danh sách đầu vào hay
  không (gộp không bao giờ làm mất dòng đã tính phí). Dùng mỗi khi có hai bản ledger
  của một tập (hai phiên, hai file trên Drive, bản Drive + bản trong container): **không bao giờ** "lấy bản mới nhất"
  cho ledger, vì bản kia chứa các request đã tính phí (§11.6).
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
  duyệt tải lên `ClaudeFilmLab/<ProjectName>/04_SanXuat/<thư mục tập>/<YYYY-MM-DD>/`. Đường dẫn trong zip tính từ
  `out/<project>/<id>/`: khôi phục = kéo zip từ Drive và giải nén ngay trong `out/<project>/<id>/` (file về đúng
  `plates/`, `clips/`, `renders3d/`). Tập `method: blender`: gói có thêm các thư mục `renders3d/s03[_v<NN>|_preview|_keys]/`
  của shot, chỉ file ở cấp đầu (`beauty.mp4` – bản compositor dùng –, `render.json`; `_keys`: `first.png`, `last.png`,
  `keyframes.json`); thư mục khung PNG (`beauty/`, `depth/`, `normal/`, `line/`, `mask/`; ~3 MB mỗi khung 1080p) không
  vào gói, trừ `beauty/` của render không có `beauty.mp4` (`--no-mp4`), hoặc khi thêm `--with-frames`. Turntable G2
  (`renders3d/turntable-<asset>/`): thêm `--with-turntables` vào gói của shot mẫu G2.
- Render (`renders/*`: bản nháp, bản cuối), lời bình (`vo/`) và âm thanh (`audio/`) không chờ duyệt: tải riêng từng file
  lên `04_SanXuat/<thư mục tập>/_ChuaDuyet/` **ngay khi tạo xong** (§11.6, mục "Media chưa duyệt"); duyệt xong bản nháp
  chuyển sang `04_SanXuat/…/<YYYY-MM-DD>/`, bản cuối sang `05_ThanhPham/<thư mục tập>/`.
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
| Lưu Drive từng file | Media: gói zip theo shot (`tools/bundle.py`); ảnh pro/4K từ Lambda tải từ S3 về `out/` rồi vào gói như mọi ảnh. File chữ của dự án: từng file, bản mới thay bản cũ theo §11.6 |
| Reviewer có Bash giới hạn | Reviewer không có Bash; số đo do `tools/check_episode.py` ghi ra `review/check-v<N>.txt` |
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
├── 04_SanXuat/<thư mục tập>/            ledger.csv · <YYYY-MM-DD>/ gói shot (tools/bundle.py), bản nháp đã duyệt · _ChuaDuyet/ render, vo/, audio/ chưa duyệt (§11.6)
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
| `04_SanXuat/<thư mục tập>/_ChuaDuyet/` | `out/<project>/<id>/renders/*` (bản nháp, bản cuối, thumbnail), `vo/**` (trừ `_stale/`), `audio/**` | chỉ đẩy, **ngay khi tạo xong**, chưa duyệt (§11.6) |
| `04_SanXuat/<thư mục tập>/<YYYY-MM-DD>/` | `out/<project>/<id>/bundles/*.zip`; bản nháp đã duyệt | gói: chỉ đẩy, sau khi duyệt; bản nháp: chuyển từ `_ChuaDuyet/` (`update_file`) khi G3 qua |
| `05_ThanhPham/<thư mục tập>/` | bản cuối đã duyệt | chuyển từ `_ChuaDuyet/` (`update_file`) khi G4 qua |
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
   `parentId = '<id>' and trashed = false`, tải từng file chữ bằng `download_file_content` rồi **ngay sau đó** ghi
   xuống đĩa: `python3 tools/drive_sync.py save projects/<project> --id <fileId> --to <đường dẫn> --size <fileSize>`
   (nhiều nhóm `--id … --to … --size …` trong một lệnh được). Connector trả base64 vào hội thoại, không ghi ra đĩa;
   `save` đọc kết quả mới nhất của ID đó trong bản ghi phiên (`~/.claude/projects/<thư mục repo>/*.jsonl`, cả
   `subagents/`; không thấy thì mọi dự án; bản ghi khác: `--transcript <glob>`), giải base64 (chuẩn hoặc url-safe), so
   kích thước với `--size`, ghi file nguyên tử rồi đánh dấu như `pulled` (khi đã có snapshot). Phiên local: connector
   có thể tự lưu file và chỉ trả `Binary content (<mime>, <n>KB) saved to <file>` (`…/tool-results/mcp-…-blob-*.<đuôi>`,
   nội dung thô); `save` dò dòng đó như trên và chép file được nêu (chỉ nhận file nằm trong kho bản ghi Claude). Cần chỉ
   thẳng file: `--from-file <file> --size <fileSize>` sau `--id` (không dò bản ghi; bắt buộc `--size`). **Không bao giờ chép lại
   chuỗi base64 bằng tay** (tốn gấp đôi ngữ cảnh, sai một ký tự là hỏng file). Mỗi file vẫn đi qua ngữ cảnh một lần
   (≈ 1,33 × kích thước file), nên vẫn kéo theo khâu, không kéo cả cây. `--to` tương đối với `projects/<project>/`,
   hoặc bắt đầu bằng `projects/<project>/` / `out/<project>/`; đường dẫn ra ngoài dự án (kể cả qua symlink) bị từ chối.
   `save` từ chối (mã thoát 1, không ghi gì) khi file đích có thay đổi chưa đẩy: muốn so với bản Drive thì lưu cạnh
   nó (`--to <file>.orig`, file tạm không bao giờ đẩy); `--force` chỉ khi chắc chắn bỏ phần sửa. Không in nội dung file.
   Thư mục con chưa có trong manifest thì thêm ID vào `PROJECT.md`. `TienDo_SanXuat` tải với `exportMimeType: text/csv`.
3. Một thư mục có hai file cùng tên (lần đẩy trước bị ngắt giữa chừng): lấy file `modifiedTime` mới nhất, chuyển file
   cũ vào `99_LuuTru/` theo bước 3 của mục đẩy. **Ngoại lệ `ledger.csv`:** tải **mọi** bản về
   (`out/<project>/ep<NN>/ledger.drive-1.csv`, `…-2.csv`) rồi gộp, không chọn bản mới nhất:
   `python3 tools/ark.py ledger-merge out/<project>/ep<NN>/ledger.drive-*.csv -o out/<project>/ep<NN>/ledger.csv`
   (§7); lần đẩy ledger kế tiếp sẽ đưa các bản cũ vào `99_LuuTru/`.
4. Chụp dấu bản vừa kéo và ghi giờ kéo (UTC), **một lần** sau lần kéo đầu của container:
   `python3 tools/drive_sync.py snapshot projects/<project> --include-out out/<project>` (từ thư mục gốc repo).
   Đã có snapshot (kéo thêm theo khâu, container cũ còn sống): `python3 tools/drive_sync.py pulled projects/<project>
   <các file vừa kéo>` – chỉ thay dòng của các file đó, không đụng `.pulled.at`, không ghi `.pushed.log`. `snapshot`
   từ chối (mã thoát 1, không ghi gì) khi còn thay đổi chưa đẩy, vì chụp lại sẽ đánh dấu chúng là đã đẩy; `--force`
   chỉ dùng khi chắc chắn bỏ các thay đổi đó khỏi danh sách đẩy. File tạm (`*.b64`, `*.orig`, `*.bak`, `*.tmp`,
   `*.part`, `*~`) và `ledger.drive-*.csv` không vào dấu, không vào danh sách đẩy.
   Lỡ tạo file mới trước lần chụp dấu đầu: `snapshot projects/<project> --only <các file/thư mục vừa kéo>` chỉ chụp
   những file đó (file khác vẫn là NEW); đã có snapshot thì `--only` từ chối, dùng `pulled`. `snapshot` không có
   `--include-out` giữ nguyên các dòng `out/<project>/…` của dấu cũ. File là symlink trỏ ra ngoài `projects/<project>/`
   và `out/<project>/` không vào dấu; `plan` in nó là UNMAPPED, `pulled`/`record`/`save` từ chối.
   Lệnh ghi `projects/<project>/.pulled.sha256` (định dạng `sha256sum`: `<hex>  <đường dẫn>`, đường dẫn như
   `find projects/<project>` in ra, media dạng `out/<project>/…`; không có file nào bắt đầu bằng `.`) và
   `projects/<project>/.pulled.at` (`2026-11-10T15:30:00Z`). Tương đương bằng shell khi không chạy được công cụ:
   `find projects/<project> -type f ! -name '.*' -print0 | sort -z | xargs -0 sha256sum > projects/<project>/.pulled.sha256`
   và `date -u +%Y-%m-%dT%H:%M:%SZ > projects/<project>/.pulled.at`. Mọi lần tải lên trong phiên ghi một dòng
   `<giờ UTC> <đường dẫn bản làm việc> <ID Drive mới>` vào `projects/<project>/.pushed.log` (`drive_sync.py record`).

**Media chưa duyệt (ngay khi tạo xong, trước mọi cổng):** container cloud bị thu hồi khi rảnh và mọi thứ chỉ có trong
`out/<project>/` mất theo (SHK Q1·T3, 11/2026: bản 600 s gồm 101 file lời bình và `final_v02.mp4` chờ G4 bị mất vì quy
tắc cũ chỉ đẩy media sau khi duyệt). Vì vậy `renders/*`, `vo/**` (trừ `_stale/` và file tạm `*.raw.wav`, `*.tempo.wav`)
và `audio/**` của mỗi tập được đẩy ngay sau khi agent tạo xong, vào `04_SanXuat/<thư mục tập>/_ChuaDuyet/` (render ở
gốc thư mục đó, `vo/`, `audio/` giữ thư mục con), theo các bước đẩy dưới đây (`plan` ánh xạ sẵn, `record` sau mỗi lần
tải). Người dùng duyệt → không tải lại: `update_file` file đã tải (ID trong `.pushed.log`) đổi `parentId` sang thư mục
ngày `04_SanXuat/<thư mục tập>/<YYYY-MM-DD>/` (bản nháp, G3) hoặc `05_ThanhPham/<thư mục tập>/` (bản cuối, G4); dòng
`note` của `plan` in sẵn đích. `vo/`, `audio/` ở lại `_ChuaDuyet/`. Bản không được duyệt cũng ở lại (không xoá).
Mọi lần `plan` (có hay không `--include-out`) quét `out/<project>/<id>/` và in `!!! UNSAVED MEDIA: N file(s) not on
Drive (renders …, vo …, audio …)` ở đầu và cuối khi còn file như vậy không có dòng cùng mã băm trong `.pulled.sha256`
(kèm số plate/clip chưa vào gói nào); `status.py` in dòng `UNSAVED media` trong mục `MEDIA`. Còn dòng đó thì chưa dừng
phiên cloud. Phiên local trên máy chủ lab không mất file khi dừng, nhưng vẫn đẩy như vậy để Drive là nguồn gốc.

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
   trong tên zip, ảnh khóa; render, `vo/`, `audio/` vào `_ChuaDuyet/`); `plates/`, `clips/` không đẩy riêng (nằm trong gói shot).
   `TienDo_SanXuat.csv` được tách riêng (`[sheet]`, bước 5), không tải lên như file chữ. File không có ánh xạ (UNMAPPED)
   hay thư mục thiếu ID → mã thoát 1: tạo thư mục (`create_file` folder, `parentId` = ID cha), ghi ID vào
   `drive.folders`, chạy lại `plan`. File gốc trong `sources/` đã sửa thì không lập (chỉ `DanhMuc.csv` được sửa).
   Shell tương đương: các dòng `>` của
   `find projects/<project> -type f ! -name '.*' ! -name TienDo_SanXuat.csv -print0 | sort -z | xargs -0 sha256sum | diff projects/<project>/.pulled.sha256 - | grep '^>'`,
   cộng `out/<project>/<id>/ledger.csv` nếu khâu vừa rồi có tạo ảnh/video.
2. Mỗi file (đúng các tham số `plan` in ra): `create_file` vào thư mục tương ứng (ID từ manifest), `title` = tên file, `base64Content` =
   `sha256:<hex>:<đường dẫn tuyệt đối>` (hex từ `sha256sum`), `contentMimeType` (`.md` `text/markdown`, `.csv` `text/csv`,
   `.json` `application/json`, `.yaml`/`.txt` `text/plain`), `disableConversionToGoogleType: true`. Tải lên thành công →
   ngay lập tức `python3 tools/drive_sync.py record projects/<project> --uploaded <đường dẫn> --id <ID mới>
   --sha256 <hex>` đúng như `plan` in ra (thay đúng dòng của file trong `.pulled.sha256`, thêm dòng vào
   `.pushed.log`). `--sha256` là bản đã tải lên: file bị sửa sau lúc tải thì `record` in `WARN … still to push` và
   file vẫn là CHANGED ở lần `plan` sau. `record`/`pulled` chỉ nhận file trong `projects/<project>/` hoặc
   `out/<project>/` (mã thoát 2); chạy song song nhiều lệnh `record` được (có khoá `.drive_sync.lock`).
3. **Quy tắc phiên bản (chọn vì đơn giản và chắc):** connector không ghi đè được nội dung file (`update_file` chỉ sửa
   tên, thư mục, thuộc tính), nên lịch sử phiên bản của Drive không dùng được. Mỗi lần đẩy là **file mới**; chỉ sau khi
   tải lên thành công, tìm bản cũ ngay lúc đó bằng `search_files` (`parentId = '<id thư mục>' and title = '<tên file>'
   and trashed = false`) – không dựa vào ID nhớ từ lúc kéo, vì đẩy nhiều lần trong phiên hoặc ngữ cảnh bị nén sẽ làm
   mất ID – rồi **mọi kết quả trừ ID vừa tạo** được `update_file` chuyển vào `99_LuuTru/` (`parentId`) và đổi tên
   `<đường dẫn logic của thư mục, '/' → '__'>__<tên không đuôi>_<YYYYMMDD-HHMM>.<đuôi>` (giờ UTC lúc thay), vd.
   `03_KichBan__ep01-bac-thi__script_20261110-1530.md`. Kết quả: mỗi thư mục luôn có đúng một bản hiện hành mỗi tên;
   mọi bản cũ nằm ở `99_LuuTru/`, tìm lại được theo tên. Tải lên trước, chuyển sau: bị ngắt giữa chừng chỉ để lại
   bản trùng (bước 3 của mục kéo xử lý), không bao giờ mất bản nào.
   **`ledger.csv` trước khi đẩy:** phiên khác có thể đã đẩy ledger của cùng tập sau lần kéo. `plan` in sẵn các bước
   này thành khối `pre` ngay trước dòng `create_file` của ledger (JSON: `pre.ledger_merge`) và ghi chú `ledger: push
   after every stage that generated; no approval gate` – ledger không chờ duyệt như media. Tải bản đang ở Drive về
   `out/<project>/ep<NN>/ledger.drive-1.csv`, `ark.py ledger-merge out/<project>/ep<NN>/ledger.csv
   out/<project>/ep<NN>/ledger.drive-1.csv -o out/<project>/ep<NN>/ledger.csv`, xoá bản tạm, rồi mới đẩy bản đã gộp
   (bản trên Drive luôn là tập con của bản vừa đẩy, nên chuyển nó vào `99_LuuTru/` không mất dòng nào). Khi các
   `ledger.drive-<n>.csv` còn trên đĩa và mọi dòng của chúng đã có trong ledger, `plan` in `pre done` (JSON:
   `done: true`, `unmerged: []`) thay cho các bước: xoá bản tạm rồi tải lên.
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
   `snapshot` sau khi đẩy). `plan` chạy lại phải in `Nothing to push.` (trừ file cố ý chưa đẩy; còn plate/clip chưa nằm trong gói nào thì
   dòng đó là `Nothing to push (text). N plate/clip file(s) are in no bundle…` – media ấy chỉ có trong container); ghi giờ đẩy vào cột cuối dòng
   `## Nhật ký` của EPISODE.md.
7. Mỗi lần tải lên người dùng duyệt: gom file của một khâu đẩy một lượt, báo trước danh sách.

**Media:** gói shot, bản nháp, bản cuối, ảnh khóa chỉ đẩy sau khi người dùng duyệt (§9); đã có trên Drive thì kéo về
khi cần, không tạo lại bằng API.

### 11.7 Không xoá

Không xoá, không `trash_file` gì trên Drive. Thứ không dùng nữa (bản cũ, tập huỷ, ảnh hỏng đã lỡ tải lên) chuyển vào
`99_LuuTru/` bằng `update_file` (`parentId`), đổi tên theo §11.6 bước 3 nếu có thể trùng tên.
