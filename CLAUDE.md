# AI Film Lab – quy trình chuẩn cho Claude

Repo này chứa **lõi dùng lại** (mã, skill, agent, style pack, mẫu, quy trình) cho các phiên Claude Code cloud làm phim AI
(BytePlus ModelArk: Seedream cho ảnh, Seedance cho video; skill `cinecode` để dựng phim bằng code).
Dữ liệu từng dự án phim nằm trên Google Drive, không nằm trong repo.

## Quy tắc bắt buộc
- **Không bao giờ in, ghi log, đọc hay tìm API key** (Ark, AWS, Google). Trong phiên cloud, proxy tự chèn
  khóa Ark cho `ark.ap-southeast.bytepluses.com`; `tools/ark.py` chỉ gửi giá trị giả.
- Không yêu cầu người dùng dán khóa vào chat. Khóa cho Lambda do người dùng tự nhập ở AWS Console.
- Tạo ảnh/video là có tính phí: không gen thử ngoài yêu cầu; kiểm tra miễn phí trước (`tools/doctor.sh`).
- Request bị proxy cắt (502 sau ~30 s) **có thể vẫn bị tính phí** → không tự thử lại.
- **Dữ liệu dự án không bao giờ commit vào repo** (kinh thư, nhân vật, bối cảnh, nghiên cứu, kịch bản, shot list,
  `EPISODE.md`, ngân sách, prompt, tiến độ, tài liệu gốc, media). Nó chỉ nằm trên Drive và trong bản làm việc
  `projects/<project>/` + `out/<project>/` (git bỏ qua).

## Dự án trên Drive
- Gốc lab: Drive `ClaudeFilmLab` (ID `19yQarw7ATu90uzXjboGP4sy5FzlQhd0y`), mỗi dự án một thư mục `<ProjectName>/`
  (vd. `SonHaiKinh/`): `00_QuanLy · 01_TaiLieuGoc · 02_KinhThu · 03_KichBan · 04_SanXuat · 05_ThanhPham · 99_LuuTru`.
  Cấu trúc, `PROJECT.md`, ánh xạ đường dẫn, quy tắc đặt tên: `docs/CONVENTIONS.md` §11. Mẫu: `templates/project/`.
- **Kéo** đầu phiên, trước mọi việc, bằng connector Google Drive (không có CLI): đọc `00_QuanLy/PROJECT.md` trước (ID mọi
  thư mục), luôn tải `SERIES.md`, `EPISODE.md`, `budget.yaml` và mọi bản `ledger.csv` về `projects/<project>/` và
  `out/<project>/ep<NN>/`; file khác kéo theo khâu sắp chạy (film-pipeline mục 0).
- **Đẩy** file chữ đã đổi sau mỗi khâu và trước khi dừng phiên (container bị thu hồi khi rảnh); cập nhật
  `TienDo_SanXuat`. Bản mới = file mới; bản cũ chuyển vào `99_LuuTru/` (§11.6). Không xoá gì trên Drive.

## Làm phim
- Mọi việc làm tập phim đi qua skill `film-pipeline` (phiên chính là đạo diễn): đọc `EPISODE.md` của tập trước,
  không dựa vào lịch sử chat; giao việc cho agent trong `.claude/agents/`; cổng duyệt G1–G4 chỉ do người dùng qua.
- Hợp đồng chung (cấu trúc, đặt tên, schema): `docs/CONVENTIONS.md`. Quy trình: `docs/WORKFLOW.md`.
- Mỗi tập một phương pháp dựng, ghi trong `EPISODE.md`: `method: layers` (chỉ ảnh + chuyển động bằng code, tạo theo lô bằng
  `ark.py image-batch`, không Seedance: `ai_motion` trống, `video_seconds: 0`, bỏ khâu 6) hoặc `method: seedance` (clip cho
  cử động lớn) hoặc `method: code` (nhân vật và cảnh vẽ hoàn toàn bằng code với bộ `tools/toon/`, style `engine: code`,
  `images: 0`, `video_seconds: 0`, bỏ khâu 5–6; `.claude/skills/film-compose-shot/references/code-method.md`). Thiếu khóa = `seedance` (WARN).
  Người dùng chọn ở khâu 0 (với `code`: cho xem `python3 tools/toon/toon.py lookbook`); không trộn trong một tập, sau G1 không tự đổi.
  Quy tắc dàn cảnh của `layers` (không trượt, không xoay thân, không bộ phận rời):
  `.claude/skills/film-compose-shot/references/layers-method.md` và `layers-character.md`. Người nhỏ trong cảnh rộng
  (≤ 25 % chiều cao khung: đứng trên sống núi, đi dọc đường, đám đông ở xa) vẽ bằng code, không mua tranh:
  `COMPOSE.figure.draw` (id `figure`), `references/layers-figure.md`.
