# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/), phiên bản theo [SemVer](https://semver.org/lang/vi/).

## [Unreleased]

### Xem trực tiếp bản dựng 3D và render: `tools/review/` (2026-11-25, nhánh `claude/review-tool`)
- Web app tự host (Docker `python:3.13-alpine`, chỉ thư viện chuẩn; SQLite trong volume; ngrok cho URL công khai, không
  đăng nhập theo lựa chọn của chủ lab): bảng theo dõi trực tiếp (SSE), **bản vẽ dựng** (phần hình mới của mỗi bước vẽ
  bằng nét cyan rồi thành khối, đường kích thước, phát lại), xem model GLB (OrbitControls, khung dây/pháp tuyến/đất sét,
  hoạt hình), **dòng thời gian** kiểu CapCut chỉ để duyệt (dạng sóng, đánh dấu, vùng lặp, A/B, cắt/đổi thứ tự → edit.json).
- Cổng công khai 8790 chỉ đọc (Range, CSP chỉ script cùng nguồn, chặn path traversal); cổng ghi 8791 chỉ 127.0.0.1.
- `review.py up|down|url|status|publish-video|publish-model`; `client.py` không bao giờ làm hỏng hay làm chậm lệnh gọi;
  `bpy_snapshot.py` + `demo_build_giot.py` (Giọt dựng 10 bước); `--review BUILD` cho `blender.py render|turntable|keyframes`
  và `comfy.py run`; `vendor_three.py` chép three.js 0.186.1 đã ghim (example ghim trong `three-examples.lock`).
- **Thẻ Máy và ComfyUI** trên bảng theo dõi: `monitor.py` (máy chủ lab, chỉ thư viện chuẩn) gửi mỗi 2 giây CPU, RAM, GPU %,
  VRAM, nhiệt độ, công suất GPU, dung lượng trống mọi ổ cố định và tên job nặng (chỉ nhãn trong danh sách cho phép, không
  dòng lệnh/đường dẫn), cùng tiến độ ComfyUI đọc từ log tqdm (bước i/n, s/bước, ETA, %, 10 lượt gần nhất; nối với build
  khi job chạy bằng `comfy.py run --review`). Biểu đồ canvas 10 phút / 24 giờ (SQLite trung bình 1 phút), màu cảnh báo
  VRAM > 90 %, > 83 °C, ổ < 10 GB. `/api/metrics`, `/api/comfy`; SSE tối đa một sự kiện mỗi loại mỗi 2 giây.
  `review.py up|down|status|monitor` bật/tắt/xem monitor (`out/_review/monitor.pid`).
- Sửa: chuyển từ một build sang build khác khi trang trước còn tải GLB làm model của build trước hiện trong trang sau;
  mỗi trang giờ vẽ vào khung riêng, trang cũ bị huỷ khi tải xong (`web/route.js`, test node).

#### Sửa sau review PR #48
- **Lộ thông tin**: `comfy.py` và `blender.py` chỉ gửi lên server loại lỗi cố định (`failed: execution error`,
  `failed: prompt refused`, `failed: blender error`…) và tên file (`turntable chuc-long.glb (ink-wash)`), không bao giờ
  đường dẫn tuyệt đối, nội dung ngoại lệ, prompt hay `node_errors` (chi tiết vẫn ở ledger và stderr). `server.py` và
  `client.py` cùng lọc mọi trường chữ (tiêu đề, nhãn, thông báo, bước hiện tại, stats): đường dẫn kiểu `C:\…`, `D:/…`,
  `/home/…`, `/mnt/…`, `\\server\…`, `~/…` thành tên file, cắt độ dài.
- **Chống DoS**: tối đa 64 luồng SSE cùng lúc (quá thì 503 + `Retry-After`), mỗi luồng SSE sống tối đa 10 phút
  (EventSource tự nối lại); socket timeout 15 giây khi đọc request, hạn 20 giây cho cả phần đầu request (chặn
  slow-loris), 60 giây cho mỗi khối file gửi đi, 30 giây cho người đọc SSE bị kẹt.
- **DNS rebinding trên cổng ghi**: cổng 8791 chỉ nhận `Host` là `127.0.0.1|localhost|[::1]:<cổng>` (một header `Host`
  duy nhất; thêm tên khác bằng `--ingest-host`/`REVIEW_INGEST_HOSTS`) và mọi POST phải có header `X-Film-Review: 1`
  (403 nếu thiếu). `client.py` tự gửi header (mọi publisher đi qua nó; `monitor.py` dùng `client.INGEST_HEADERS`), người
  gọi không phải đổi gì. Giữ dữ liệu có giới hạn: ≤ 500 build (bỏ build cập nhật lâu nhất), ≤ 2000 bước, ≤ 500 render,
  ≤ 200 job mỗi build, lịch sử máy ≤ 24 giờ + 60 dòng.
- **CSP**: `connect-src 'self' blob:` để Chromium tải được texture nhúng trong GLB.
- **`review.py down` / pid**: chỉ giết tiến trình đã kiểm (`ngrok.pid` phải là ngrok(.exe); `monitor.pid` phải là python
  chạy `tools/review/monitor.py`, đọc dòng lệnh bằng PowerShell `Get-CimInstance Win32_Process` hoặc `/proc`); pid cũ hay
  của chương trình khác thì xoá file pid, không giết; `up` không còn bỏ qua việc bật monitor vì pid cũ.
- `monitor.py`: kẹp số đo vào đúng khoảng server nhận trước khi gửi; server trả 4xx thì ghi log (mỗi thông báo một lần),
  gửi bản rút gọn (chỉ số chính) và không lùi thời gian; chỉ lùi khi mất kết nối hoặc 5xx.
- Web app: bản chụp `/api/builds` đầu tiên không còn ghi đè cập nhật SSE mới hơn (gộp theo `updated`); đường dẫn `#/…`
  mã hoá hỏng mở bảng theo dõi kèm thông báo thay vì trang trắng.

### Engine local: Blender (3D) và ComfyUI + MiniMax H3 (video AI tại chỗ) (2026-11-25, nhánh `claude/local-engines`)
Chạy trên máy của chủ lab (RTX 5070 Ti 16 GB), miễn phí, dùng app và model **đã cài sẵn** (Blender 5.3, Comfy Desktop với
MiniMax H3); không tải model nào. Thiết kế: `docs/superpowers/specs/2026-11-25-local-engines-design.md`.

- **`tools/blender/`**: render 3D chạy nền bằng Blender 5.3 từ `shot3d.json` v1 (asset thủ tục: núi, đá, thông, nước,
  đất, linh vật Giọt; hoặc file `.glb`; 9 chuyển động máy như `tools/toon/project.js`), 4 look `grey-layout`, `clay`,
  `toon-ink`, `ink-wash`; pass depth (16-bit, dải cố định), normal, line, mask; `render.json`; cùng khung render hai lần
  ra cùng byte. CLI `blender.py find|check|render|still|turntable|keyframes|lookbook`; `keyframes` cho khung đầu/cuối
  1344×768 để làm clip H3. EEVEE ~2 s/khung ở 1080p cho look mực, < 1 s cho look phẳng.
- **`tools/comfy/comfy.py`**: clip AI tại chỗ qua ComfyUI + **MiniMax H3**: `h3-i2v` (khung đầu, tuỳ chọn khung cuối),
  `h3-r2v` (tối đa 9 ảnh tham chiếu + neo ảnh theo giây); 24 fps, lưới 17k+5 khung, 1344×768 (nháp 864×480), khung đầu
  cắt 7:4 + lanczos trước khi gửi, không negative, 20 bước (`--turbo` chỉ cho nháp); clip có tiếng. `start` chạy Python
  của Comfy Desktop không giao diện, `--offline`; input/output/temp vào `out/_comfy/` (không đụng thư mục của Desktop
  trên ổ C:); `run` từ chối node ngoài danh sách cho phép (node API MiniMax trả phí không bao giờ qua), ghi ledger
  `comfy:<workflow>` + file `.json` cạnh clip (seed, hash graph, model). `ping|models|workflows|install|interrupt`;
  `install` không bao giờ tải model. Đo trên máy chủ lab: clip 5,17 s 1344×768, 20 bước = 713 s GPU (~12 phút).
- **`tools/ark.py`**: khoá ledger chạy được trên Windows (msvcrt); dòng `comfy:*`/`blender:*` không trừ trần nào; trạng
  thái cuối mới `interrupted`.
- **Phương pháp thứ tư `method: blender`** và khoá **`video_engine: seedance | comfy`** trong `EPISODE.md`:
  `check_episode.py` (style `engine: blender`, mã lớp `A-<asset>`, `shots3d/s<NN>.json` kiểm bằng `tools/blender/spec.py`,
  `renders3d/`, `ASSETS.md`; tập `blender` có `ai_motion` phải ghi rõ `video_engine`), `status.py` (dự báo phút GPU,
  mục LOCAL), `doctor.sh` (dòng `blender`, `comfy`; `n/a` ở cloud).
- Style `thuy-mac-blender`, `toon-3d-blender` (draft); agent mới `film-3d-artist`; mẫu `shot3d.json`, `ASSETS.md`;
  tài liệu `blender-method.md`, `local-video.md`, WORKFLOW, CONVENTIONS, MODELS, RUNBOOK, CLAUDE.md (quy tắc: engine local
  chỉ ở phiên local; không tải app/model khi chưa hỏi).
- Sửa sau review:
  - `bundle.py`: gói shot của tập `blender` có `renders3d/<shot>[_v<NN>|_preview|_keys]/` (`beauty.mp4`, `render.json`,
    khung `_keys`; không chuỗi PNG trừ `--with-frames` hoặc render không có mp4); `--with-turntables` cho G2; giải nén
    gói trong `out/<project>/<id>/` là khôi phục được render (check_episode, CONVENTIONS, skill ghi cùng một cách).
  - `comfy.py run --keep-frames` tách khung vào `clips/<tên clip>/raw/000001.png` (đúng chỗ `check_episode` nhận và
    `matte_seq.py` đọc), không còn `<tên>_frames/0001.png` bị báo ERROR.
  - Mã lớp `A-<asset>` và thư mục `turntable-<asset>` nhận dấu `_` như id asset của `spec.py`; regex `renders3d/`
    chuyển về `episode_id.py`.
  - `blender.py find` thoát mã 3 khi thấy Blender mà `--version` lỗi; `doctor.sh` báo WARN (trước đây lẫn với "không có").
  - `comfy.py interrupt`: lỗi mạng ở từng id được báo riêng, các id còn lại vẫn xử lý, cuối cùng thoát mã 1.
  - `comfy.py run --steps 0` bị từ chối (mã 2), không lặng lẽ thành 20 bước.
  - `ark.py ledger-close` trên dòng `comfy:`/`blender:` báo "không tốn gì" (thay vì "vẫn tính vào trần") và gợi ý
    `comfy.py interrupt`, không gợi ý `--resume-task`.
  - Bỏ chữ "Wan" lỗi thời (check_episode, `looks.json`): engine local là MiniMax H3 (`tools/comfy/comfy.py`); test chặn tái phát.
  - THIRD_PARTY.md: hai workflow H3 phỏng theo Comfy-Org/workflow_templates (MIT, đã kiểm `LICENSE`); `.meta.json` ghi nguồn.
  - CLAUDE.md, WORKFLOW §4, agent `film-animator`: ngoại lệ của quy tắc `--budget/--ledger` cho engine local
    (`comfy.py run` chỉ `--ledger`; dòng `comfy:*`/`blender:*` tính 0).

