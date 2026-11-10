# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/), phiên bản theo [SemVer](https://semver.org/lang/vi/).

## [Unreleased]

Dữ liệu dự án phim chuyển lên Google Drive; repo chỉ còn là lõi dùng lại.

### Thêm
- `tools/tts/vieneu_tts.py` (issue #8): lồng tiếng Việt local trên CPU bằng VieNeu-TTS v3 Turbo (`vieneu` 3.8.3,
  Apache-2.0, giọng mẫu dùng thương mại được): đọc `script.md` (quy tắc của `check_episode.py`) hoặc `vo-lines.json`,
  ghi `<id>.wav` 48 kHz + `tts-log.json` (model, phiên bản, giấy phép, watermark), so độ dài với khung `[mm:ss]`,
  chuẩn hóa số/năm/đơn vị, bảng phát âm `term,doc`, chế độ `--audition`. Cài riêng (không vào hook), xem
  `tools/tts/README.md`. Test không cần model: `tests/test_tts.py`.

### Thay đổi
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
  `TienDo_SanXuat.csv` (header của Google Sheet tiến độ).

### Sửa
- `tools/ark.py`: kiểm ngân sách và giữ chỗ thành một bước nguyên tử (`reserve()`: một `LOCK_EX` trên ledger bao quanh
  đọc ledger, cộng tổng, ghi `pending` hoặc `refused-budget`; nén `--ref` làm trước khoá). N agent song song không còn
  vượt trần tối đa N−1 request; gỡ "giới hạn đã biết" ở CONVENTIONS §7 và WORKFLOW §4. Thêm test 8 tiến trình
  tranh trần 3 ảnh (#15 phần 1).

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

[1.0.0]: https://github.com/danny-exnodes/claude-film-lab/releases/tag/v1.0.0
