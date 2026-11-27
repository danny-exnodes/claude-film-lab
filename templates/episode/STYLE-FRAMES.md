# Style frame – <Tên tập>

<!-- Mẫu (khâu 3b, tập method blender/code; .claude/skills/film-pipeline/SKILL.md mục 2.3, docs/CONVENTIONS.md §5).
     Đạo diễn chép vào projects/<project>/<thư mục tập>/STYLE-FRAMES.md. Làm SAU cổng thiết kế sinh vật (3a), TRƯỚC khi
     dựng hàng loạt: 5–8 khung hoàn chỉnh, mỗi chương một khung (bối cảnh dựng nhanh + sinh vật proxy theo concept đã
     duyệt + nâng chất + grade). Chủ dự án duyệt và chọn khung chuẩn; mọi shot sau đó đối chiếu khung chuẩn.
     Khung là thứ khâu 5 làm lại được: nâng chất (Qwen-Edit) chỉ khi tập dùng cùng đường đó cho shot thật.
     Khung hoàn chỉnh (đã grade): out/<project>/<id>/styleframes/final/<id>_sf<NN>_<chủ-đề>_v<NN>.png; render có pass
     ở styleframes/render/sf<NN>/, bản nâng chất ở styleframes/edit/. Contact sheet (chỉ final/), bảng màu và bản sao
     khung chuẩn: review/styleframes/ của thư mục tập (lên Drive cùng chữ của tập):
       python3 tools/styleframes.py sheet out/<project>/<id>/styleframes/final --out review/styleframes/<id>_contact_v01.png --palette-out review/styleframes/<id>_palette_v01.png
     status.py --gate G2 cần bảng "Khung chuẩn đã duyệt" đủ dòng; check_episode.py WARN từ khâu 4 (khâu 3a/3b ghi stage: 3). -->

## Khung

<!-- Một dòng mỗi khung (5–8, mỗi chương một khung). File: khung hoàn chỉnh trong final/. Cách làm: lệnh/bước đã chạy
     (blender.py render --frames N --passes depth mask, toon.py still, comfy.py run qwen-edit, grade.py), đủ để làm lại.
     Bảng "Khung chuẩn đã duyệt" chỉ nhận id hoặc file của bảng này (hoặc file trong review/styleframes/). -->

| id | Chương | Shot | File | Cách làm | Ghi chú |
|---|---|---|---|---|---|

## Bảng màu

<!-- Dòng palette mà styleframes.py sheet in ra, rồi tên gọi từng màu theo vai (nền xa, sương, đá, nước, sinh vật,
     điểm nhấn). Ghi cả số đo luma/contrast/saturation của khung chuẩn. -->

- Contact sheet: `review/styleframes/<id>_contact_v01.png` · bảng màu: `review/styleframes/<id>_palette_v01.png`
- Palette:
- Vai màu:

## Quy tắc đối chiếu

<!-- Điều mọi shot sau phải giữ, viết thành số hoặc câu kiểm được: độ nhạt (luma), độ tương phản sinh vật/nền, độ bão
     hoà, mật độ sương, nét, hướng sáng. Đo một khung của shot với khung chuẩn:
       python3 tools/styleframes.py compare review/styleframes/<khung chuẩn>.png <khung của shot>.png
     DRIFT = lệch quá ngưỡng: xem lại bằng mắt, sửa look/grade trước khi render tiếp. -->

-

## Khung chuẩn đã duyệt

<!-- Đạo diễn ghi SAU khi chủ dự án chọn (cổng 3b, trong hội thoại). Vai: `không khí` (một khung cho không khí cả tập)
     và mỗi sinh vật chính một dòng (slug của bảng "## Sinh vật của tập" trong EPISODE.md). Khung: id hoặc file (bản
     sao trong review/styleframes/). Ngày bắt đầu bằng YYYY-MM-DD (chưa duyệt thì chưa ghi dòng). Lời chủ dự án chép nguyên văn. Thêm một dòng vào
     "## Đã khóa (không làm lại)" của EPISODE.md. -->

| Vai | Khung | Ngày | Lời chủ dự án (nguyên văn) |
|---|---|---|---|