## [1.3.0] - 2026-11-25

### Đợt sửa issue mở (#45, 2026-11-25)
Bảy gói việc làm song song, mỗi gói một nhánh, gộp và chạy lại cả bộ test (`bash tools/ci.sh`). Không có request tính phí nào.

#### Ngân sách và ledger (#15, #13 phía dùng)
- `ark.py ledger-merge` kiểm mọi dòng trước khi ghi (lỗi `<file>:<dòng>`, mã 2, không ghi gì), gộp dòng không `req=` theo
  bội, kết quả không phụ thuộc thứ tự đầu vào, từ chối khi bản gộp tính một request ít hơn một bản; `req=` chỉ nhận cả cụm hex.
- Lệnh mới `ark.py ledger-close --req <id> --ledger L --status abandoned`: đóng request mồ côi, vẫn tính vào trần;
  `status.py` in lệnh này ở mọi dòng OPEN và coi `abandoned` là đã đóng.
- Agent (`FILM_AGENT`) bị từ chối `--no-budget` và `--force` (mã 2).
- `lambda-job finish`: `sent: false` → `failed-unsent` (không tính); job `running` quá `deadline` + 60 s → báo worker chết,
  `--give-up` ghi `failed`; WARN khi `worker_sha256` khác repo; status/ảnh là trang lỗi S3 → mã 2.
- `ark.py image`: phản hồi không có ảnh → `failed`; ảnh phụ không bao giờ ghi đè file; `--size 0K/0x0` là kích thước lạ.
- `ark.py video --resume-pending --ledger L`: tải tiếp mọi task video đang mở.
- Test 8 tiến trình tranh trần 1 ảnh: đúng 1 dòng `pending` (chứng minh `reserve()` chặn tiêu vượt khi chạy song song).

#### Kéo file từ Drive (#36)
- `drive_sync.py save`: ghi file vừa tải bằng `download_file_content` xuống đĩa từ bản ghi phiên (kể cả agent con,
  `--transcript`), kiểm `--size`, ghi nguyên tử, không ghi đè thay đổi chưa đẩy, tự đánh dấu đã kéo; không còn chép base64 bằng tay.
- `drive_sync.py snapshot --only <file…>`: chụp dấu lần đầu chỉ cho các file vừa kéo.
- `snapshot` không có `--include-out` giữ các dòng `out/<project>/`; symlink trỏ ra ngoài dự án bị từ chối
  (`pulled`/`record`/`save`) và hiện UNMAPPED trong `plan`; khối `pre` của ledger in `pre done` khi mọi
  `ledger.drive-<n>.csv` đã gộp.

#### Lồng tiếng và âm thanh (#37, #8 một phần)
- Cài sẵn lồng tiếng: `docs/setup-script.sh` (v4) bước 3b cài `vieneu==3.8.3`, torch CPU và `resemble-perth==1.0.1` theo
  `requirements-tts.txt` (lỗi chỉ là WARN; `FILM_TTS=0` bỏ qua, `FILM_TTS_PREFETCH=1` tải sẵn model).
- `tools/doctor.sh` thêm dòng `tts`, `tts-watermark` và cờ `--episode <tập>` (FAIL thiếu watermark khi tập đã qua G3 và có lời bình).
- `vieneu_tts.py --require-watermark` (mã 4, trước khi nạp model); `film-narrator` dùng cho mọi lần render; `--check` tính
  lại khung theo mốc hiện tại (`--strict`: OVER là lỗi), khoá thư mục `vo/`, lỗi ffmpeg khi đổi tốc độ giữ bản đọc cũ,
  báo wav mồ côi không có mục log.
- Đọc số: phân số, số âm, tháng, ngày dd-mm-yyyy, khoảng thế kỷ/La Mã (`thế kỷ XIV–XV`); `a/b` đứng một mình là phân số.
- `status.py --gate G4` kiểm watermark của mọi bản đọc trong `vo/tts-log.json`.
- `score.py` 1.1.0 ghi qua thư mục tạm (lỗi ghi: mã 1, giữ bộ cũ), xoá stem con cũ khi `--overwrite`, tối đa 16 nốt mỗi lần rải.

#### Lược đồ tập và bộ kiểm (#28, #35 mục 1–2)
- Plate tư thế `L4b`…`L4z` được nhận ở mọi công cụ: `check_episode.py`, `anchors.py`, `matte.py` (tách như `L4`),
  `status.py`, `bundle.py`; một định nghĩa chung trong `tools/episode_id.py`.
- Id shot ba chữ số `s<NNN>` cho tập trên 99 shot; trộn `s<NN>`/`s<NNN>` trong một tập là ERROR.
- Tập `method: code`: cột `layers` nhận thêm `M-<model>`; `check_episode.py` đọc từ vựng chuyển động TOON thẳng từ
  `motions.json` (id mới hợp lệ ngay, id `toon/project.js` là giá trị `camera`); id sai nhánh là WARN.
- Kiểm phủ (check-5): hai bản `approved=yes` của một lớp là ERROR; file trong `plates/` không có dòng `prompts.csv` là WARN;
  từ khâu 8, shot `seedance` có `ai_motion` mà thiếu clip là ERROR.
