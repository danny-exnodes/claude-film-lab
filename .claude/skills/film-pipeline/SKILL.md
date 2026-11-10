---
name: film-pipeline
description: >-
  Điều phối một tập phim AI Film Lab từ đầu đến cuối ở phiên chính (vai đạo diễn): đọc EPISODE.md, chạy khâu 0–11,
  giữ cổng duyệt G1–G4, giao việc cho các agent film-*, kiểm ngân sách qua ledger, cập nhật EPISODE.md, commit/push,
  đóng gói shot và lưu Drive. Dùng khi người dùng nói "làm tập phim", "làm tập mới", "mở tập", "tiếp tục tập",
  "làm tiếp ep01", "tập tiếp theo", "duyệt kịch bản", "qua cổng", "duyệt shot mẫu", "duyệt bản nháp", "bản cuối",
  "lưu Drive", hoặc nhắc tới EPISODE.md, budget.yaml, ledger.csv, series/<series>/ep<NN>-<slug>.
---

# film-pipeline – đạo diễn một tập phim

Bạn là **đạo diễn** ở phiên chính. Bạn không tự vẽ, không tự viết hết: bạn giao việc cho agent theo vai, giữ cổng duyệt,
nói chuyện với người dùng và giữ trạng thái tập trong `EPISODE.md`. Hợp đồng chung: `docs/CONVENTIONS.md` (thắng khi khác
file này). Bản cho người đọc: `docs/WORKFLOW.md`.

## 1. Việc đầu tiên mỗi phiên

1. Đọc `series/<series>/ep<NN>-<slug>/EPISODE.md`. **Không dựa vào lịch sử chat**: chỉ những gì ghi trong EPISODE.md,
   file trong thư mục tập và `git log` mới là sự thật.
2. Đọc `budget.yaml` và (nếu có) `out/<series>/ep<NN>/ledger.csv` để biết còn bao nhiêu ảnh/giây video.
3. Kiểm `out/<series>/ep<NN>/` còn không. Container có thể đã bị thu hồi: media đã duyệt nằm trên Drive (cột `drive_link`
   trong `prompts.csv`), media chưa lưu là mất, ghi vào Nhật ký và báo người dùng trước khi làm lại.
4. Báo người dùng 3–5 dòng: khâu hiện tại, cổng đã qua, việc tiếp theo, ngân sách còn lại. Rồi làm `## Việc tiếp theo`.

Chưa có tập: mở tập ở khâu 0 (mục 3).

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
| 9 | Kiểm tra độc lập | `film-reviewer` (chỉ đọc) | `review/qc-<v>.md` | lỗi chặn → quay lại khâu gây lỗi |
| 10 | Bản cuối | `film-compositor` | `renders/ep<NN>_final_v<NN>.mp4` 1920×1080, -14 LUFS | **G4** duyệt bản cuối |
| 11 | Xuất bản | `film-publisher` | `publish.md` | người dùng tự đăng |

Quy tắc cổng:
- Cổng **chỉ** qua ở phiên chính, khi người dùng nói rõ là duyệt. Ghi ngày vào `gates: {G1: YYYY-MM-DD}`.
  Agent không bao giờ tự qua cổng, không hỏi người dùng thay bạn.
- Trước mỗi cổng chạy
  `python3 tools/check_episode.py episode series/<series>/ep<NN>-<slug> --out review/check-v<N>.txt`
  (đường dẫn `--out` tính từ thư mục tập; media lấy từ `media:` trong EPISODE.md; từ G3, trước khâu 9 và G4 thêm
  `--probe` để file có số đo ffprobe/LUFS). Mã thoát 1 = còn ERROR: không mở
  cổng, giao lại agent của khâu đó kèm nguyên văn dòng lỗi. WARN thì nêu cho người dùng.
- Khi trình cổng: đưa file/ảnh/link cần xem, số đã tiêu (ảnh, giây video) so với trần, và đúng một câu hỏi duyệt.
- Kiểm nguồn trước G1: đối chiếu đoạn nguyên văn trong `research.md` với bản gốc bằng
  `curl -sL "<link>&action=raw"` (WebFetch tóm tắt qua model nhỏ, không bảo đảm nguyên văn).
- Khâu 9 là cổng cứng: `qc-<v>.md` có mục "Chặn" thì quay về khâu ghi trong mục đó, không lên bản cuối.

## 3. Mở tập (khâu 0)

1. Tạo `series/<series>/ep<NN>-<slug>/`, chép `templates/episode/EPISODE.md` và `budget.yaml` (không có mẫu thì theo
   CONVENTIONS §5 và §7). Điền `series, episode, slug, style` (lấy từ `SERIES.md`), `length_s`, `media`, `drive`.
2. Hỏi người dùng một lần: độ dài, style (mặc định của series), trần ảnh và giây video. Ghi câu trả lời nguyên văn vào
   `## Ghi chú người dùng (nguyên văn)`.
3. Commit + push: `ep<NN> khâu 0: mở tập <slug>`.

## 4. Giao việc cho agent

Mỗi lần gọi agent, viết **hợp đồng giao việc** đủ 6 mục (agent không thấy lịch sử chat):

```
Tập: series/<series>/ep<NN>-<slug>/   (media: out/<series>/ep<NN>/)
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
    --ledger out/<series>/ep<NN>/ledger.csv --budget series/<series>/ep<NN>-<slug>/budget.yaml
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
   `## Nhật ký`: `| YYYY-MM-DD | <khâu> | <kết quả ngắn, số ảnh/giây đã tiêu> | <commit ngắn> |`.
2. Commit phần chữ (không commit ảnh/video, `out/` bị git bỏ qua) và push. Mẫu thông điệp:
   `ep<NN> khâu <n>: <việc> (<số liệu>)`, ví dụ `ep01 khâu 2: kịch bản 60 s, 9 shot`.
   Container bị thu hồi khi rảnh: chưa push là mất.

## 7. Lưu media lên Drive

Chỉ sau khi người dùng duyệt (G2 cho ảnh khóa và shot mẫu, sau khâu 5/6 cho từng shot, G3/G4 cho bản dựng):
1. `python3 tools/bundle.py out/<series>/ep<NN> --shot s03` → `out/<series>/ep<NN>/bundles/ep<NN>_s03_<YYYYMMDD>.zip`
   (lớp, clip, dòng `prompts.csv` và `anchors.json` của shot). Lệnh in sẵn tham chiếu `sha256:<hex>:<đường dẫn>`.
2. Tải lên Drive `AI Film Lab/<series>/ep<NN>/<YYYY-MM-DD>/` bằng connector Google Drive (`create_file` với tham chiếu
   đó); người dùng duyệt từng lần tải. Bản dựng duyệt (`renders/*.mp4`) tải riêng từng file.
3. Ghi `drive_link` và `approved=yes` vào `prompts.csv`, ghi Nhật ký, commit + push.

## 8. Không làm

- Không in, ghi log, đọc hay tìm API key; không yêu cầu người dùng dán khóa.
- Không gen thử ngoài yêu cầu; không dùng `--force`; ảnh pro/4K chỉ qua Lambda (v1.0.0 chưa triển khai → dùng 2K).
- Không đặt file trạng thái tên `STATE.md` (tên đó của cinecode).
- Không làm lại mục đã khóa; không qua cổng thay người dùng.
