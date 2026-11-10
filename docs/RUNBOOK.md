# Runbook – sự cố đã gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `HTTP 404 ModelNotOpen ... has not activated the model X` | Model chưa kích hoạt trên tài khoản Ark | Kích hoạt trong Ark Console nếu có trong danh sách; không thì đổi model theo `docs/MODELS.md` |
| `HTTP 404 InvalidEndpointOrModel.NotFound` | Sai ID model | Tra `docs/MODELS.md` hoặc `tools/ark.py ping --all` |
| `HTTP 502 upstream request failed` sau đúng ~30 s | Proxy chèn khóa của Claude cloud cắt request đồng bộ > 30 s (ảnh pro, ảnh 4K) | Không thử lại (có thể đã bị tính phí). Giảm `--size`, dùng `--fast`, hoặc chạy qua Lambda (`lambda/README.md`). Báo Anthropic để nâng giới hạn – mẫu báo cáo bên dưới |
| Video ra vuông dù `--resolution 720p` | Ảnh đầu vào vuông, `ratio=adaptive` | Truyền `--ratio 16:9` (model sẽ crop) hoặc dùng ảnh 16:9 |
| `ModuleNotFoundError: rembg` / thiếu font CJK | Hook khởi động chưa chạy hoặc lỗi | `CLAUDE_CODE_REMOTE=true .claude/hooks/session-start.sh` |
| Connector (AWS, Drive…) báo cần đăng nhập lại, sau khi đăng nhập vẫn không có tool | Phiên đã gỡ server khi lỗi xác thực, không nạp lại giữa chừng | Commit/push công việc, mở **phiên mới** |
| `ark.py image/video` thoát mã 2: "budget and ledger required" | Từ v1.0.0 ngân sách là bắt buộc | Thêm `--budget <tập>/budget.yaml --ledger out/<project>/ep<NN>/ledger.csv`; thử nhanh ngoài tập (phiên chính) dùng `--no-budget` |
| Ledger có dòng `pending` không có dòng kết thúc | Tiến trình bị kill (timeout, container thu hồi) giữa lúc tạo | Vẫn tính là đã trả phí. Video: `ark.py video --resume-task <task_id> --ledger L` để tải clip thay vì tạo lại |
| `ark.py` thoát mã 3, ledger ghi `refused-budget` | Vượt trần trong `budget.yaml` của tập | Hỏi người dùng nâng trần (phiên chính), không tự sửa `budget.yaml` trong agent |
| `ctext.org` trả trang ~2,8 KB nhắc "robot" thay vì nội dung | ctext chặn truy cập tự động | Dùng `zh.wikisource.org` (tải bình thường từ container) |
| cinecode tự kích hoạt hoặc đọc nhầm trạng thái tập | Thư mục có file `STATE.md` (tên riêng của cinecode) | Trạng thái tập luôn là `EPISODE.md`; `STATE.md` chỉ nằm trong thư mục film của cinecode |
| `gh issue list` / `gh pr ...` báo `GitHub GraphQL is not available` | Phiên cloud chỉ cho REST API | Dùng `gh api repos/<owner>/<repo>/...` |
| Định dạng cinecode đã lưu biến mất ở phiên mới | Mặc định lưu ở `~/.cinecode/formats` | Hook đặt `CINECODE_FORMATS=<repo>/formats`; commit định dạng đã duyệt |
| `make.py stills/draft/final` lỗi khi mở Chrome (chạy bằng root, "Running as root without --no-sandbox") | Container chạy root; `capture.mjs` chỉ đọc `CHROME_PATH` | Hook đặt `CHROME_PATH=<repo>/tools/compose/chrome-root.sh` (thêm `--no-sandbox`). Phiên cũ: `export` tay biến này |
| Bản nháp bị giữ vì **TOO STILL** | Chuyển động nhỏ trên tranh nhạt có điểm 0,2–0,45 so với ngưỡng 1,0 của cinecode | Đúng như dự kiến với tranh tĩnh: cắt shot ngắn lại, thêm hành động hoặc đẩy máy rõ hơn (`film-compose-shot` §6) |
| Bản nháp bị giữ vì **SOUND THIN / SOUND ALL CODE** | Âm thanh chỉ do code tạo | Thêm bản ghi thật (gió, bước chân…) theo `styles/<id>/sound.md` |
| Plugin GitHub lỗi `Authorization header is badly formatted` | Lỗi kết nối plugin | Không ảnh hưởng clone/push (đi qua git proxy); kết nối lại plugin trong cài đặt nếu cần GitHub API |
| Không có `projects/<project>/` hay `EPISODE.md` khi bắt đầu phiên | Dữ liệu dự án không nằm trong repo; container mới chưa kéo | Kéo từ Drive theo `docs/CONVENTIONS.md` §11.6: `ClaudeFilmLab/<ProjectName>/00_QuanLy/PROJECT.md` trước. Không có Drive connector → dừng, báo người dùng bật connector (không tạo lại từ trí nhớ) |
| Ngân sách tập "còn nguyên" dù đã tạo ảnh ở phiên trước | `out/<project>/ep<NN>/ledger.csv` chưa được kéo về | Kéo `04_SanXuat/ep<NN>-<slug>/ledger.csv` trước khi gọi `ark.py`; đẩy lại sau mỗi khâu có tạo ảnh/video |
| Hai file cùng tên trong một thư mục Drive | Lần đẩy trước bị ngắt giữa "tải bản mới" và "chuyển bản cũ" | Giữ file `modifiedTime` mới nhất, chuyển file cũ vào `99_LuuTru/` với tên có giờ (§11.6 bước 3) |
| `update_file` không đổi được nội dung file trên Drive | Connector chỉ sửa metadata (tên, thư mục) | Đúng thiết kế: đẩy bản mới bằng `create_file`, chuyển bản cũ vào `99_LuuTru/` |
| CSV/Markdown tải lên thành Google Sheet/Doc | Thiếu `disableConversionToGoogleType: true` | Chuyển file đó vào `99_LuuTru/`, tải lại với cờ này (chỉ `README_CauTruc`, `TienDo_SanXuat` được chuyển đổi) |
| `drive_sync.py plan` thoát mã 1: `MISSING – create folder …` hoặc `UNMAPPED` | Thư mục Drive chưa có ID trong `drive.folders` của `PROJECT.md` (hoặc còn `<id>`), hay file nằm ngoài bảng ánh xạ §11.3 | Tạo thư mục theo đúng thứ tự `plan` in (`create_file` folder, `parentId` = ID cha), ghi ID vào `drive.folders`, chạy lại `plan`; file UNMAPPED thì chuyển vào thư mục có ánh xạ |
| `plan` vẫn liệt kê file vừa đẩy | Chưa chạy `drive_sync.py record … --uploaded <file> --id <ID mới>` sau `create_file` | Chạy `record` cho đúng file đã tải; không chạy lại `snapshot` sau khi đẩy (sẽ xoá dấu của file người dùng từ chối tải) |

## Mẫu báo cáo giới hạn 30 s cho Anthropic
> Claude Code on the web: requests to a host using proxy-injected credentials (`ark.ap-southeast.bytepluses.com`)
> are cut at ~30 s with `HTTP 502 upstream request failed`. Requests under ~26 s succeed; every request over 30 s
> fails at 30.1 s (reproduced with 3 different payloads). `/__agentproxy/status` shows no `recentRelayFailures`.
> The upstream API (synchronous image generation) legitimately takes 30–60 s. Please raise or make configurable
> the upstream timeout for injected-credential hosts.
