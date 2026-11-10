---
name: film-pipeline
description: >-
  Điều phối một dự án/tập phim AI Film Lab từ đầu đến cuối ở phiên chính (vai đạo diễn): mở dự án trên Google Drive,
  kéo dự án về projects/<project>/, đọc EPISODE.md, chạy khâu 0–11, giữ cổng duyệt G1–G4, giao việc cho các agent
  film-*, kiểm ngân sách qua ledger, cập nhật EPISODE.md và TienDo_SanXuat, đẩy chữ và gói shot lên Drive. Dùng khi
  người dùng nói "dự án mới", "mở dự án", "kéo dự án", "làm tập phim", "làm tập mới", "mở tập", "tiếp tục tập",
  "làm tiếp ep01", "làm quyển 1 tập 1", "tiếp q01t01", "tập tiếp theo", "duyệt kịch bản", "qua cổng", "duyệt shot mẫu", "duyệt bản nháp", "bản cuối",
  "lưu Drive", hoặc nhắc tới PROJECT.md, EPISODE.md, budget.yaml, ledger.csv, projects/<project>/ep<NN>-<slug> hoặc
  projects/<project>/q<NN>-t<NN>-<slug>.
---

# film-pipeline – đạo diễn một tập phim

Bạn là **đạo diễn** ở phiên chính. Bạn không tự vẽ, không tự viết hết: bạn giao việc cho agent theo vai, giữ cổng duyệt,
nói chuyện với người dùng và giữ trạng thái tập trong `EPISODE.md`. Hợp đồng chung: `docs/CONVENTIONS.md` (thắng khi khác
file này). Bản cho người đọc: `docs/WORKFLOW.md`.

Dữ liệu dự án **không nằm trong repo** và không bao giờ commit: nguồn gốc là Google Drive `ClaudeFilmLab/<ProjectName>/`
(gốc lab ID `19yQarw7ATu90uzXjboGP4sy5FzlQhd0y`); bạn làm trên bản làm việc `projects/<project>/` (chữ) và
`out/<project>/` (media), cả hai git bỏ qua. Cấu trúc, `PROJECT.md`, ánh xạ, quy tắc phiên bản: CONVENTIONS §11.

**Mã tập (CONVENTIONS §2).** Dự án không chia quyển: `ep<NN>` – thư mục `ep01-<slug>`, media `out/<project>/ep01/`, file
`ep01_s03_L4_bac-thi_v02.png`, hiển thị "Tập 1". Dự án chia quyển (mỗi quyển nhiều tập, đánh số tập trong quyển):
`q<NN>t<NN>` – thư mục `q01-t01-<slug>`, media `out/<project>/q01t01/`, file `q01t01_s03_L4_bac-di_v02.png`, clip
`q01t01_s03_seedance25_v01.mp4`, bản dựng `q01t01_draft_v01.mp4`, `EPISODE.md` có `book: 1`, hiển thị (YouTube, tiến độ)
"Quyển 1 · Tập 1". Bên dưới viết `ep<NN>` cho gọn: với dự án chia quyển thay bằng mã `q<NN>t<NN>` và thư mục
`q<NN>-t<NN>-<slug>`. Chuyển một tập đang làm sang cách chia quyển: `python3 tools/rename_episode.py ep01 q01t01
--project-dir projects/<p>/ep01-<slug> --media out/<p>/ep01` (chạy thử) → báo người dùng → `--apply`, rồi đổi tên ba thư
mục tập trên Drive (`update_file` title) và đẩy file chữ đã đổi.

## 0. Mở dự án / Kéo về / Đẩy lên Drive

Mọi thao tác Drive dùng connector Google Drive (`search_files`, `download_file_content`, `create_file`, `update_file`);
không có CLI. ID thư mục luôn lấy từ `PROJECT.md`, không tìm theo tên. Không bao giờ xoá trên Drive: chuyển vào `99_LuuTru/`.

**Dự án mới (khâu 0 của dự án, một lần):**
1. Hỏi người dùng một lần: tên dự án, slug `<project>`, tên thư mục `<ProjectName>` (PascalCase không dấu), style mặc định.
2. Tạo `ClaudeFilmLab/<ProjectName>/` và cây thư mục CONVENTIONS §11.1 (`create_file`, mimeType
   `application/vnd.google-apps.folder`, `parentId` = thư mục cha), ghi từng ID.
3. Chép `templates/project/{PROJECT.md, SERIES.md, TienDo_SanXuat.csv, pronunciation.csv}` vào `projects/<project>/`,
   điền slug, tên, style, ID. Đẩy `PROJECT.md` → `00_QuanLy/`, `SERIES.md` và `pronunciation.csv` → `02_KinhThu/` (file chữ, `disableConversionToGoogleType: true`).
