---
# Mẫu trạng thái tập – docs/CONVENTIONS.md §5. Chép vào projects/<project>/ep<NN>-<slug>/EPISODE.md và điền.
# KHÔNG đặt tên STATE.md (tên đó thuộc cinecode).
series: <series>             # slug series, trùng tên thư mục projects/<project>/
episode: 1                   # số tập (số nguyên)
slug: <slug>                 # slug tập, thư mục là ep<NN>-<slug>
style: <style-id>            # thường bằng style trong SERIES.md; thư mục styles/<style-id>/
length_s: 60                 # thời lượng đích (giây); shot cuối trong shots.csv kết thúc đúng số này
stage: 0                     # khâu hiện tại 0..11 theo docs/WORKFLOW.md
gates: {G1: null, G2: null, G3: null, G4: null}   # ngày người dùng duyệt YYYY-MM-DD, hoặc null
media: out/<project>/ep01     # thư mục media (git bỏ qua)
drive: "AI Film Lab/<series>/ep01"
---

# <Tên tập>

## Ghi chú người dùng (nguyên văn)

<!-- Chép nguyên văn yêu cầu, góp ý, quyết định của người dùng; mỗi mục có ngày. Không tóm tắt, không sửa chữ. -->

## Đã khóa (không làm lại)

<!-- Thứ đã duyệt và không được tạo lại/sửa: ảnh khóa, lớp, kịch bản, giọng đọc... mỗi dòng: thứ gì, file/link, ngày,
     cổng nào. -->

## Việc tiếp theo

<!-- Danh sách việc cụ thể cho khâu hiện tại, việc đầu tiên ở trên cùng. -->

## Nhật ký

<!-- Mỗi khâu một dòng: ngày | khâu | kết quả | commit. -->

| Ngày | Khâu | Kết quả | Commit |
|---|---|---|---|
