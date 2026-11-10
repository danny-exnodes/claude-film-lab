---
# Trạng thái tập – docs/CONVENTIONS.md §5. Không đặt tên STATE.md.
series: son-hai-kinh
episode: 1
slug: bac-thi
style: thuy-mac
length_s: 60
stage: 2
gates: {G1: null, G2: null, G3: null, G4: null}
media: out/son-hai-kinh/ep01
drive: "AI Film Lab/son-hai-kinh/ep01"
---

# Bác Thi (猼訑) · Sơn Hải Kinh tập 1 (bản chạy thử 60 s)

## Ghi chú người dùng (nguyên văn)

<!-- Chưa có ghi chú trực tiếp cho tập này. Độ dài 60 s lấy từ issue #6 ("Chạy thử trọn quy trình với
     son-hai-kinh/ep01-bac-thi bản 60 giây"); chờ người dùng xác nhận độ dài, style, trần chi phí. -->

## Đã khóa (không làm lại)

<!-- Chưa có. -->

## Việc tiếp theo

1. Đạo diễn: xác nhận với người dùng các điểm của khâu 0 (độ dài 60 s, style `thuy-mac`, trần trong `budget.yaml`).
2. Đạo diễn: kiểm đoạn nguyên văn trong `research.md` bằng `curl` bản thô (link trong file).
3. Đạo diễn: chạy `python3 tools/check_episode.py episode series/son-hai-kinh/ep01-bac-thi --out review/check-v1.txt`,
   rồi trình **G1** (kịch bản `script.md` + `shots.csv`). Câu hỏi duyệt đi kèm: câu luận đề `[00:44]`.
4. Sau G1: khâu 3, giao `film-art-director` (CHARACTER.md cho `bac-thi`, `nguoi-ganh-muoi`; LOCATION.md cho `nui-co`;
   prompt lớp cho 10 shot).

## Nhật ký

| Ngày | Khâu | Kết quả | Commit |
|---|---|---|---|
| 2026-11-10 | 0 | Mở tập chạy thử 60 s, budget.yaml chép từ templates/episode (40 ảnh, 30 s video) | (chưa commit) |
| 2026-11-10 | 1 | research.md: nguyên văn 基山 (南山經) từ zh.wikisource oldid 2650929, tên đọc Bác Thi theo chú 愽施二音 | (chưa commit) |
| 2026-11-10 | 2 | Chạy khô skill film-script: script.md 10 câu, shots.csv 10 shot = 60 s; không tạo ảnh/video | (chưa commit) |