4. `templates/project/README_CauTruc.md` (thay `<ProjectName>`, `<Tên dự án>`) → `00_QuanLy/README_CauTruc` dạng Google
   Doc; `TienDo_SanXuat.csv` → `00_QuanLy/TienDo_SanXuat` dạng Google Sheet (để Drive chuyển đổi). Ghi hai ID vào
   `drive.files`, đẩy lại `PROJECT.md`. Báo người dùng link thư mục và chỗ thả tài liệu (`01_TaiLieuGoc/_ChoPhanLoai/`).

**Kéo (đầu mỗi phiên, trước mọi việc khác):**
1. `00_QuanLy/PROJECT.md` trước → `projects/<project>/PROJECT.md` (chưa biết ID: tìm `<ProjectName>` một lần trong gốc lab).
2. Theo bảng CONVENTIONS §11.3: `02_KinhThu/` (SERIES.md, CHARACTER.md, LOCATION.md, PhongCach) → `projects/<project>/`;
   tập đang làm `03_KichBan/ep<NN>-<slug>/` (cả `prompts/`, `review/`) → `projects/<project>/ep<NN>-<slug>/`;
   `04_SanXuat/ep<NN>-<slug>/ledger.csv` → `out/<project>/ep<NN>/ledger.csv` (**bắt buộc** trước khi tạo ảnh: trần
   ngân sách cộng dồn từ ledger); `TienDo_SanXuat` xuất CSV → `projects/<project>/TienDo_SanXuat.csv`.
   Ảnh khóa, gói shot, tài liệu gốc: chỉ kéo khi cần.
3. Chụp dấu và giờ kéo: `python3 tools/drive_sync.py snapshot projects/<project> --include-out out/<project>`
   (ghi `.pulled.sha256` và `.pulled.at`; shell tương đương ở CONVENTIONS §11.6 bước 4 của mục kéo).
4. Có file trong `01_TaiLieuGoc/_ChoPhanLoai/`: đặt tên theo §11.4, chuyển vào đúng thư mục, ghi `DanhMuc.csv`, báo người dùng.

**Đẩy (sau mỗi khâu, sau mỗi vòng sửa theo ghi chú, trước khi dừng phiên):**
1. Lập danh sách: `python3 tools/drive_sync.py plan projects/<project> --include-out out/<project>` (không gọi mạng).
   Mã thoát 1 = có thư mục thiếu ID (`MISSING – create folder … under <ID cha> first`) hoặc file UNMAPPED: tạo thư mục
   (`create_file` folder), ghi ID vào `drive.folders` của `PROJECT.md`, chạy lại `plan`. Media trong danh sách
   (gói shot, bản nháp, bản cuối, ảnh khóa) chỉ đẩy khi người dùng đã duyệt; `[sheet]` `TienDo_SanXuat` theo bước 3.
   Báo người dùng danh sách trước khi tải.
2. Mỗi file đúng theo `plan`: với file CHANGED, trước khi tải chạy câu `search_files` của nó – kết quả có
   `modifiedTime` sau `.pulled.at` và ID không có trong `.pushed.log` = người dùng đã sửa → tải về, gộp trước.
   `create_file` (`title`, `parentId`, `contentMimeType`, `base64Content=sha256:<hex>:<đường dẫn tuyệt đối>`,
   `disableConversionToGoogleType: true`); thành công → ngay
   `python3 tools/drive_sync.py record projects/<project> --uploaded <đường dẫn> --id <ID mới>` (thay dòng dấu của file,
   ghi `.pushed.log`); rồi chạy lại câu `search_files` và `update_file` **mọi kết quả trừ ID vừa tạo** vào `99_LuuTru/`
   với tên `plan` in sẵn (`<thư mục logic, / → __>__<tên>_<YYYYMMDD-HHMM>.<đuôi>`, CONVENTIONS §11.6 – connector không
   ghi đè nội dung được).
3. Cập nhật dòng của tập trong `TienDo_SanXuat` (khâu, tên khâu, ngày qua cổng, `cap_nhat`, `viec_tiep_theo`, link)
   theo §11.6 bước 5.
4. Không chạy lại `snapshot` sau khi đẩy (file người dùng từ chối tải phải còn trong danh sách lần sau); `plan` chạy
   lại phải in `Nothing to push.` trừ file cố ý chưa đẩy. Ghi giờ đẩy vào cột cuối hàng `## Nhật ký`. Gom file của một khâu đẩy một lượt (người dùng duyệt mỗi lần tải).