- Checker: khóa YAML ghi hai lần (EPISODE.md, budget.yaml) là ERROR; ``` trong chú thích HTML không còn nuốt lời bình;
  `--probe` in format đã dùng và WARN khi không kiểm được thời lượng bản cuối; tên báo cáo thống nhất `review/check-v<N>.txt`.

#### Bộ ghép COMPOSE 1.4.0 (#4 một phần)
- Vải, tư thế, mí mắt vẽ trong một lượt `drawPlate` (hết chồng hai lần ở chỗ nối khi mờ dần, `blur` áp cả lớp, mí nằm
  trên vải); khoá `sway` theo shot, `root: [x, y]`, salt băm (cây trong film cũ đổi pha lắc sau khi làm mới).
- `embers` và `glow` theo alpha của khung; `COMPOSE.rgb` đọc `rgb()` và tên màu; chặn NaN khi thời lượng bằng 0; bước
  chân `figure` luôn trong 10–38 % chiều cao, chân đã đặt không trượt khi quay người.
- `inline.py`: ghi nguyên tử, giữ CRLF, tỉ lệ khung theo `--size`, cảnh báo thiếu dòng cỡ mặc định, đường dẫn anchors
  tìm được từ mọi thư mục; `demo_plates.py --help` không tạo gì.
- Mới: `inline.py <film.html> --preflight` (chạy thử mọi shot bằng node, báo ERROR/WARN, thoát 1 khi có ERROR).

#### Dị thú và sơn thủy 3D bằng code (#35)
- Dị thú 3D bằng code (`tools/toon/creature.js`): spec + seed, thân loft theo spline, 0/2/4/6 chân không trượt, nhiều
  đuôi trễ pha, cánh, sừng, tai, bờm, 1–3 mắt; đi, chạy, bơi, bay, quay, nhìn, vỗ cánh, xòe đuôi, thở, chớp mắt; ba con
  mẫu `mac-loc`, `van-dieu`, `luc-tuc-ngu` (thiết kế của lab). Thông số model: `code-method.md` §8.
- Look `ink-wash-3d` (`tools/toon/ink3d.js`) và style `thuy-mac-3d` (số 12): mực loang bậc theo thớ giấy, viền mực mảnh
  dần theo khoảng cách, núi ba tầng có nét thuân, sương, mặt nước có vòng sóng; motion mới `head-turn`, `tail-fan`,
  `wing-flap`, `fly`, `swim`, `fly-through`, `ink-reveal-3d`, `water-ripple`, `brush-write`.
- `toon.py still|turntable|clip|lookbook --creature <mẫu|spec.json>`; bộ TOON 1.2.0.
- Sửa: `tools/toon/three.lock` chưa từng được commit (`.gitignore` `*.lock` nuốt mất) nên `install_three.sh`, `doctor`
  dòng `three` và setup bước 6 hỏng trên bản clone mới (`--check` còn báo ok khi chưa cài gì); thêm ngoại lệ
  `.gitignore`, file lock (three 0.186.1), `install_three.sh` từ chối khi thiếu lock, test.

#### Test, CI, doctor
- Test chạy được bằng user thường: đường dẫn cinecode lấy từ `CINECODE_DIR` hoặc `~/.claude/skills/cinecode`; hết 2 lỗi
  import ở `test_audio.py` / `test_compose.py`.
- CI: `tools/ci.sh` (`--install` cài `requirements-ci.txt`), mẫu workflow `docs/ci/tests.yml` để chủ dự án chép tay vào
  `.github/workflows/tests.yml`.
- `tests/test_docs.py`: kiểm đường dẫn, lệnh con và cờ mà CLAUDE.md, docs, skill, agent nhắc tới có thật trong mã; kiểm
  front matter của agent và skill.
- doctor: phân biệt "không có trả lời" với "trả lời không phải JSON" ở ark-ping; lệnh thử video nhận 2xx không phải object
  thì báo có thể đã tạo task; thêm kiểm python ≥ 3.10, ổ trống (WARN < 5 GB), dấu phiên bản setup script, và (chế độ
  đầy đủ) mở Chrome headless qua `CHROME_PATH`.
- Hook khởi động trong git worktree không chạy pip, không ghi đè dấu cài đặt.
- Setup script v4 ghi dấu `/opt/film-lab/setup-script.version`: **dán lại setup script** vào môi trường cloud để doctor hết WARN.

#### Sửa sau review PR #45
- Lời bình: `1/1000` đứng một mình đọc là phân số (trước đây thành "tháng một năm một ngàn"); `m/yyyy` chỉ đọc là tháng
  năm sau `tháng` hoặc một từ dẫn (`vào`, `từ`, `đến`, `cuối`, `đầu`, `giữa`, `trước`, `sau`, `hồi`, `khoảng`);
  `ngày 2-9` đọc "ngày hai tháng chín", còn `ngày 3-5 tháng 6` vẫn là khoảng ngày.
- `drive_sync.py plan` dùng chính phép gộp của `ark.py ledger-merge` để xét bản ledger trên Drive đã gộp chưa: hai dòng cũ
  giống nhau (không `req=`) hay một request tính nhiều hơn ở bản Drive không còn bị báo `pre done`.
- Cổng G4: lời bình đọc từ `vo-lines.json` (`--lines`, id khác `VO<n>`) được kiểm watermark thay vì bị báo thiếu.
- `preflight.cjs`: đọc kích thước JPEG có khối EXIF/ICC lớn hơn 64 KB; `--fps N` đặt trước đường dẫn film không còn bị hiểu
  là tên file.

## [1.2.0] - 2026-11-25

### Phương pháp dựng thứ ba `code` và bộ 11 phong cách vẽ bằng code (#38–#43, 2026-11-19 / 24)
Nhân vật và cảnh vẽ hoàn toàn bằng code, không gọi model tạo ảnh hay video nào (0 ảnh, 0 giây). Một nhân vật định nghĩa
một lần, đổi phong cách chỉ là đổi cách vẽ. Ý tưởng từ một bài đăng "10 animation styles" chủ dự án gửi; linh vật,
tên và bố cục là của lab.

- **Bộ TOON `tools/toon/`** (v1.0.0, script thuần như bộ COMPOSE, hàm thuần của `t` và `SEED`): `rig.js` (nhân vật =
  `character.json`: thân `drop`/`blob`/`box`, 1–2 mắt, chỏm, má, miệng, tay chân ống; khung xương, IK hai đoạn),
  `motion.js` (timeline `walk`, `run`, `turn`, `jump`, `wave`, `cheer`, `point`, `bounce`, `look`, `blink`, `idle`;
  bước chân tính theo quãng đường nên **chân không trượt** ở mọi tốc độ; quay người đặt lại chân; nhảy có nén – bật –
  bay – tiếp đất; chớp mắt và thở tự động theo seed), `project.js` (máy quay có `move`/`orbit`/`follow`/`shake`, phép
  chiếu, danh sách hình 2D theo độ sâu, đạo cụ cảnh theo seed), `look2d.js` (`flat-toon`, `ink-silhouette`,
  `rubber-hose`, `blueprint` vẽ dần từng nét), `look3d.js` (three.js: `clay-3d` có bề mặt "sôi" mỗi hình, `lowpoly-90s`
  flat shading, `cardboard` mảnh bìa có độ dày, ghim đồng, đèn bàn đổ bóng), `post.js` (`riso` 2–3 mực chồng, halftone,
  lệch bản; `pixel-16` 320×180, 16 màu, dither Bayer; `ascii` lưới ký tự theo độ sáng và hướng biên, quầng phosphor),
  `toon.js` (`TOON.ready`, `TOON.render`), `looks.json` (sổ đăng ký).
- **Mười style pack `engine: code`** (`status: draft`): `dat-nan-3d`, `hoat-hinh-phang`, `ban-ve-ky-thuat`, `in-riso`,
  `pixel-16bit`, `bong-muc`, `ong-cao-su`, `chu-ascii`, `bia-cat-dan`, `low-poly-90` (+ `sach-pop-up`, xem dưới), và mẫu `styles/_template-code/`.
  Style pack có khóa mới `engine: image | code` (thiếu = `image`); với `code`: khối `render` (look, post, hold, palette,
  opts, camera, env) thay cho `style_block`/`matte`/`layers`/`models`/`prompts/`.
- **`method: code`** trong `EPISODE.md` (gộp `code3d` của #35): `check_episode.py` báo ERROR khi `images`,
  `video_seconds` hay `models.*` > 0, khi shot có `ai_motion`, khi mã lớp không phải `C-<slug>`/`E-<slug>`/`FX[-…]`/`T`,
  khi style không khớp phương pháp; `camera` nhận thêm `orbit`, `dolly`, `crane`, `track`; không cần `prompts.csv`.
  `status.py`: METHOD `code`, FORECAST 0/0, cổng G2 kiểm `character.json`, turntable trong `review/` và chi phí 0.
  `motions.json` thêm 13 id (`engine: toon`).
- **`tools/toon/toon.py`** (miễn phí, Chromium headless qua Playwright, WebGL phần mềm): `still`, `turntable`, `clip`,
  `reel`, `lookbook` (cả 10 style cùng một hành động, `sheet.png` + `lookbook.mp4`; bản nháp 960×540 ~2 phút).
- **`inline.py --toon`**: chèn bộ TOON sau bộ COMPOSE, `READY` chờ `loadToon` (three.js nạp trước khung đầu), cảnh báo
  `toon:` vào `qc` của READY; `--init --toon` đặt mẫu `templates/toon-film-section.js` (CHARS, STYLE, SHOTS) và look
  `toon`. Film đã có bộ TOON giữ nó khi làm mới không có `--toon`. Đã chạy qua `make.py stills` và `draft` của cinecode
  với cả look 2D và 3D.
- **three.js 0.186.1 ghim cục bộ** (`tools/toon/three.lock`, `install_three.sh`, `FILM_THREE`): setup script bước 6,
  hook khởi động cài khi thiếu; `doctor.sh` dòng `three` (thiếu = WARN, sai băm = FAIL) và, ở bản đầy đủ, `webgl`.
  `chrome-root.sh` bật SwiftShader (`FILM_WEBGL=gpu` để tắt). Render không tải CDN.
- **Phong cách thứ 11 `sach-pop-up`** (look `popup-paper`, TOON v1.1.0, 2026-11-24), sau khi nghiên cứu Papertrails
  (xikhar/papertrails, MIT; chỉ học kỹ thuật, không dùng mã hay tranh của họ): cuốn sách pop-up nhìn từ trên cao qua
  ống kính dài; trang in nền và đường kraft mép xé; cây hai tấm bìa cài chéo, thông, dải bụi in hoa, đá gấp; mặt bìa in
  hoạ tiết vẽ bằng code, mép cắt kem; bìa bật dậy theo lò xo bản lề (`opts.rise`, vượt ~15 % rồi rung) và lắc trong gió;
  ánh ấm, bóng mềm, tilt-shift, grade ấm; ban đêm có đèn lồng (`opts.night`). Ghi chép nghiên cứu: `styles/sach-pop-up/STYLE.md`.
- Bộ COMPOSE lên v1.3.0 (1.2.0 là bản có `ink.js`, `figure.js` ở mục dưới; 1.3.0 vì `inline.py --toon`). Tài liệu: `references/code-method.md` (mới), `film-pipeline` §2.1,
  `film-script` §4a, `film-compose-shot`, agent `film-writer`, `film-art-director`, `film-compositor`,
  `film-reviewer`, `film-animator`, `docs/WORKFLOW.md` (ba phương pháp), `docs/CONVENTIONS.md` §3/§5/§6, RUNBOOK, BACKLOG.
- Test: `tests/js/toon.test.cjs` (16 test node: chân không trượt, độ dài xương, nhảy đúng độ cao, chớp mắt theo seed,
  hậu kỳ chỉ ra màu hợp lệ…), `tests/test_toon.py` (render thật cả 10 style, cùng khung hai lần ra cùng byte cả 2D lẫn
  3D), `tests/test_method_code.py` (13 test: `check_episode`, style, `status.py` G2, `inline.py --toon`).

### Âm thanh tổng hợp và hình người vẽ bằng nét mực (#32, #33, 2026-11-24)
- **Âm thanh tổng hợp tại chỗ `tools/audio/` (#33, #32)**: `pluck.py` (guqin, pipa, koto bằng mô hình dây Karplus-Strong mở rộng: trượt dây, rung, bồi âm, tremolo, rải dây), `sfx.py` (15 foley theo bảng của `styles/thuy-mac/sound.md`: `wind`, `fire`, `drone`, `brush_air`, `whoosh`, `hoof`, `ink_drop`, `gong`, `drum`, `drum_roll`, `ember`, `thump`, `footstep`, `cloth_flap`, `water_ring`) và `score.py` dựng `score.json` của tập thành stem `music.wav` / `foley.wav` / `ambience.wav` + `preview.wav` + `score-log.json` + `mix-snippet.json` cho `audio/mix.json` của cinecode. Chạy local, miễn phí, chỉ numpy + scipy, không sample, không API; cùng điểm nhạc + cùng seed cho file giống hệt từng byte; khoảng lặng (`silence`) là số 0 tuyệt đối; kiểm tra trước khi dựng (mã thoát 2, in mọi lỗi, không ghi gì); file đầu ra đã có thì từ chối (`--overwrite`). Nhạc vẫn do người dùng chọn: tool không tự bật. Không có sáo/tiêu và không có sampler; `drone` và `gong` là xấp xỉ tổng hợp.
- `templates/episode/score.json`: mẫu điểm nhạc 24 s; `THIRD_PARTY.md`: mã phỏng theo lemomo-ai/lemo-opuscar (MIT, Copyright (c) 2026 LemoLab).
- `styles/thuy-mac/sound.md`: sửa tham chiếu chết `core/audio/pluck.py` thành `tools/audio/pluck.py`, ghi tên hàm foley cạnh từng dòng.
- **Hình người vẽ bằng code cho cảnh rộng (`figure`, bộ ghép 1.2.0, #32)**: `COMPOSE.figure.draw(st, o)` vẽ một người nhỏ bằng nét mực code (khối áo nhạt + nét mực đậm + búi tóc/nón, mặc định nhìn từ sau), không mua ảnh nào: đứng, đi dọc `path` (bàn chân đã đặt không trượt, độ dài bước suy từ tốc độ), quay người, giơ tay, cúi, ngồi, `timeline`; thân theo bậc 12 fps, áo, tay áo, đai và dải buộc tóc bay theo gió của shot (`st.wind`, cùng cơn gió với `cloth`). `COMPOSE.figure.crowd` cho đám đông lệch pha. Cao tối đa 25 % khung (270 px), lớn hơn bị thu lại + cảnh báo (dùng plate AI + `cloth` / `pose-cycle`). Hướng dẫn: `.claude/skills/film-compose-shot/references/layers-figure.md`, `compose-api.md` §5.4.
- **Nét mực `COMPOSE.ink`** (`tools/compose/ink.js`): `stroke` (lực nhấn, sợi lông bút cạn mực dần, `dry` từ ướt đến phi bạch, năm sắc mực, bút ăn mực một bên) và `mass` (khối nhạt mép mềm), vẽ thẳng vào sân khấu; mỗi nét có `id` nên chỗ đứt nét không bò giữa các khung.
- `inline.py` chèn 16 file (thêm `ink.js`, `figure.js` sau `pose.js`); `motions.json` và `styles/thuy-mac` có id `figure`. Chạy lại `python3 tools/compose/inline.py film.html` để film cũ nhận bộ mã mới.
- `THIRD_PARTY.md`: `ink.js` và `figure.js` phỏng theo mã MIT của lemomo-ai/lemo-opuscar (Copyright (c) 2026 LemoLab).
- `tools/audio` sau lần nghe đầu của chủ dự án: gió viết lại thành luồng trầm có đợt (trước đó nghe như tiếng ồn: 8,6 % năng
  lượng trên 1 kHz, nay dưới 0,5 %); cồng dựng lại thành cồng có núm gõ dùi mềm (hai bản đầu dùng tỉ lệ bồi âm của thanh gỗ
  và có tiếng "tách" ở đầu nên nghe như gõ gỗ): âm cơ bản D3 147 Hz (chủ dự án chọn bằng tai; cao hơn nghe ra chuông) mạnh nhất và ngân nhiều giây (sau 5 giây còn −5 dB),
  bồi âm gần quãng tám, mỗi bồi âm là một cặp phách chậm, không có tiếng tách, có vang phòng mặc định; khóa mới `reverb` và `room_s` cho mọi sự kiện trong `score.json`.
- `THIRD_PARTY.md`: ghi công cho mã phỏng theo lemomo-ai/lemo-opuscar (MIT). Chỉ phỏng mã; phim mẫu, nhân vật, bố cục
  và bản nhạc của dự án đó không được dùng.

## [1.1.0] - 2026-11-11

Dữ liệu dự án phim chuyển lên Google Drive, repo chỉ còn là lõi dùng lại; mỗi tập chọn một trong hai phương pháp dựng
(`layers` hoặc `seedance`); công cụ được gia cố sau một đợt kiểm toán. **Bản này có thay đổi phá vỡ** so với 1.0.0
(đường dẫn `series/` → `projects/`, mã thoát và mặc định của `ark.py`, `budget.yaml` chặt hơn, nơi ghi của `matte.py`):
xem mục "Cần làm khi nâng cấp" trong `docs/releases/v1.1.0.md`. Số phiên bản 1.1.0 do chủ dự án chọn.

### Hai phương pháp dựng: `layers` và `seedance` (#28, 2026-11-11)
Mỗi tập chọn một phương pháp trong `EPISODE.md`. `layers` chỉ dùng model ảnh (tạo theo lô), tách lớp và chuyển động bằng
code, không gọi Seedance. Chưa dựng shot thật nào bằng `layers`; giá batch của Ark chưa xác minh (tài khoản hết số dư).

- **Hai cách dựng cho mỗi tập (#28)**: `EPISODE.md` có khóa `method: layers | seedance`. `layers` = chỉ dùng model ảnh, tách lớp, ghép lớp và làm chuyển động bằng code, không gọi Seedance; `seedance` = cử động nhân vật bằng clip Seedance. Thiếu khóa = `seedance` kèm một WARN (tập cũ giữ nguyên nghĩa); giá trị khác là ERROR. Với `layers`, `tools/check_episode.py` báo ERROR khi shot nào có `ai_motion`, khi `video_seconds` > 0, hoặc khi `models.<id>` > 0 với id chứa `seedance` trong `budget.yaml`.
- Mẫu tập mới (`templates/episode/`): `method: layers` và `video_seconds: 0` (trước là 30); tập dùng Seedance phải ghi `method: seedance` và đặt trần video cùng người dùng. `templates/project/SERIES.md` có dòng ghi nhớ `method:` mặc định của dự án (công cụ chỉ đọc `EPISODE.md`).
- **Hai phương pháp dựng cho mỗi tập (`method: layers | seedance`, issue #28) – tài liệu, skill, agent, style pack**: `EPISODE.md` ghi một trong hai; không có khóa = `seedance` (tập cũ giữ nguyên). `layers` chỉ dùng ảnh của model giá thấp, tạo theo lô (`ark.py image-batch <jobs.csv>`), tách lớp, ghép 2.5D và mọi chuyển động là code (`cloth`, `strip-warp`, `foliage`, `smoke`, `fire`, `embers`, `mist-bands`, `pose-cycle`); khâu 6 (clip AI) bị bỏ qua, `video_seconds: 0`, `ai_motion` trống. Tài liệu mới `.claude/skills/film-compose-shot/references/layers-method.md`: quy tắc dàn cảnh (nhân vật giữ tư thế, không trượt, không xoay, không bộ phận hiện rời; hành động lớn = đổi bậc 2–4 plate tư thế 8–12 fps), bảng "kịch bản muốn gì → làm thế nào", chi phí mỗi shot, danh sách kiểm trước G3. Skill `film-script`, `film-pipeline` (mục 2.1), `film-prompt-layers` (mục 4a: bộ tư thế, `jobs.csv`), `film-compose-shot` (mục 3a) và agent `film-writer`, `film-art-director`, `film-plate-maker`, `film-compositor`, `film-animator` đều rẽ nhánh theo `method`; `film-animator` không dùng cho `layers`. `docs/WORKFLOW.md` có bảng so sánh hai phương pháp; trước G2 đạo diễn đưa người dùng mục `FORECAST` của `tools/status.py`.
- **Thủy mặc: nhân vật 2D tô phẳng trên nền thủy mặc**: mẫu prompt mới `styles/thuy-mac/prompts/character-cel.txt` (mảng màu phẳng, viền mực đậm, bảng màu hẹp + ochre, mặc định nhìn từ sau, nền trắng phẳng như L4) và `prompts/pose-set.txt` (plate tư thế `L4b`, `L4c`… từ ảnh khóa làm `--ref`, cùng khung vẽ và vị trí bàn chân); `motion.md` có giá trị cho `smoke` (màu mực), `fire` (ochre → son, giữ quy tắc một màu son), `cloth`, `foliage`, `pose-cycle` (8 fps); `style.yaml` khai báo năm id này. Giá trị và mẫu prompt chưa thử trên model (tài khoản chưa có tín dụng).
- **Bộ ghép 2.5D v1.1.0 – khói, lửa, cây cử động bằng code (phương pháp `layers`, không gọi Seedance, #28):**
  `tools/compose/smoke.js` (`COMPOSE.smoke.plume`: cột khói bốc lên, cuộn, tan dần; khói mực đậm trên giấy sáng hoặc khói
  sáng trên nền tối), `fire.js` (`COMPOSE.fire.flames`: lưỡi lửa nhấp nháy trên đường chân hoặc tại các điểm, màu thổ
  hoàng → màu nhấn của bảng màu, không bao giờ chớp sáng toàn khung; `COMPOSE.fire.glow`: ánh lửa ấm nhấp nháy, cường độ
  bị chặn ở 0.6), `foliage.js` (rig `sway`: tán cây / bụi / cỏ đung đưa tại chỗ từ đường gốc, ngọn lệch mặc định ≤ 1.5 %
  chiều cao, các cây cạnh nhau tự khác nhịp; dùng lại bộ máy strip-warp). Tất cả là hàm thuần của `(t, SEED)`; tham số
  sai / thiếu hộp neo → cảnh báo `compose: ...`, không làm hỏng READY.
- `motions.json` thêm id `smoke`, `fire`, `foliage`, và đăng ký trước `cloth`, `pose-cycle`. `inline.py`: `ORDER` thêm
  ba file mới và hai file tuỳ chọn `cloth.js`, `pose.js` (chưa có thì bỏ qua; file khác thiếu → `FAILED`); `--lint` in
  số file thực sự được chèn (`12 files, lint ok (optional, not there yet: cloth.js, pose.js)`).
- Tài liệu: `compose-api.md` §5.1–5.3 (tham số, mặc định, khoảng nên dùng, ví dụ). Test: `tests/js/atmosphere.test.cjs`
  (16 test node) + 3 test Python cho `inline.py`.
- **`ark.py image-batch JOBS.csv`** (issue #28, phương pháp `layers`): tạo cả lô lớp tranh bằng một lệnh. Mỗi dòng CSV (`id,prompt,out,size,model,ref,seed,negative`; `prompt` dạng `@file`) là một request `image` với đúng các dòng ledger `pending` + dòng cuối, không thử lại. Kiểm mọi dòng trước khi gửi (mã 2, liệt kê hết lỗi theo `id`); dòng đã có file đầu ra thì bỏ qua nên chạy lại sau khi bị ngắt không trả tiền hai lần; cả lô vượt trần → một dòng `refused-budget`, mã 3, không gửi gì; chạy tối đa `--parallel` request cùng lúc (mặc định 3, tối đa 4), từng request vẫn qua bước kiểm nguyên tử. Bị từ chối ngân sách giữa chừng, HTTP 401/403, lỗi số dư hoặc SIGINT/SIGTERM thì không bắt đầu dòng mới, dòng đang chạy vẫn ghi dòng cuối. `--dry-run` in kế hoạch và ngân sách sau lô, không ghi gì; `--only ID …` chỉ chạy vài dòng; `--fast` dùng flash cho dòng không ghi model.
- Chưa làm (chưa xác minh, cần request trả tiền để thử): Batch API bất đồng bộ của Ark và chế độ tạo chuỗi ảnh của Seedream – `image-batch` vẫn tính giá từng ảnh như `image` (`docs/MODELS.md`).
- **Bộ ghép – nhân vật cử động cho phương pháp `layers`** (#28): thêm `tools/compose/cloth.js` (rig `cloth`: áo choàng, tay áo, dải lụa, tóc bay tại chỗ; sóng chạy từ mép dính thân ra mép tự do, gió và cơn giật chung cho mọi hộp vải của shot qua `st.wind`, mép dính lệch đúng 0, biên độ trần 10 % chiều dài, điểm ảnh ngoài hộp không đổi) và `tools/compose/pose.js` (rig `poses`, id `pose-cycle`: đổi bậc giữa 2–4 tranh tư thế theo lưới 8–12 fps, căn theo điểm neo `feet` và tỉ lệ chung, hoà tan tối đa 2 khung, hàm dựng timeline `COMPOSE.pose.walk / once / sequence`; thiếu tranh hoặc điểm neo → cảnh báo và hiện khung 0; không có tween vị trí/góc xoay của cả thân).
- Tài liệu mới `.claude/skills/film-compose-shot/references/layers-character.md`: chọn `cloth` / `strip-warp` / `pose-cycle`, số tranh tư thế cho từng hành động, cách tạo tranh tư thế khớp nhau, số đo fps và thời gian giữ, những điều không bao giờ làm (trượt, xoay thân, bộ phận rời).
- Test: `tests/js/character.test.cjs` (18 test node) và `tests/test_compose_character.py` (chạy bộ test node, lint, kiểm điểm ảnh thật bằng Chrome headless).
- `tools/status.py` in thêm dòng `METHOD` (phương pháp dựng của tập, đọc `method:` trong EPISODE.md: `layers` | `seedance`; thiếu khóa = `seedance`, giá trị khác in `invalid` kèm ghi chú) và mục `FORECAST`: dự báo phần còn phải trả trước khi tạo gì, tính từ `shots.csv` + `prompts.csv`, không gọi mạng. Gồm số ảnh còn phải tạo (lớp chưa có ảnh hoặc bị từ chối, trên tổng số lớp, kèm số đã duyệt/đã tạo/mất file) và số giây Seedance dự kiến (shot có `ai_motion` chưa có clip, làm tròn lên từng shot, tối thiểu 4 s mỗi clip), mỗi số so với phần còn lại của `budget.yaml`: `fits` hoặc `OVER by N`. Tập `method: layers` dự kiến 0 giây video và in `CONFLICT: method layers but sNN has ai_motion` cho từng shot còn `ai_motion`. Cả hai có trong `--json` (`method`, `forecast`). (#28)
- `tools/status.py --gate G2` thêm điều kiện `forecast fits the budget`: `[MISSING]` khi phần còn phải tạo vượt phần còn lại của trần. Số `from_s`/`to_s` hỏng trong `shots.csv` chỉ thành ghi chú, shot đó bị bỏ khỏi dự báo, không làm công cụ dừng.

### Gia cố công cụ sau đợt kiểm toán (2026-11-10)
Mười gói việc, mỗi gói có test viết trước và một lượt review độc lập; 664 test (trước đợt: 236). Việc còn nợ:
`docs/BACKLOG.md`.

- `tools/ark.py`: từ chối tại chỗ (mã thoát **2**, không gửi gì, không ghi ledger, không tạo thư mục đầu ra) trước khi tốn tiền: `budget.yaml` chỉ nhận bốn khoá `images` / `video_seconds` / `models` / `ledger_required`, trần phải là số ≥ 0 và request phải nằm dưới một trần (khoá gõ sai như `image:`, file rỗng hay thiếu không còn chạy không trần); file đầu ra đã tồn tại bị từ chối kèm gợi ý `_v<NN>` còn trống (`--overwrite` chỉ cho thử nhanh); `image` từ chối mọi kích thước lớn hơn 2K (`4k`, `8K`, `3840x2160`…) và mọi model `-pro-`; thiếu file `--ref` / `--image` báo `no such file`; ledger sai header bị từ chối thay vì tính lại trần từ 0.
- `ark.py video`: mặc định `--resolution 720p` (trước là 1080p), chỉ nhận `480p|720p|1080p`, `--duration` ≥ 1. Lỗi mạng hoặc HTTP 429/5xx khi poll được thử lại tối đa 5 lần (`poll error (n/5)`), không bao giờ gửi lại POST; tải clip qua `<out>.part` với 3 lần thử nên không còn file dở; task `succeeded` thiếu `video_url` vẫn có dòng `failed` cuối.
- **Thay đổi hành vi**: các lần từ chối tại chỗ (4K, model pro) nay thoát mã 2 thay vì 1; mã 1 chỉ còn nghĩa "request đã rời máy, xem dòng ledger".
- `ark.py lambda-job`: `prepare` cũng kiểm file đầu ra, budget và header ledger, nhắc khi `--size` là tên (`1K/2K/4K`) vì không cố định tỉ lệ khung; `finish` che mọi thứ sau `Bearer ` trong lỗi của worker trước khi in hoặc ghi ledger.

- **`drive_sync.py` không còn báo nhầm "đã đẩy"**: `snapshot` từ chối (mã thoát 1, không ghi gì) khi đã có dấu mà còn thay đổi chưa đẩy; kéo thêm file dùng lệnh mới `drive_sync.py pulled <project> <file…>` (chỉ thay dòng của các file đó, không đụng `.pulled.at`); `--force` để chụp lại toàn bộ.
- **File trạng thái có khoá và ghi nguyên tử** (`.drive_sync.lock`, ghi tạm + `os.replace`): chạy song song nhiều lệnh `record` không còn làm mất dòng của `.pulled.sha256`.
- **`record --sha256 <hex>`** (plan in sẵn): file bị sửa sau lúc tải lên vẫn là CHANGED và có cảnh báo `still to push`; `record`/`pulled` từ chối (mã thoát 2) đường dẫn ngoài `projects/<project>/` và `out/<project>/`; đường dẫn có `\` được chuẩn hoá.
- **Ledger trong danh sách đẩy**: `ledger.csv` có khối `pre` (tải mọi bản trên Drive → `ark.py ledger-merge` → chạy lại `plan`) in trước `create_file`, ghi chú "không chờ duyệt" thay cho ghi chú media; `ledger.drive-*.csv` không bao giờ vào danh sách.
- **Danh sách đẩy gọn và đúng hơn**: mọi dòng `search_files` có `excludeContentSnippets=true`; tên file có dấu `'` hoặc `\` được escape trong truy vấn; file tạm (`*.b64`, `*.orig`, `*.bak`, `*.tmp`, `*.part`, `*~`) chỉ liệt kê một lần, không đẩy; đoạn "Before uploading a CHANGED file" chỉ in khi có file CHANGED; khi không còn chữ để đẩy nhưng còn plate/clip chưa nằm trong gói nào, in `Nothing to push (text). N plate/clip file(s) are in no bundle…` thay cho `Nothing to push.`.
- **`bundle.py` tạo zip tái lập được**: mọi thành phần ghi với ngày 1980-01-01 và quyền 0644, nên chạy lại gói không đổi nội dung giữ nguyên sha256 – không còn bị lập để tải lên và lưu trữ lại.
- Tài liệu: `docs/CONVENTIONS.md` §11.6 và skill `film-pipeline` mục 0 – chụp dấu một lần, `pulled`, `--sha256`, kéo theo khâu (kéo trọn một tập ≈ 250 KB ngữ cảnh), kiểm `wc -c` = `fileSize`.

