# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/), phiên bản theo [SemVer](https://semver.org/lang/vi/).

## [Unreleased]

Dữ liệu dự án phim chuyển lên Google Drive; repo chỉ còn là lõi dùng lại.

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

[Unreleased]: https://github.com/danny-exnodes/claude-film-lab/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/danny-exnodes/claude-film-lab/releases/tag/v1.0.0