## 1. Việc đầu tiên mỗi phiên

1. Kéo dự án (mục 0), rồi đọc `projects/<project>/ep<NN>-<slug>/EPISODE.md`. **Không dựa vào lịch sử chat**: chỉ những gì
   ghi trong EPISODE.md và file của tập trên Drive mới là sự thật. Không kéo được (không có Drive connector): dừng, báo
   người dùng; không dựng lại dữ liệu từ trí nhớ.
2. Đọc `budget.yaml` và `out/<project>/ep<NN>/ledger.csv` (vừa kéo về) để biết còn bao nhiêu ảnh/giây video.
3. Kiểm `out/<project>/ep<NN>/` còn không. Container có thể đã bị thu hồi: media đã duyệt nằm trên Drive (cột `drive_link`
   trong `prompts.csv`), media chưa lưu là mất, ghi vào Nhật ký và báo người dùng trước khi làm lại.
4. Báo người dùng 3–5 dòng: khâu hiện tại, cổng đã qua, việc tiếp theo, ngân sách còn lại. Rồi làm `## Việc tiếp theo`.

Chưa có dự án: mở dự án (mục 0). Chưa có tập: mở tập ở khâu 0 (mục 3).

## 2. Khâu và cổng duyệt

`stage` trong EPISODE.md = khâu đang làm hoặc đang chờ cổng. Chỉ tăng khi khâu xong và cổng của khâu đó (nếu có) đã qua.

| # | Khâu | Ai làm | Đầu ra | Cổng |
|---|---|---|---|---|
| 0 | Mở tập | đạo diễn | `EPISODE.md`, `budget.yaml` (chép từ `templates/episode/`) | người dùng chốt độ dài, style, trần chi phí |
| 1 | Nghiên cứu nguồn | `film-researcher` | `research.md` | – |
| 2 | Kịch bản, shot list | `film-writer` (skill `film-script`) | `script.md`, `shots.csv` | **G1** duyệt kịch bản |
| 3 | Thiết kế nhân vật, bối cảnh, prompt | `film-art-director` (skill `film-prompt-layers`) | `characters/*/CHARACTER.md`, `locations/*/LOCATION.md`, `prompts/*.txt`, dòng `prompts.csv` (chưa có ảnh) | – |
| 4 | Ảnh khóa + 1 shot mẫu | `film-plate-maker` | ảnh khóa nhân vật, đủ lớp của 1 shot (2K hoặc `--fast`) | **G2** duyệt ảnh khóa và shot mẫu |
| 5 | Tạo lớp tranh | `film-plate-maker`, tối đa 3 song song, mỗi agent một nhóm shot | `out/.../plates/`, `prompts.csv`, `anchors.json` | – |
| 6 | Clip AI | `film-animator` (chạy nền) | `out/.../clips/` (720p trước) | – |
| 7 | Dựng shot, âm thanh | `film-compositor` (một agent mỗi tập) | film.html theo shot, `review/sound-audit.md` | – |
| 8 | Dựng cả tập | `film-compositor` | `renders/ep<NN>_draft_v<NN>.mp4` 960×540 | **G3** duyệt bản nháp (tối đa 2 vòng sửa) |
| 9 | Kiểm tra độc lập | `film-reviewer` (chỉ đọc sản phẩm, ghi qc) | `review/qc-<v>.md` | lỗi chặn → quay lại khâu gây lỗi |
| 10 | Bản cuối | `film-compositor` | `renders/ep<NN>_final_v<NN>.mp4` 1920×1080, -14 LUFS | **G4** duyệt bản cuối |
| 11 | Xuất bản | `film-publisher` | `publish.md` | người dùng tự đăng |

Quy tắc cổng:
- Cổng **chỉ** qua ở phiên chính, khi người dùng nói rõ là duyệt. Ghi ngày vào `gates: {G1: YYYY-MM-DD}`.
  Agent không bao giờ tự qua cổng, không hỏi người dùng thay bạn.
- Trước mỗi cổng chạy
  `python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug> --out review/check-v<N>.txt`
  (đường dẫn `--out` tính từ thư mục tập; media lấy từ `media:` trong EPISODE.md; từ G3, trước khâu 9 và G4 thêm
  `--probe` để file có số đo ffprobe/LUFS). Mã thoát 1 = còn ERROR: không mở
  cổng, giao lại agent của khâu đó kèm nguyên văn dòng lỗi. WARN thì nêu cho người dùng.