- **`matte.py` chạy đúng model rembg đã ghi trong tài liệu (`u2net`)**: trước đây `--method rembg` vô tình dùng `bria-rmbg` (tải 1 GB, ~9 GB RAM, 34 s mỗi ảnh 2K). Model nay tường minh: `--rembg-model`, biến `FILM_REMBG_MODEL`, mặc định `u2net`; model chưa có trong máy thì từ chối (mã thoát 2) thay vì tự tải, trừ khi thêm `--allow-download`. **Thay đổi hành vi:** bản tách L4/P sẽ khác bản làm trước đây.
- **`matte.py`, `upscale.py` không bao giờ ghi đè ảnh gốc**: OUT trùng IN luôn bị từ chối; OUT đã tồn tại bị từ chối nếu không có `--overwrite`; `--preview` không được trùng IN/OUT. **Thay đổi hành vi:** lệnh chạy lại với OUT cũ nay thoát mã 2.
- **`matte.py` bỏ được OUT**: mặc định ghi `plates/matte/<cùng tên>.png` (`<thư mục IN>/matte/<tên IN>.png`); đây là quy tắc chung cho ảnh đã tách (CONVENTIONS §3, skill `film-prompt-layers`).
- `matte.py` dùng `matte.per_layer.<mã>.bg` làm màu key (chroma) / màu giấy (luminance); dòng `saved` ghi rõ màu hoặc model đã dùng; giữ alpha sẵn có của ảnh đầu vào (RGBA, LA, palette) thay vì biến vùng trong suốt thành đen đặc; áp dụng hướng xoay EXIF; lỗi style.yaml / ảnh không đọc được báo `matte: ...` thay vì traceback.
- `anchors.py`: từ chối `nan`/`inf` (file luôn là JSON hợp lệ), báo đúng lỗi khi `anchors.json` hỏng, kiểm tên điểm (chữ ASCII, số, `_`, `-`; không dùng `size`, `_size`, `points`, `boxes`, `version`), file khóa đổi thành `.anchors.json.lock` (file ẩn, `drive_sync` không còn đề nghị tải lên Drive).

