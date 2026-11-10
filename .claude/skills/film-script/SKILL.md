---
name: film-script
description: >-
  Viết kịch bản một tập phim 2.5D nhiều lớp cho AI Film Lab, mọi trường phái: tra nguyên văn chữ Hán (zh.wikisource.org),
  đọc tên theo Hán Việt có căn cứ, dựng cấu trúc và nhịp, viết lời bình tiếng Việt có mốc [mm:ss], xuất script.md và
  shots.csv theo docs/CONVENTIONS.md §6. Dùng ở khâu 2 (trước cổng G1), khi người dùng nói "viết kịch bản", "shot list",
  "lời bình", "sửa kịch bản", "kịch bản tập", hoặc khi film-pipeline giao khâu 2 cho film-writer.
---

# film-script – kịch bản tập phim 2.5D

Đầu ra nằm trong `projects/<project>/ep<NN>-<slug>/` (dự án chia quyển: `projects/<project>/q<NN>-t<NN>-<slug>/`, vd.
`q01-t01-nam-son-kinh/`; CONVENTIONS §2): `research.md` (nếu chưa có), `script.md`, `shots.csv`.
Đây là bản làm việc (git bỏ qua) của thư mục `03_KichBan/ep<NN>-<slug>/` trên Google Drive: mọi file của tập, kể cả
`research.md` và tài liệu gốc, thuộc về dự án trên Drive, không bao giờ vào repo; đạo diễn đẩy lên Drive sau khâu.
Hợp đồng file: `docs/CONVENTIONS.md` §4–§6, §11. Phương pháp viết chung (đi rộng rồi thu hẹp, một cú lật, viết kết trước,
cho thấy thay vì kể, kiểm người xem lần đầu): tham chiếu `/root/.claude/skills/cinecode/references/writing.md` §1–§4, §8,
§14–§15; file này chỉ ghi phần riêng của Film Lab.

## 0. Đọc trước

1. `EPISODE.md` của tập: `length_s`, `style`, ghi chú người dùng, mục đã khóa (không viết lại câu đã khóa).
2. `projects/<project>/SERIES.md`: khán giả, ngôn ngữ, quy ước riêng.
3. `styles/<style>/STYLE.md`, mục **`## Giọng kể và nhịp`**: giọng, tốc độ đọc, motif quen, nhịp cắt. Mục này thắng các
   mặc định dưới đây khi khác. Chưa có mục đó: dùng mặc định ở đây và ghi "chưa có giọng kể của style" vào báo cáo.
4. `characters/` và `locations/` của dự án: nhân vật, bối cảnh đã có thì dùng lại (`reuse_of`), không vẽ lại.
5. Tài liệu gốc của dự án đã kéo về `projects/<project>/sources/` (bản trên Drive: `01_TaiLieuGoc/`, tên theo
   CONVENTIONS §11.4). Cần tài liệu chưa kéo về: ghi tên file vào báo cáo để đạo diễn kéo.

## 1. Nguồn trước, chữ sau

- Nguồn chữ Hán: **zh.wikisource.org** (bản thô: `https://zh.wikisource.org/w/index.php?title=<trang>&action=raw`).
  ctext.org chặn truy cập tự động (trả trang "robot"), chỉ dùng khi người dùng tự mở để đối chiếu.
- Chép **nguyên văn** đoạn dùng vào `research.md`: chữ Hán, link trang, `oldid` (bản sửa), ngày truy cập; nguồn là tài
  liệu gốc của dự án thì ghi tên file trong `01_TaiLieuGoc/` (và trang/tờ). Chú thích
  (ví dụ chú của Quách Phác, trong wikitext là `{{*|...}}`) chép riêng, ghi rõ là chú. Không chép từ trí nhớ; nguồn
  không tới được thì ghi "không truy cập được".
- WebFetch tóm tắt trang qua model nhỏ, có thể đổi chữ: đoạn nguyên văn phải lấy từ bản thô (`action=raw`) hoặc để đạo
  diễn kiểm bằng `curl` trước G1.
- **Tên riêng đọc theo Hán Việt.** Chữ hiếm: theo chú âm cổ và ghi căn cứ, ví dụ 猼訑, chú Quách Phác "愽施二音"
  (愽 = 博 bác, 施 thi) → **Bác Thi**. Ghi bảng: chữ Hán · cách đọc · căn cứ.
- Hình dạng nhân vật bám nguyên văn từng mệnh đề. Chỗ nào là diễn giải (màu lông, dáng đi, bối cảnh, người kể) ghi rõ
  "diễn giải" trong `research.md`.
- Không dùng hình, tên, bố cục của phim hoạt hình thương mại; ảnh tham khảo chỉ để lấy không khí.

## 2. Cấu trúc và nhịp

