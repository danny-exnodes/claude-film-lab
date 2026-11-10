# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/), phiên bản theo [SemVer](https://semver.org/lang/vi/).

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
  `--budget`/`--ledger` (biến môi trường `FILM_BUDGET`, `FILM_LEDGER`, `FILM_AGENT`) chặn vượt trần trước khi gọi API,
  ghi mọi lần gọi kể cả lỗi và request bị proxy cắt; thoát mã 3 khi vượt ngân sách.
- **`tools/check_episode.py`**: kiểm tập (front matter, nhịp shot, mốc giây lời bình, tên file media, prompts.csv)
  và style pack (schema, matte, placeholder prompt, id chuyển động).
- **`tools/layers/`**: `matte.py` (none / luminance / chroma có despill / rembg + ngưỡng theo lớp từ `style.yaml`),
  `anchors.py` (ghi điểm neo, vẽ dấu để duyệt), `upscale.py` (Lanczos, tạm thời).
- **`tools/compose/`**: bộ JS dựng 2.5D cho cinecode Quick (parallax theo độ sâu, máy quay, sương, tàn lửa, quầng nắng,
  đung đưa theo dải, chớp mắt, thở), `inline.py` nối vào `film.html`, sổ đăng ký `motions.json`.
- **`tools/bundle.py`**: gói zip theo shot (kèm `--with-film`) và in tham chiếu file cho Google Drive.
- **Hook khởi động** cài font CJK, `rembg`, PyYAML; trỏ `/opt/byteplus/ark.py` vào repo; đặt `CINECODE_FORMATS`
  và `CHROME_PATH`; in báo cáo `doctor --quick`.
- **Test**: 91 test `unittest` (`python3 -m unittest discover -s tests`).

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