- `tools/tts/vieneu_tts.py`: bản đọc lời bình hoặc khớp kịch bản từng dòng, hoặc thoát mã khác 0 và nói rõ dòng nào, vì sao.
  - Lỗi kịch bản là lỗi đầu vào (mã thoát mới **2**, chưa render gì): dòng lời bình thiếu mốc, mốc sai dạng (`[0:05]`), giây > 59, mốc không có lời, mốc không sau mốc trước, `length_s` không lớn hơn mốc cuối → `script.md:<n>: <lý do>`; trước đây dòng bị bỏ qua lặng lẽ và id `VO<n>` bị lệch.
  - `--lines`: kiểm dạng file, id an toàn và không trùng (id `../../x` từng ghi ra ngoài `--out`), `start_s`/`slot_s` là số; file không đọc được → một dòng lỗi, mã 2, không còn traceback.
  - `tts-log.json`: đọc trước khi nạp model (file hỏng đổi tên thành `tts-log.json.bad-<giờ UTC>`), ghi sau mỗi dòng, theo thứ tự kịch bản; thêm `text_sha`, `status` (`ok`/`EMPTY`/`OVER`/`CLIPPED`/`NOSLOT`), `flags`, RMS, đỉnh, số mẫu clip, khoảng lặng đầu/cuối.
  - Bản đọc cũ: báo `STALE <id>` (chữ đã đổi) và `ORPHAN <id>` (id không còn trong kịch bản); render cả tập chuyển wav mồ côi vào `<out>/_stale/`; `--only` từ chối khi dòng khác đang `STALE` (trừ `--allow-stale`).
  - Chế độ mới `--check` (không nạp model): mã 0 chỉ khi mọi dòng có bản đọc khớp chữ, giọng, mode, seed – tiêu chí xong của khâu lồng tiếng.
  - `--strict` kiểm thật: bản đọc rỗng (`EMPTY`) luôn thoát mã 1; `--strict` thêm `CLIPPED`, `NOSLOT` (với `--script`) và token chưa đọc được (`WARN <id>: unread token`, vd. `ba.5`, chữ Hán); `--dry-run` ước lượng độ dài theo số âm tiết (`--rate`, mặc định 4/giây) và `--dry-run --strict` thoát mã 1 khi ước lượng vượt khung quá 15 %.
  - `--speed` chỉ nhận 0,9–1,1; kiểm ffmpeg trước khi nạp model.
- Agent mới `film-narrator` (`.claude/agents/film-narrator.md`): lồng tiếng chỉ bằng `vieneu_tts.py`, giọng/mode/seed theo hợp đồng giao việc, xong khi `--check` đạt; chưa gắn vào khâu nào của quy trình (chờ quyết định). `film-compose-shot` §5: lời bình chỉ lấy từ `<media>/vo/`, không bao giờ dùng `tools/tts.py`/`keys.py` của cinecode (đường đó tìm khóa Gemini).

- **Bộ mã COMPOSE v1.0.1** (`tools/compose/`): lớp `seq` (clip Seedance đã tách nền) không có `place` không còn bị tự zoom kiểu cover nên trùng khít lớp tranh nó thay thế khi máy quay lia, đẩy lệch tâm hoặc rung; `end: 'hide'` không vẽ gì trước `at`; khung `seq` khác kích thước khung đầu làm `load` báo lỗi. Phim đã chèn bộ mã 1.0.0 giữ hành vi cũ cho tới khi chạy lại `python3 tools/compose/inline.py film.html`.
- Cảnh báo của bộ mã đi vào `qc` của READY nên `make.py` in ra dưới dạng dòng `compose: ...` (trước đây chỉ có ở console trình duyệt, chạy headless không thấy); cảnh báo lộ mép gộp một dòng cho mỗi lớp, giữ mức zoom lớn nhất và thời điểm đầu tiên. `inline.py` in `WARNING` khi không tìm thấy `qc: qc.warnings` trong template cinecode.
- `inline.py`: ghi nguồn `anchors.json` vào dấu `compose-kit begin` và đọc lại file đó khi làm mới không có `--anchors` (`anchors: refreshed from ...` / `anchors: kept from the earlier embed`); kiểm mọi tham số (`--size` dạng WxH, `--anchors` là JSON object) và tính xong mọi thay đổi rồi mới ghi, `STATE.md` ghi sau `film.html`, lỗi là `FAILED: ...` với mã thoát 1; không còn ăn mất ký tự sau dấu kết thúc; `</` trong anchors được thoát.
- Bộ mã JS có bài kiểm riêng không cần trình duyệt (`tests/js/`, chạy bằng `node --test` qua `tests/test_compose_js.py`; bỏ qua khi không có node).
- Tài liệu dựng shot: lớp đã tách nền tham chiếu `../../plates/matte/<file>`; ví dụ clip-làm-lớp có `cover: false` và dùng `tools/layers/matte_seq.py`.

