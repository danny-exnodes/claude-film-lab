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
- **Kéo** đầu phiên, trước mọi việc: đọc `00_QuanLy/PROJECT.md` trước (ID mọi thư mục), tải kinh thư, tập đang làm và
  `ledger.csv` về `projects/<project>/` và `out/<project>/ep<NN>/` bằng connector Google Drive (không có CLI).
- **Đẩy** file chữ đã đổi sau mỗi khâu và trước khi dừng phiên (container bị thu hồi khi rảnh); cập nhật
  `TienDo_SanXuat`. Bản mới = file mới; bản cũ chuyển vào `99_LuuTru/` (§11.6). Không xoá gì trên Drive.

## Làm phim
- Mọi việc làm tập phim đi qua skill `film-pipeline` (phiên chính là đạo diễn): đọc `EPISODE.md` của tập trước,
  không dựa vào lịch sử chat; giao việc cho agent trong `.claude/agents/`; cổng duyệt G1–G4 chỉ do người dùng qua.
- Hợp đồng chung (cấu trúc, đặt tên, schema): `docs/CONVENTIONS.md`. Quy trình: `docs/WORKFLOW.md`.
- Trạng thái tập là `EPISODE.md`, **không bao giờ** `STATE.md` (tên đó thuộc cinecode).
- Mọi lệnh tạo ảnh/video cho một tập phải có `--budget <tập>/budget.yaml --ledger out/<project>/ep<NN>/ledger.csv`
  và `FILM_AGENT=<tên agent>` khi chạy trong agent.
- Trước mỗi cổng duyệt: `python3 tools/check_episode.py episode <thư mục tập>` không còn ERROR.

## Khởi động phiên
Hook `.claude/hooks/session-start.sh` tự chạy: cài font CJK + `rembg`, trỏ `/opt/byteplus/ark.py` vào
`tools/ark.py`, in báo cáo `doctor --quick`. Nếu báo cáo có FAIL → xử lý theo `docs/RUNBOOK.md` trước khi làm việc.
Kiểm tra đầy đủ (vẫn miễn phí): `tools/doctor.sh`.

## Công cụ
```
python3 tools/ark.py ping
python3 tools/ark.py image "<prompt>" <file>.png --size 2K [--fast] [--ref a.png] --budget B --ledger L   # lite ~25 s · flash ~11 s
python3 tools/ark.py video "<prompt>" <file>.mp4 --image <khung đầu>.png --duration 5 --resolution 720p [--no-audio] --budget B --ledger L
python3 tools/layers/matte.py IN.png OUT.png --style styles/<id> --layer L2 --preview check.png
python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug>
```
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
- Sửa `lambda/ark_image_worker.py` → triển khai lại theo `lambda/README.md`.
- cinecode được ghim ở `tools/compose/cinecode.ref` (= `CINECODE_REF` trong `docs/setup-script.sh`); đổi ghim theo
  `docs/RUNBOOK.md` ("cinecode đổi template"), không `git pull` trong thư mục skill.
- Phát hành: `docs/RELEASING.md`. Claude chỉ sửa `CHANGELOG.md` và mở PR; **không** `git tag`, không push tag, không gọi
  API release (phiên cloud bị chặn 403 – đúng như dự kiến, không thử lại). Tag và GitHub Release do người dùng tạo tay.