- Trạng thái tập là `EPISODE.md`, **không bao giờ** `STATE.md` (tên đó thuộc cinecode).
- Mọi lệnh tạo ảnh/video cho một tập phải có `--budget <tập>/budget.yaml --ledger out/<project>/ep<NN>/ledger.csv`
  và `FILM_AGENT=<tên agent>` khi chạy trong agent.
- Trước mỗi cổng duyệt: `python3 tools/check_episode.py episode <thư mục tập> --out review/check-v<N>.txt` (thêm `--probe`
  từ G3) không còn ERROR, và `python3 tools/status.py <thư mục tập> --gate <G>` in `READY`. `budget.yaml` thiếu hoặc sai
  khóa, và `stage` vượt cổng chưa có ngày, đều là ERROR.

## Khởi động phiên
Hook `.claude/hooks/session-start.sh` tự chạy: cài font CJK + `rembg`, trỏ `/opt/byteplus/ark.py` vào
`tools/ark.py`, in báo cáo `doctor --quick`. Nếu báo cáo có FAIL → xử lý theo `docs/RUNBOOK.md` trước khi làm việc.
Kiểm tra đầy đủ: `tools/doctor.sh` – gửi thêm đúng một request video với độ phân giải sai, Ark từ chối trước khi tạo task nên
không bị tính phí; nếu doctor báo `unexpected task <id> created` thì huỷ task đó trong Ark Console. Trong git worktree hook
không đổi `/opt/byteplus/ark.py`. Hook luôn in báo cáo doctor, kể cả khi pip lỗi (`film-lab: pip install failed`).

## Công cụ
```
python3 tools/ark.py ping
python3 tools/status.py projects/<project>/ep<NN>-<slug> [--gate G2]   # chỉ đọc: khâu, phương pháp, cổng, ngân sách, request dở, lớp tranh, dự báo chi phí, điều kiện cổng
python3 tools/ark.py image "<prompt>" <file>.png --size 2K [--fast] [--ref a.png] --budget B --ledger L   # lite 2K ~25 s · flash 1024² ~11 s
python3 tools/ark.py image-batch <jobs.csv> --budget B --ledger L [--parallel 3] [--dry-run] [--only ID ...] [--fast]   # cả lô lớp tranh: kiểm hết trước khi gửi, bỏ qua file đã có
python3 tools/ark.py video "<prompt>" <file>.mp4 --image <khung đầu>.png --duration 5 [--resolution 720p] [--no-audio] --budget B --ledger L
python3 tools/layers/matte.py IN.png [OUT.png] --style styles/<id> --layer L2 --preview check.png   # bỏ OUT → plates/matte/<cùng tên>.png
python3 tools/compose/keyframe.py --check <khung đầu>.png --key "#RRGGBB"                # miễn phí, trước mỗi clip tính phí
python3 tools/layers/matte_seq.py <clip>.mp4 --start-frame <khung đầu>.png --strict      # tách nền cả clip + số đo nhấp nháy
python3 tools/tts/vieneu_tts.py --script <tập>/script.md --pron projects/<project>/pronunciation.csv --out <media>/vo --dry-run --strict
python3 tools/audio/score.py <tập>/score.json --dry-run | --out <media>/audio [--stems] [--seed N]   # nhạc dây gảy + tiếng động theo sự kiện, local, miễn phí
python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug> [--probe] --out review/check-v<N>.txt
python3 tools/drive_sync.py snapshot|pulled|plan|record projects/<project> [--include-out out/<project>]
python3 tools/toon/toon.py still|turntable|clip|lookbook ...          # method: code, miễn phí: xem style vẽ bằng code, linh vật giot
python3 tools/compose/inline.py <film>/film.html --init --toon         # film.html cho tập method: code (bộ TOON + mẫu shot)
```
- Mã thoát của `ark.py image|video|lambda-job prepare`: **2** = từ chối tại chỗ, chưa gửi gì → sửa lệnh; **3** = vượt trần;
  **1** = request đã rời máy, xem dòng ledger. File đầu ra đã tồn tại bị từ chối (tăng `_v<NN>`; `--overwrite` chỉ cho thử
  tay); `budget.yaml` chỉ nhận `images / video_seconds / models / ledger_required`; `matte.py` và `upscale.py` không ghi đè
  ảnh gốc. `ark.py video` mặc định 720p, chỉ nhận `480p|720p|1080p`.
- `matte.py --method rembg` dùng model `u2net` (đổi bằng `--rembg-model` / `FILM_REMBG_MODEL`); model chưa tải sẵn thì bị từ
  chối, không tự tải (`--allow-download`).