Chi tiết và cách co giãn theo độ dài: `references/structure.md`. Tóm tắt (chuẩn 3 phút, co theo `length_s`):
- Mở trong khoảng 0–11% độ dài (3 phút: 0–20 s) bằng **một người cụ thể và một câu hỏi**; khung đầu đã chuyển động.
- Giữa: đọc nguồn **theo từng mệnh đề, mỗi mệnh đề một hành động nhìn thấy được** (một shot hoặc một nhịp trong shot).
- **Câu hỏi treo** đặt sớm (trước 25%), **lật** ở khoảng 2/3, **giải** trước khi kết.
- Kết quay về hình mở đầu nhưng đã đổi. **Một motif lặp 3 lần** (lần 3 đổi nghĩa).
- Shot 3–13 s, dài ngắn xen kẽ; hai shot liền nhau không cùng cả cỡ cảnh lẫn chuyển động máy.

## 3. Lời bình

Danh sách lỗi văn máy và cách sửa: `references/writing-tells.md`. Tóm tắt:
- Tiếng Việt, câu ngắn, đọc to được. **Không dùng dấu gạch ngang** (—, –, `--`) trong lời; dùng dấu phẩy, chấm, hai chấm.
- Mỗi câu một mốc `[mm:ss]`; khoảng cách giữa hai mốc liền nhau (và từ mốc cuối tới hết lời) **tối thiểu 3 s**.
- 2 s đầu để cho hình và tiếng; phim có người kể thì câu đầu vào khoảng `[00:02]`, không trễ hơn `[00:03]`.
- Một **câu luận đề** duy nhất, đánh dấu trong `script.md`.
- Câu đọc nguyên văn nguồn được phép trùng với hình (đó là trích dẫn). Câu không phải trích dẫn qua "phép thử chú thích":
  chỉ gọi tên cái đang thấy thì cắt hoặc đổi.
- Kết có giây riêng không lời: tối thiểu 2 s (phim tới 1 phút), 4 s (tới 3 phút).
- Mật độ mặc định khi STYLE.md chưa định: giọng kể chậm 2,5–3 âm tiết/giây, tổng lời không quá 75% thời lượng.

## 4. Đầu ra

`script.md`:
```
# <Tên tập> · <tên dự án> ep<NN>          (chia quyển: # <Tên tập> · <tên dự án> Quyển 1 · Tập 1)

> Độ dài: <n> s · Style: <id> · Giọng: <theo STYLE.md>
> Luận đề: [mm:ss] · Câu hỏi treo: [mm:ss] · Lật: [mm:ss] · Giải: [mm:ss]
> Motif "<motif>": [mm:ss] · [mm:ss] · [mm:ss]

## Chương 1: <tên>

[00:02] <câu>
[00:06] <câu>

## Ghi chú

> Chương theo giây, khoảng không lời, số âm tiết, đảo thứ tự nguồn, diễn giải, tài sản dùng lại.
```
`tools/check_episode.py` coi **mọi dòng** không phải dòng trống, tiêu đề `#`, trích dẫn `>`, chú thích `<!-- -->`, khối
code hay đường kẻ là lời bình, và lời bình phải mở bằng `[mm:ss]`. Vì vậy thông tin phụ và bảng ghi chú đặt trong `>`.
Mốc tăng dần, nằm trong `length_s`. Không dùng dấu gạch ngang ở bất kỳ đâu trong `script.md` (ngoài lời bình là WARN).

`shots.csv` theo CONVENTIONS §6, header đúng thứ tự:
`shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of`
- `shot` = `s01, s02…`; liên tục từ 0 tới `length_s`; mỗi shot 3–13 s.
- `shot_size` ∈ extreme-wide, wide, medium, close, extreme-close, insert; `camera` ∈ static, push-in, pull-out,
  pan-left, pan-right, tilt-up, tilt-down, drift, handheld (một giá trị).
- `layers`: `L1;L2;L3;L4;P<n>-<bộ-phận>;FX`. `code_motion`: id module của style (`style.yaml` → `motion`).
  `ai_motion` trống = không dùng Seedance; chỉ dùng khi code không làm được (thân thú bước đi, nước chảy thật).
- Trường có dấu phẩy phải đặt trong ngoặc kép. Danh sách tài sản dùng lại thể hiện qua `reuse_of` và mục Ghi chú.

## 5. Tự kiểm trước G1

- Có Bash (phiên chính): `python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug>` → sửa hết ERROR.
- Không có Bash (agent `film-writer`): tự kiểm theo danh sách dưới, báo "chưa chạy check_episode"; đạo diễn chạy.
- [ ] Tổng thời lượng shot = `length_s`; shot 3–13 s; không hai shot liền nhau trùng cả cỡ cảnh và máy.
- [ ] Mỗi câu có mốc, cách nhau ≥ 3 s; không dấu gạch ngang; một câu luận đề; kết có giây không lời.
- [ ] Mỗi mệnh đề nguồn dùng trong phim có trong `research.md` nguyên văn + link; diễn giải được đánh dấu.
- [ ] Motif xuất hiện 3 lần; câu hỏi treo, lật, giải có mốc.
- [ ] Đọc lại theo `references/writing-tells.md`; đọc to và bấm giờ từng câu.