- **Lambda worker an toàn hơn (cần triển khai lại trước job trả phí kế tiếp):** khóa Ark được đọc lại từ Secrets Manager mỗi job và kiểm dạng trước khi dùng; khóa dán sai (xuống dòng, giá trị giả) dừng trước khi gửi với thông báo cố định, và khóa bị xoá khỏi mọi lỗi ghi vào `jobs/<job_id>.json`, CloudWatch và ledger. Worker từ chối event không có `job_id` do `lambda-job prepare` cấp, giữ chỗ job bằng ghi có điều kiện (không tạo ảnh thứ hai khi S3 lỗi đọc hay event giao lại), ghi `sent`, `deadline`, `worker_sha256` vào status; thiếu ảnh tham chiếu báo `ref not in bucket: …`.
- **`lambda/build_deploy.py`:** `--help` và import không còn build; thêm `--zip-out`, `--check`. Chương trình triển khai báo `zip-stale` (bucket giữ zip cũ, không cập nhật function) và `code-mismatch` (function chạy mã khác repo) thay vì `Active`; timeout 900 s, event bất đồng bộ quá 300 s bị bỏ, role có `s3:ListBucket`. Thêm `tests/test_deploy.py` (chạy chương trình với `call_boto3` giả).
- `lambda/README.md`: các bước triển khai lại, trường status mới, ngừng đọc lại sau `deadline` + 60 s, `curl -fsS`, kích thước có tên không cố định tỉ lệ (truyền `<rộng>x<cao>`). Skill và bộ nhớ agent bỏ câu "Lambda chưa triển khai → dùng 2K".