- Khung đầu của clip luôn do `tools/compose/keyframe.py` tạo (`clips/..._start_v<NN>.png`, không lấy file trong `plates/`);
  khung clip tách nền bằng `tools/layers/matte_seq.py`, không chạy `matte.py` từng khung.
- Âm thanh bằng code: `tools/audio/score.py` (cổ cầm, tỳ bà, koto, cồng, trống khung, drone, bộ tiếng động;
  `tools/audio/README.md`). Chỉ viết phần `music` khi người dùng đã chọn nhạc code; `foley` dùng được với mọi lựa chọn.
  `score.json` là dữ liệu dự án (không commit). Chất âm chưa có người nghe duyệt.
- Lời bình: chỉ `tools/tts/vieneu_tts.py` (agent `film-narrator`); không dùng `tts.py`/`keys.py` của cinecode (chúng tìm khóa).
- Chọn model và giới hạn: `docs/MODELS.md`.
- Ảnh **pro** hoặc **4K** vượt giới hạn 30 s của proxy → dùng Lambda (`lambda/README.md`), không dùng `--force`.
  Mọi job Lambda đi qua `ark.py lambda-job prepare` (kiểm trần, ghi `pending`, in payload) và `lambda-job finish`
  (dòng cuối); không có ledger thì không gọi Lambda.
- Hai bản `ledger.csv` của một tập (hai phiên, hai file trên Drive) → `ark.py ledger-merge`, không lấy bản mới nhất.
- Video chạy dạng task bất đồng bộ, không bị giới hạn 30 s; một video 5 s mất ~2–3 phút → chạy Bash với timeout dài
  hoặc `run_in_background`.

## Quy ước file
- Media gen ra để trong `out/<project>/ep<NN>/{plates,clips,renders}/` (git bỏ qua), đặt tên theo
  `docs/CONVENTIONS.md` §2. Không commit ảnh/video.
- Sau khi người dùng duyệt shot: `python3 tools/bundle.py out/<project>/ep<NN> --shot s<NN>` rồi tải zip lên Drive
  `ClaudeFilmLab/<ProjectName>/04_SanXuat/ep<NN>-<slug>/<YYYY-MM-DD>/` bằng connector Google Drive (`create_file` với
  tham chiếu file `sha256:<hash>:<đường dẫn>` mà bundle.py in ra; người dùng duyệt mỗi lần tải). Bản dựng duyệt tải
  lên riêng (bản cuối vào `05_ThanhPham/ep<NN>-<slug>/`).
- Container bị thu hồi khi phiên rảnh: thay đổi mã/quy trình (lõi) phải commit + push; dữ liệu dự án phải đẩy lên Drive
  trước khi kết thúc.

## Khi cải tiến repo
- Sửa `tools/ark.py` → cập nhật `docs/MODELS.md` nếu đổi model, chạy `tools/doctor.sh`.
- Gặp lỗi mới → thêm vào `docs/RUNBOOK.md` (triệu chứng, nguyên nhân, cách xử lý).
- Sửa `lambda/ark_image_worker.py` → triển khai lại theo `lambda/README.md` (mục "Triển khai lại"); `build_deploy.py --check`
  in hai mã băm phải khớp với function đang chạy.
- Sửa `tools/toon/*.js` → tăng `T.VERSION` trong `rig.js`, chạy `tests/test_toon.py` (node + trình duyệt) và
  `tests/test_method_code.py`; look/hậu kỳ mới → thêm vào `looks.json` và `TOON.LOOKS`/`TOON.POSTS` (`toon.js`).
  Đổi phiên bản three.js: `tools/toon/three.lock` + `docs/setup-script.sh` (`THREE_VER`), `docs/RUNBOOK.md` ("three.js").
- Sửa `tools/compose/*.js` → tăng `C.VERSION` trong `core.js`, chạy test (`tests/test_compose_js.py`,
  `tests/test_compose_character.py`, `tests/test_compose_figure.py` cần node) và `python3 tools/compose/inline.py --lint`. Module mới → thêm vào `ORDER`
  của `inline.py` và `motions.json`.
- Mã phỏng theo dự án khác → ghi nguồn ở đầu file và thêm một dòng vào `THIRD_PARTY.md`.
- Lỗi đã biết nhưng chưa sửa và việc hoãn lại: `docs/BACKLOG.md`.
- cinecode được ghim ở `tools/compose/cinecode.ref` (= `CINECODE_REF` trong `docs/setup-script.sh`); đổi ghim theo
  `docs/RUNBOOK.md` ("cinecode đổi template"), không `git pull` trong thư mục skill.
- Phát hành: `docs/RELEASING.md`. Claude chỉ sửa `CHANGELOG.md` và mở PR; **không** `git tag`, không push tag, không gọi
  API release (phiên cloud bị chặn 403 – đúng như dự kiến, không thử lại). Tag và GitHub Release do người dùng tạo tay.