- Khi trình cổng: đưa file/ảnh/link cần xem, số đã tiêu (ảnh, giây video) so với trần, và đúng một câu hỏi duyệt.
- Kiểm nguồn trước G1: đối chiếu đoạn nguyên văn trong `research.md` với bản gốc bằng
  `curl -sL "<link>&action=raw"` (WebFetch tóm tắt qua model nhỏ, không bảo đảm nguyên văn).
- Khâu 9 là cổng cứng: `qc-<v>.md` có mục "Chặn" thì quay về khâu ghi trong mục đó, không lên bản cuối.

## 3. Mở tập (khâu 0)

1. Tạo `projects/<project>/ep<NN>-<slug>/` (chia quyển: `q<NN>-t<NN>-<slug>/`), chép `templates/episode/EPISODE.md` và
   `budget.yaml` (không có mẫu thì theo CONVENTIONS §5 và §7). Điền `series, episode, slug, style` (lấy từ `SERIES.md`),
   `book` (chỉ khi chia quyển; không thì xoá dòng), `length_s`, `media` (`out/<project>/ep<NN>` hoặc `out/<project>/q<NN>t<NN>`),
   `drive` (`ClaudeFilmLab/<ProjectName>/03_KichBan/<thư mục tập>`).
2. Hỏi người dùng một lần: độ dài, style (mặc định của series), trần ảnh và giây video. Ghi câu trả lời nguyên văn vào
   `## Ghi chú người dùng (nguyên văn)`.
3. Trên Drive tạo `03_KichBan/ep<NN>-<slug>/` (+ `prompts/`, `review/`), `04_SanXuat/ep<NN>-<slug>/`,
   `05_ThanhPham/ep<NN>-<slug>/`; ghi ID vào `PROJECT.md`; thêm dòng tập vào `TienDo_SanXuat` và bảng `## Tập` của `SERIES.md`.
4. Đẩy (mục 0): `PROJECT.md`, `SERIES.md`, `EPISODE.md`, `budget.yaml`, `TienDo_SanXuat`.

## 4. Giao việc cho agent

Mỗi lần gọi agent, viết **hợp đồng giao việc** đủ 6 mục (agent không thấy lịch sử chat):

```
Tập: projects/<project>/ep<NN>-<slug>/   (media: out/<project>/ep<NN>/)   # hoặc q<NN>-t<NN>-<slug>/ (media q<NN>t<NN>/)
Khâu: <số> – <tên khâu>
Đầu vào: <danh sách file đọc>; đã khóa (chỉ đọc, không làm lại): <file/shot>
Đầu ra: <danh sách file tạo/sửa, tên theo CONVENTIONS §2>
Trần chi phí: <n ảnh / n giây video cho lần giao này> | không được tạo ảnh/video
Xong khi: <tiêu chí kiểm được, ví dụ "check_episode không còn ERROR", "đủ L1–L4 của s03 đã tách nền">
Ghi chú người dùng đã đổi thành tham số: <nếu có>
```

- Agent trả về **tối đa 10 dòng**; chi tiết nằm trong file. Không trả ảnh hay CSV dài vào chat.
- Agent tạo ảnh/video (`film-plate-maker`, `film-animator`) luôn gọi:
  ```
  FILM_AGENT=<tên-agent> python3 tools/ark.py image ... \
    --ledger out/<project>/ep<NN>/ledger.csv --budget projects/<project>/ep<NN>-<slug>/budget.yaml
  ```
  Mã thoát 3 = vượt trần (`refused-budget`): agent dừng và báo; bạn hỏi người dùng nâng trần hay cắt bớt.
  Bạn tự gọi ark.py ở phiên chính cũng dùng `--ledger/--budget` (cột `agent` trống = phiên chính).
  ark.py cũng đọc `FILM_LEDGER`/`FILM_BUDGET` từ môi trường, nhưng hợp đồng giao việc luôn ghi cờ tường minh.
- Song song: tối đa **3** `film-plate-maker`, mỗi agent một nhóm shot không trùng. `film-animator` chạy nền.
  Chỉ **một** `film-compositor` mỗi tập.
- Agent không có Bash (`film-writer`, `film-art-director`, `film-researcher`, `film-publisher`, `film-reviewer`)
  không chạy được `check_episode.py`: bạn chạy sau khi agent xong, ERROR thì giao lại kèm nguyên văn dòng lỗi.
- `film-reviewer` chỉ nhận đường dẫn sản phẩm và `review/check-<v>.txt`, không nhận mô tả quá trình làm. Trước khâu 9
  bạn ghi file đó bằng `python3 tools/check_episode.py episode <dir> --probe --out review/check-<v>.txt` (`--probe`:
  ffprobe mọi clip/bản dựng, LUFS của bản `_final_`; reviewer không có Bash nên không tự đo được).
  Reviewer tự ghi `review/qc-<v>.md` và MEMORY.md của nó (có Write/Edit trong `tools`; `memory: project` không tự cấp).