- `tools/check_episode.py` chặt hơn trước cổng duyệt (mã thoát 0 không còn có nghĩa "sẵn sàng" khi ngân sách vô hiệu, khâu vượt cổng, media mất hay lời bình bị bỏ sót):
  - **`budget.yaml` được kiểm**: thiếu file là ERROR từ khâu 0; chỉ nhận bốn khóa `images`, `video_seconds`, `models`, `ledger_required` (khóa lạ là ERROR: gõ sai tên trần = không có trần); `images` và `video_seconds` bắt buộc, là số ≥ 0; từ khâu 4 chưa bật `ledger_required: true` là WARN.
  - **`stage` so với `gates`**: khâu đã vượt cổng (G1 = 2, G2 = 4, G3 = 8, G4 = 10) mà cổng còn `null` là ERROR; cổng sau có ngày khi cổng trước còn `null`, hoặc ngày lùi lại, là ERROR; ngày ở tương lai là WARN. `shots.csv` chỉ có header ở khâu < 3 chỉ còn là WARN.
  - **`--probe` chỉ xét bản dựng mới nhất** của mỗi loại (`draft`, `final`); bản cũ in một dòng INFO `superseded by v<NN>`. Bản cuối sai kích thước/fps so với `format` trong `SERIES.md` (mặc định 1920×1080, 24 fps) hoặc lệch `length_s` quá 1 s là ERROR (trước là WARN hoặc bỏ qua); bản nháp không phải nửa khung (960×540) hoặc không có tiếng là WARN.
  - **Media thiếu**: từ khâu 7, mất cả thư mục media khi `prompts.csv` còn file bắt buộc là ERROR (trước chỉ WARN); file `approved=no` không còn bị đòi phải có trên đĩa (một dòng INFO).
  - **Lời bình**: dòng có chú thích `<!-- -->` đứng cùng dòng không còn bị bỏ khỏi kiểm tra và TTS (chú thích bị cắt, phần chữ được giữ); `--` trong lời bình là ERROR (trong `>` là WARN); chữ Hán, `|`, `` ` ``, `](`, `<`, `>` trong lời đọc là WARN `not speakable`.
  - **Không còn traceback thiếu báo cáo**: file không phải UTF-8, ledger UTF-16, ngày không tồn tại (`2026-11-31`), giá trị YAML sai kiểu trong style pack, `nan`/`inf` trong `shots.csv` đều thành dòng ERROR; lỗi bất ngờ in `ERROR internal: …` và file `--out` vẫn được ghi. Ledger có BOM không còn báo sai header.
- Tài liệu: `docs/WORKFLOW.md` ghi lệnh trước cổng kèm `--out review/check-v<N>.txt`; `docs/CONVENTIONS.md` §4 ghi quy tắc `budget.yaml` và `script.md` đúng như mã; skill `film-script` §1 nói rõ phần tra nguồn là của phiên chính / `film-researcher`.

- **doctor.sh đếm đủ lỗi**: phép thử model video (một POST với độ phân giải sai `9999p`, Ark từ chối trước khi tạo task) giờ đi qua bộ đếm – `ModelNotOpen`, task bị nhận nhầm (in kèm id để huỷ trong Ark Console) và mất mạng đều là FAIL, mã thoát khác 0; không còn cảnh `FAIL video-model` rồi `Result: all checks passed`.
- **ark-ping chặt hơn**: FAIL khi danh sách model rỗng, khi model mặc định (video, flash, pro cho Lambda) ở trạng thái `Shutdown`, khi quá 20 s; mất mạng in đúng một dòng `Ark host unreachable: …` thay cho traceback.
- **doctor.sh thêm kiểm tra**: node ≥ 22, ffprobe, biến phiên `FILM_LAB` / `CINECODE_FORMATS` / `CHROME_PATH` (WARN kèm dòng `export` để dán); chế độ đầy đủ import thật `rembg` + `onnxruntime`; `-h/--help` in cách dùng, tham số lạ thoát mã 2.
- **Worktree không còn kéo lệch `/opt/byteplus/ark.py`**: hook chạy trong git worktree giữ nguyên liên kết của bản chính; doctor trong worktree chấp nhận liên kết đó và chỉ sang hook của bản chính khi cần sửa.
- **Hook luôn in báo cáo doctor**: pip lỗi hoặc quá giờ không còn làm hook thoát mã 1 trong im lặng – in `film-lab: pip install failed (rc N)`, không ghi dấu, lần khởi động sau tự thử lại; apt, pip và tải u2net có giới hạn thời gian (120/300/600/240 s).
- **Test mới**: `tests/test_env_scripts.py` (chạy thật hai script với thư mục tạm, shim và máy chủ Ark giả) và `tests/test_repo_hygiene.py` (không dữ liệu dự án, media hay file > 500 KB trong repo; script giữ quyền chạy; pin pip khớp `docs/setup-script.sh`).

- **`tools/status.py` (mới, chỉ đọc)**: một màn hình cho mỗi tập: khâu và cổng (`BLOCKED` khi khâu đã vượt cổng chưa duyệt), `## Việc tiếp theo`, ngân sách đã tiêu/trần đếm đúng như `ark.py` (mỗi request một lần), request trả phí còn dở (`OPEN`, kèm đúng lệnh `--resume-task` hoặc `lambda-job finish`), `CUT-502`/`FAILED`, file đã trả tiền không còn trên đĩa (`MISSING`), trạng thái từng lớp của từng shot (no-prompt, todo, made, rejected, approved, lost), plate mồ côi, media chưa nằm trong gói nào, và danh sách điều kiện của cổng kế tiếp (`--gate G1..G4`). Dạng `--ledger L [--budget B]` chỉ in phần ngân sách (lab, agent báo chi phí). `--json` cho agent. Mã thoát 0 = không gì chặn, 1 = có việc phải xử lý, 2 = sai cách dùng. Không ghi file, không gọi mạng.
- Skill `film-pipeline`: đầu phiên chạy `python3 tools/status.py <thư mục tập>` thay cho việc đọc tay `budget.yaml`, `ledger.csv` và `out/`; trước khi trình cổng chạy thêm `--gate <G>`.

- **Clip Seedance thành lớp, một lệnh thay cho vòng lặp tự chế**: `tools/layers/matte_seq.py <clip>.mp4 [--start-frame <khung đầu>] [--strict] [--strip <ảnh>] [--json <file>]` tách khung bằng ffmpeg, tách nền cả clip trong một tiến trình (chroma tự dò màu key, `--low 40 --high 200`, khử loang màu; `--method rembg` dùng một phiên model và từ chối khi model chưa có trên đĩa), in số đo `bg_flat`, `bg_dirty`, `flicker`, `area_jitter`, độ phủ, khung chạm mép, khung rỗng, IoU với khung đầu, các dòng WARN (HAZE, FLICKER, CROPPED, EMPTY, BACKGROUND NOT FLAT, REFRAMED, NOT 16:9) và dòng `L4b: { seq: ... }` để dán vào `PLATES`. Lệnh cũ trong tài liệu (`matte.py chroma ...`) không chạy được và đã được thay. Ngưỡng WARN mới đo trên khung giả lập, cần kiểm lại trên clip thật đầu tiên.
- **Kiểm tra khung đầu miễn phí trước khi trả tiền**: `tools/compose/keyframe.py --check <khung đầu> --key "#RRGGBB"` thoát 1 nếu ảnh không phải 1920x1080, có kênh alpha, hoặc viền 16 px không phải màu key; in khung bao của nhân vật. Khi tạo khung đầu, `keyframe.py` cảnh báo (stderr, mã thoát không đổi) nếu nhân vật bị mép khung cắt hoặc màu key gần màu nhân vật (`WARN KEY NEAR SUBJECT`).
- **Hợp đồng film-animator khớp với công cụ**: khung đầu lấy từ `clips/..._start_v<NN>.png` (không bao giờ từ `plates/`), chạy `keyframe.py --check` trước mỗi lệnh tính phí, lệnh bắt buộc có `--ratio 16:9 --no-audio`, prompt có ba vế cố định, dòng `failed` có `task_id` lấy lại bằng `ark.py video --resume-task`, sau khi tải về chạy `matte_seq.py --start-frame --strict`. `references/seedance-layer.md` ghi rõ ai làm từng bước, một quy tắc màu key, và sửa phương án phủ toàn khung (`depth 1.0, cover: true`).
- `tools/ark.py ledger-merge`: các dòng đang có trong `--out` luôn được giữ (lệnh kéo trong tài liệu từng làm mất dòng
  chỉ có ở bản trong container); ledger không có xuống dòng cuối file không còn làm dính dòng mới vào dòng cũ; ledger có
  BOM vẫn được đếm.
- Worker Lambda đã gia cố được **triển khai lại 2026-11-11** (timeout 900 s, `CodeSha256` khớp repo); chưa có job nào chạy
  trên bản này.
- **Lambda đã tạo ảnh thật đầu tiên** (#13 bước 3, phần 2K): Seedream Pro `2K` qua `lambda-job`, 77,3 s trong worker,
  ~90 s từ lúc Invoke đến lúc có file; ảnh trả về 1664×2496 (dọc) vì kích thước dạng tên không cố định tỉ lệ khung.

### Thêm
- `tools/ark.py lambda-job prepare|finish` (#13 bước 1): ảnh pro/4K tạo qua Lambda nay vào cùng ledger và cùng trần.
  `prepare` làm bước kiểm trần + giữ chỗ nguyên tử như `image` (dòng `pending`, `note` = `req=<id>; lambda`; vượt trần →
  `refused-budget`, mã 3, không in payload), nén `--ref` sẵn để tải lên `refs/<id>-<n>.jpg` và in payload Invoke có
  `job_id` = `<id>`; `finish` đọc `jobs/<id>.json` của worker, lưu ảnh đã tải về đúng tên và ghi dòng cuối `ok`/`failed`
  (chạy lại không thêm dòng). Không có ledger thì không có payload. Trần `models.dola-seedream-5-0-pro-260628` trong
  `budget.yaml` từ nay có hiệu lực. `lambda/README.md` viết lại theo luồng này. Test: `tests/test_lambda.py`.
- `tools/ark.py ledger-merge A.csv B.csv … -o OUT.csv` (#15 phần 2): hợp các bản ledger của một tập, khử trùng theo
  `(req, status, task_id)`, ghi dưới `LOCK_EX`; không đầu vào → ledger rỗng có header. CONVENTIONS §7, §11.6 và
  `film-pipeline`: hai bản `ledger.csv` (hai phiên, hai file trên Drive) thì **gộp**, không lấy bản mới nhất; trước khi
  đẩy ledger thì gộp với bản đang ở Drive.
- `budget.yaml` `ledger_required: true` (#15 phần 2, tuỳ chọn, bật từ khâu 4): `ark.py` thoát mã 2 khi file ledger chưa
  có hoặc rỗng, để ledger chưa kéo từ Drive không làm trần tính lại từ 0.
- `film-pipeline`: mỗi tập chỉ một phiên tạo ảnh/video tại một thời điểm, ghi vào `## Nhật ký` của EPISODE.md khi bắt đầu
  và khi xong khâu 4–6 (#15 phần 2).
- `tests/test_compose.py` (#16): 22 test cho `tools/compose/inline.py` (`--init` trên bản chép template cinecode đã ghim:
  khối kit, 1920x1080, `READY` có `loadPlates`, look `plates`, dòng Format của STATE; chạy lại cho kết quả y hệt; từ chối
  `Math.random`/`Date`/`performance.now`; template đổi mốc → báo lỗi, không ghi file) và `keyframe.py` (khung 1920x1080,
  nền màu key, vị trí/chiều cao với pivot `center`, `bottom`, `top` và điểm neo). Fixture `tests/fixtures/cinecode/` (MIT).
- `docs/RELEASING.md` (#14): bước phát hành – Claude sửa CHANGELOG, chạy test + doctor, mở PR và soạn nội dung release;
  tag và GitHub Release do người dùng tạo tay (phiên cloud bị 403 khi push tag). Thêm dòng trong `CLAUDE.md`, `README.md`.
- `matte.py --paper auto` (mặc định khi không truyền `--paper #RRGGBB`, kể cả khi dùng `--style`): ước lượng màu
  giấy từ dải viền ảnh (trung vị từng kênh), in `paper #…`; nền ngà/gradient của Seedream (`#F5F1EE`, `#EAE5DF`) không
  còn cho lớp ~0% trong suốt. Cảnh báo khi L2/L3 < 10% trong suốt. Test với nền ngà và gradient tổng hợp.
- `matte.py` rembg giữ khóa toàn máy `/tmp/film-lab-rembg.lock` (fcntl): nhiều plate-maker song song xếp hàng thay vì
  bị OOM-kill (u2net ~1 GB RAM mỗi tiến trình).
- `docs/MODELS.md`: Seedance 2.5 `duration` 4–30 s (API kiểm, 2026-11-10); lite 2K + `--ref` bị proxy cắt 502 ở 31 s,
  flash 2K/2560x1440 + `--ref` ~75 ảnh không lần 502 → lớp tranh sản xuất dùng `--fast`.
- `film-plate-maker`, `film-pipeline`: mỗi agent song song dùng thư mục scratch riêng đặt theo `FILM_AGENT`.
- Đánh số tập theo quyển: mã tập `q<NN>t<NN>` (thư mục `q01-t01-<slug>`, media `out/<project>/q01t01/`, file
  `q01t01_s03_...`, `book:` trong `EPISODE.md`, hiển thị "Quyển 1 · Tập 1") song song với `ep<NN>`
  (`tools/episode_id.py`; CONVENTIONS §2/§5/§11, `check_episode.py`, `bundle.py`, `drive_sync.py`, `layers/`, mẫu, skill);
  `tools/rename_episode.py` đổi mã một tập đang làm (vd. `ep01` → `q01t01`, chạy thử mặc định, `--apply`).
- `tools/tts/vieneu_tts.py` (issue #8): lồng tiếng Việt local trên CPU bằng VieNeu-TTS v3 Turbo (`vieneu` 3.8.3,
  Apache-2.0, giọng mẫu dùng thương mại được): đọc `script.md` (quy tắc của `check_episode.py`) hoặc `vo-lines.json`,
  ghi `<id>.wav` 48 kHz + `tts-log.json` (model, phiên bản, giấy phép, watermark), so độ dài với khung `[mm:ss]`,
  chuẩn hóa số/năm/đơn vị, bảng phát âm `term,doc`, chế độ `--audition`. Cài riêng (không vào hook), xem
  `tools/tts/README.md`. Test không cần model: `tests/test_tts.py`.

- `docs/RUNBOOK.md`: bài học từ tập đầu tiên làm trọn (Sơn Hải Kinh Q1·T1): `AccountOverdueError`, `CHROME_PATH` bị ghi
  đè, người xem độc lập trước `make.py final`, `renders/` chỉ chứa bản dựng, clip Seedance lệch giải phẫu, agent dừng
  vì giới hạn 5 giờ.

### Thay đổi
- **cinecode được ghim** (#16) ở commit `67f9807` (`tools/compose/cinecode.ref` = `CINECODE_REF` trong
  `docs/setup-script.sh`; test so hai giá trị). Setup script `fetch` đúng commit rồi `checkout`, không còn
  `git pull --ff-only` mỗi lần. **Cần dán lại `docs/setup-script.sh` vào môi trường Film Lab.**
- `tools/doctor.sh`: `skill-cinecode` báo WARN khi HEAD khác ghim; mục mới `compose-kit` (cả `--quick`) chạy
  `inline.py --lint` và `--init` trên bản chép tạm của template cinecode đang cài → cinecode đổi template thì FAIL ngay
  đầu phiên thay vì lúc dựng shot.
- `lambda/ark_image_worker.py`: `job_id` đã có `jobs/<job_id>.json` thì không chạy lại (Lambda có thể giao sự kiện bất
  đồng bộ nhiều lần; chạy lại là tính phí ảnh thứ hai). 
- `lambda/build_deploy.py`: zip của worker không còn nhúng trong chương trình `run_script` (sandbox chặn `import base64`
  và không truyền được `bytes`); ghi `out/ark_image_worker.zip` (zip tất định), tải lên bucket bằng link ký sẵn, function
  lấy mã từ S3 và chương trình so `CodeSha256` với repo. **Lambda đã triển khai 2026-11-10** (#13 bước 2); chưa thử ảnh thật.
- `ark.py image`: thông báo chặn model pro / 4K chỉ sang `lambda-job` thay vì gợi ý `--force`.
- `docs/RUNBOOK.md`: 11 sự cố mới từ đợt kiểm thử khởi động máy sạch 2026-11-10 (kéo Drive bằng base64 tốn ngữ cảnh,
  CSV của Sheet dùng CRLF, connector AWS `needs_reconnect`, thiếu/hai bản ledger, lỗi `lambda-job`, cinecode đổi
  template, push tag 403).
- `ark.py video --image` không còn gửi `ratio` (trước: `ratio=adaptive`): Seedance 2.5 image-to-video từ chối `ratio`
  (HTTP 400). `--ratio` cùng `--image` chỉ gửi khi người dùng truyền, kèm cảnh báo. Tài liệu bỏ lời khuyên
  `--ratio 16:9`: tự làm khung đầu 16:9 (vd. 1280x720).
- **Repo = lõi** (công cụ, skill, agent, style pack, mẫu, quy trình, cài đặt). Dữ liệu từng dự án (kinh thư, nhân vật,
  bối cảnh, nghiên cứu, kịch bản, shot list, `EPISODE.md`, ngân sách, prompt, tiến độ, tài liệu gốc, media) nằm trên
  Drive `ClaudeFilmLab/<ProjectName>/` (gốc lab `19yQarw7ATu90uzXjboGP4sy5FzlQhd0y`) với cây chuẩn
  `00_QuanLy · 01_TaiLieuGoc · 02_KinhThu · 03_KichBan · 04_SanXuat · 05_ThanhPham · 99_LuuTru`.
- Bản làm việc trong phiên: `projects/<project>/` (git bỏ qua, `.gitignore`), cùng bố cục cũ của `series/<series>/`;
  media vẫn ở `out/<project>/`. Mọi tham chiếu `series/<series>/…` trong docs, skill, agent, mẫu và công cụ đổi thành
  `projects/<project>/…`.
- `docs/CONVENTIONS.md` §11 mới "Dự án trên Drive": cấu trúc, schema `PROJECT.md` (manifest ID thư mục), bảng ánh xạ
  Drive ↔ bản làm việc, đặt tên tài liệu gốc `<masach>_<noidung>_<NN>_<chitiet>.<ext>`, kéo/đẩy bằng connector Google
  Drive, quy tắc phiên bản (đẩy = file mới, bản cũ chuyển vào `99_LuuTru/` với tên có giờ, vì connector không ghi đè
  nội dung), không xoá trên Drive. §9 lưu trữ và bảng quyết định §10 cập nhật theo.
- `film-pipeline`: mục 0 "Mở dự án / Kéo về / Đẩy lên Drive"; đầu phiên kéo `PROJECT.md`, kinh thư, tập và
  `ledger.csv`; sau mỗi khâu đẩy chữ và cập nhật `TienDo_SanXuat` thay cho commit/push. `film-script`,
  `film-researcher`: `research.md` và tài liệu gốc thuộc dự án trên Drive.
- `EPISODE.md`: `drive:` theo quy ước mới `ClaudeFilmLab/<ProjectName>/03_KichBan/ep<NN>-<slug>` (lệch là WARN trong
  `check_episode.py`); cột cuối của `## Nhật ký` là giờ đẩy Drive thay cho commit.
- `tools/bundle.py`: tìm thư mục tập trong `projects/<project>/` trước, `series/` (cũ) sau; cờ `--episode-dir`
  (`--series-dir` vẫn dùng được).
- Hook khởi động nhắc kéo dự án khi `projects/` trống; `docs/RUNBOOK.md` thêm các sự cố đồng bộ Drive.
- Fixture test chuyển sang `tests/fixtures/projects/test-series/`.

### Thêm
- `tools/drive_sync.py` (cục bộ, không gọi mạng): `snapshot` sau khi kéo (`.pulled.sha256`, `.pulled.at`), `plan` in
  lệnh connector cho mỗi file mới/đã đổi theo ánh xạ §11.3 (ID thư mục từ `PROJECT.md` hoặc thư mục cần tạo trước, mime,
  tham chiếu `sha256:<hex>:<đường dẫn>`, truy vấn `search_files` và tên lưu trữ `99_LuuTru/`; `--json`), `record` sau
  mỗi lần tải lên (thay dòng dấu, ghi `.pushed.log`). CONVENTIONS §11.6 và `film-pipeline` §0 dùng công cụ này;
  test `tests/test_drive_sync.py`.
- `templates/project/`: `PROJECT.md`, `SERIES.md`, `README_CauTruc.md` (Google Doc cho người đọc),
  `TienDo_SanXuat.csv` (header của Google Sheet tiến độ), `pronunciation.csv` (header `term,doc`).
- Ánh xạ §11.3 `projects/<project>/pronunciation.csv` (bảng phát âm Hán Việt cho `vieneu_tts.py --pron`) ↔
  `02_KinhThu/pronunciation.csv`, cạnh `SERIES.md`; trước đây `drive_sync.py plan` báo UNMAPPED và thoát 1.

### Sửa
- `drive_sync.py`: thêm `*.lock`, `*.swp` vào danh sách file tạm không đẩy – trước đây `anchors.json.lock` lọt vào kế hoạch đẩy.
- `drive_sync.py plan`: file NEW (không có dòng trong `.pulled.sha256`) cũng được in truy vấn `search_files` và tên lưu
  trữ, nhãn "if a file with this title already exists in the folder (first push), archive it" (JSON: `archive.when`
  `if_exists`, CHANGED là `always`), để lần đẩy đầu sau khi tải tay hoặc mất dấu không để lại bản trùng trên Drive.
  CONVENTIONS §11.6 bước 1 và 4 cập nhật theo.
- `tools/ark.py`: kiểm ngân sách và giữ chỗ thành một bước nguyên tử (`reserve()`: một `LOCK_EX` trên ledger bao quanh
  đọc ledger, cộng tổng, ghi `pending` hoặc `refused-budget`; nén `--ref` làm trước khoá). N agent song song không còn
  vượt trần tối đa N−1 request; gỡ "giới hạn đã biết" ở CONVENTIONS §7 và WORKFLOW §4. Thêm test 8 tiến trình
  tranh trần 3 ảnh (#15 phần 1).
- `film-reviewer` không ghi được `review/qc-<v>.md` và MEMORY.md (chỉ có `Read, Glob, Grep`; `memory: project` không tự
  cấp công cụ ghi, đạo diễn phải lưu báo cáo tay). Thêm `Write, Edit` (vẫn không Bash), prompt giới hạn chỉ ghi
  `review/qc-*.md` của tập và `.claude/agent-memory/film-reviewer/MEMORY.md`; sửa WORKFLOW §3, CONVENTIONS, film-pipeline.

### Gỡ bỏ
- `series/son-hai-kinh/` khỏi repo (đã chuyển lên Drive `ClaudeFilmLab/SonHaiKinh/`).

## [1.0.0] - 2026-11-10

Bản phát hành đầu tiên: bộ công cụ, skill, agent và quy trình chuẩn để làm phim AI 2.5D nhiều lớp trong phiên
Claude Code cloud với BytePlus ModelArk và cinecode.

### Thêm
- **Hợp đồng chung** `docs/CONVENTIONS.md`: cấu trúc thư mục, quy ước đặt tên (kèm regex), schema `style.yaml`,
  `EPISODE.md`, `shots.csv`, `prompts.csv`, `budget.yaml`, `ledger.csv`, cùng bảng quyết định thiết kế (#1).
- **Quy trình một tập** `docs/WORKFLOW.md`: khâu 0–11, cổng duyệt G1–G4, ngân sách, chuyển giao phiên qua `EPISODE.md` (#6).
- **Skill**: `film-pipeline` (đạo diễn điều phối), `film-script` (#2), `film-prompt-layers` (#3), `film-compose-shot` (#4).
- **8 subagent theo vai** trong `.claude/agents/`: researcher, writer, art-director, plate-maker, animator, compositor,
  reviewer (chỉ đọc), publisher; bộ nhớ khởi tạo cho art-director và reviewer (#7).
- **Style pack**: `styles/_template`, `styles/thuy-mac` (kế thừa recipe `ink-wash` của cinecode),
  `styles/moc-ban` (nháp, kế thừa `woodcut`) để chứng minh thêm trường phái không cần sửa skill (#5).
- **Series** `series/son-hai-kinh`: kinh thư, nhân vật Bác Thi (nguyên văn 南山經 đã đối chiếu trên zh.wikisource,
  chú âm Quách Phác "博施" đã xác minh), bối cảnh núi Cơ, và tập `ep01-bac-thi` bản 60 s đã qua khâu kịch bản
  (research, script, shot list) – chưa tạo ảnh.
- **`tools/ark.py`**: `--seed`, `--negative`, `--guidance`; nén ảnh `--ref` thành JPEG ≤ 2048 px trước khi gửi;
  ngân sách **bắt buộc**: `--budget` + `--ledger` (hoặc `FILM_BUDGET`, `FILM_LEDGER`; `FILM_AGENT` ghi tên agent),
  thiếu thì thoát mã 2, `--no-budget` chỉ để thử nhanh; vượt trần thoát mã 3 trước khi gọi API. Ledger ghi dòng
  `pending` trước mỗi request và dòng kết thúc cùng mã `req=`, nên tiến trình bị kill vẫn để lại dấu vết tính phí;
  SIGTERM ghi `failed`; `video --resume-task <id>` tải lại clip của task cũ thay vì tạo mới; tự tạo thư mục đầu ra
  trước khi gọi API.
- **`tools/check_episode.py`**: kiểm tập (front matter, nhịp shot, mốc giây lời bình, tên file media, khung clip,
  prompts.csv) và style pack (schema, matte, placeholder prompt, id chuyển động); `--probe` đo kích thước, fps,
  thời lượng, âm thanh bằng ffprobe và độ lớn -14 LUFS của bản cuối, ghi vào `review/check-<v>.txt` cho reviewer.
- **`tools/layers/`**: `matte.py` (none / luminance / chroma có despill / rembg + ngưỡng theo lớp từ `style.yaml`),
  `anchors.py` (ghi điểm neo, vẽ dấu để duyệt), `upscale.py` (Lanczos, tạm thời).
- **`tools/compose/`**: bộ JS dựng 2.5D cho cinecode Quick (parallax theo độ sâu, máy quay, sương, tàn lửa, quầng nắng,
  đung đưa theo dải, chớp mắt, thở), `inline.py` nối vào `film.html`, sổ đăng ký `motions.json`.
- **`tools/bundle.py`**: gói zip theo shot (kèm `--with-film`) và in tham chiếu file cho Google Drive.
- **Hook khởi động** cài font CJK, `rembg`, PyYAML; trỏ `/opt/byteplus/ark.py` vào repo; đặt `CINECODE_FORMATS`
  và `CHROME_PATH`; in báo cáo `doctor --quick`.
- **Test**: 124 test `unittest` (`python3 -m unittest discover -s tests`), gồm kill tiến trình thật (SIGKILL) để kiểm ledger.

### Sửa sau review nội bộ (trước phát hành)
- `check_episode` chặn nhầm cổng G2 (dòng prompt chưa có ảnh) và G3/G4 (khung clip Seedance).
- `ark.py` có thể mất ảnh đã trả phí khi thư mục đầu ra chưa có; ledger thiếu dòng khi tiến trình bị kill.
- Hook khởi động: `pipefail` làm phép kiểm font luôn sai, `apt-get` chạy mỗi phiên; lỗi apt chặn các bước sau.
- `anchors.py` mất cập nhật khi nhiều agent ghi song song (thêm khoá file).
- Tài liệu dựng: lớp clip `seq` không dùng `place`; `bundle.py --with-film` thay cho zip tay; `--size` theo `style.yaml`.

### Quyết định thiết kế (so với đề xuất ở issue)
- Trạng thái tập là `EPISODE.md`, không phải `STATE.md` (tên của cinecode).
- Style pack kế thừa recipe cinecode qua `base:` thay vì viết lại chuyển động và âm thanh.
- Thủy mặc tách alpha theo độ đậm mực (`luminance`) cho lớp giữa/tiền cảnh để giữ vệt mực loang;
  `rembg` trên nền trắng cho nhân vật.
- Ngân sách do `ark.py` chặn, không chỉ dựa vào chỉ dẫn trong prompt; reviewer không có Bash.
- Lưu Google Drive theo gói mỗi shot thay vì từng file.

### Đã kiểm chứng
- Đường dựng 2.5D chạy qua render của cinecode với ảnh giả lập: `deterministic: yes`, bản nháp 960x540 ~20 s.
- Seedream nhận tham số `seed`, `negative_prompt`, `guidance_scale` (kiểm tra miễn phí); hiệu quả thực tế chưa đo.
- Container truy cập được zh.wikisource.org; ctext.org chặn truy cập tự động.

### Giới hạn đã biết
- Proxy của phiên cloud cắt request đồng bộ > 30 s: ảnh Seedream 5.0 Pro và ảnh 4K không chạy được trực tiếp;
  `lambda/` đã viết nhưng **chưa triển khai**.
- Chưa tạo ảnh/video thật bằng bộ công cụ mới: chất lượng tách mực, clip Seedance làm lớp, và mức chuyển động
  (cinecode báo TOO STILL với tranh tĩnh) cần đợt chạy thử có phí.
- N agent tạo ảnh song song có thể vượt trần ngân sách tối đa N−1 request.
- Lồng tiếng tiếng Việt chạy local (#8) chưa có.

[Unreleased]: https://github.com/danny-exnodes/claude-film-lab/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/danny-exnodes/claude-film-lab/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/danny-exnodes/claude-film-lab/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/danny-exnodes/claude-film-lab/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/danny-exnodes/claude-film-lab/releases/tag/v1.0.0