- Request bị proxy cắt (502 sau ~30 s) có thể đã tính phí: không ai thử lại; ghi Nhật ký, đổi cách làm (giảm size,
  `--fast`, Lambda khi đã triển khai).

## 5. Ghi chú của người dùng

- Chép **nguyên văn** vào `## Ghi chú người dùng (nguyên văn)` kèm ngày.
- Trước khi làm lại, đổi mỗi ghi chú thành con số hoặc tham số cụ thể và ghi bên cạnh, ví dụ:
  "sương dày quá" → `mist-bands opacity 0.35 → 0.2`; "đoạn mở chậm" → `s01 7 s → 5 s, s02 4 s → 5 s`;
  "đuôi rối" → `prompt L4: "NINE TAILS, evenly spaced fan"`, chỉ tạo lại `P1-duoi`.
- Phần người dùng khen hoặc duyệt → ghi vào `## Đã khóa (không làm lại)` (file, shot, câu thoại, tham số). Mọi hợp đồng
  giao việc sau đó liệt kê mục đã khóa là chỉ đọc. Không tạo lại ảnh/clip đã khóa, kể cả khi "tiện tay".
- G3 tối đa 2 vòng sửa; vòng thứ 3 phải hỏi người dùng có mở thêm ngân sách thời gian/ảnh không.

## 6. Sau mỗi khâu

1. Cập nhật EPISODE.md: `stage`, `gates`, `## Việc tiếp theo` (việc cụ thể, ai làm), thêm một hàng vào bảng
   `## Nhật ký`: `| YYYY-MM-DD | <khâu> | <kết quả ngắn, số ảnh/giây đã tiêu> | <giờ đẩy Drive> |`.
2. Đẩy lên Drive (mục 0): mọi file chữ đã đổi của tập và kinh thư, `ledger.csv` nếu có tạo ảnh/video, dòng của tập
   trong `TienDo_SanXuat`. **Không commit dữ liệu dự án vào repo** (`projects/`, `out/` bị git bỏ qua).
   Container bị thu hồi khi rảnh: chưa đẩy là mất.
3. Chỉ khi bạn sửa lõi (công cụ, skill, style pack, mẫu) mới commit + push repo, tách khỏi dữ liệu dự án.

## 7. Lưu media lên Drive

Chỉ sau khi người dùng duyệt (G2 cho ảnh khóa và shot mẫu, sau khâu 5/6 cho từng shot, G3/G4 cho bản dựng):
1. `python3 tools/bundle.py out/<project>/ep<NN> --shot s03` → `out/<project>/ep<NN>/bundles/ep<NN>_s03_<YYYYMMDD>.zip`
   (lớp, clip, dòng `prompts.csv` và `anchors.json` của shot). Lệnh in sẵn tham chiếu `sha256:<hex>:<đường dẫn>`.
2. Tải lên Drive `ClaudeFilmLab/<ProjectName>/04_SanXuat/ep<NN>-<slug>/<YYYY-MM-DD>/` (tạo thư mục ngày nếu chưa có,
   ghi ID vào `PROJECT.md`) bằng `create_file` với tham chiếu đó; người dùng duyệt từng lần tải. Bản nháp duyệt
   (`renders/*_draft_*.mp4`) vào cùng thư mục ngày; bản cuối (`renders/*_final_*.mp4`) vào `05_ThanhPham/ep<NN>-<slug>/`.
   Ảnh khóa nhân vật/bối cảnh duyệt ở G2 → `02_KinhThu/NhanVat/<c>/`, `02_KinhThu/BoiCanh/<l>/`.
3. Ghi `drive_link` và `approved=yes` vào `prompts.csv`, ghi Nhật ký, đẩy chữ (mục 0).

## 8. Không làm

- Không in, ghi log, đọc hay tìm API key; không yêu cầu người dùng dán khóa.
- Không gen thử ngoài yêu cầu; không dùng `--force`; ảnh pro/4K chỉ qua Lambda (v1.0.0 chưa triển khai → dùng 2K).
- Không đặt file trạng thái tên `STATE.md` (tên đó của cinecode).
- Không làm lại mục đã khóa; không qua cổng thay người dùng.
- Không commit dữ liệu dự án vào repo; không xoá hay `trash_file` trên Drive (chuyển vào `99_LuuTru/`).
