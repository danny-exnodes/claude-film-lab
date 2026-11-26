---
# Kinh thư của dự án – docs/CONVENTIONS.md §4. Chép vào projects/<project>/SERIES.md, điền, đẩy lên
# ClaudeFilmLab/<ProjectName>/02_KinhThu/SERIES.md. Mọi tập đọc file này trước khi viết.
series: <project>                # = project trong PROJECT.md = tên thư mục projects/<project>/
title: <Tên dự án>
style: <style-id>                # style mặc định của mọi tập, styles/<style-id>/
audience: "<ai xem, độ tuổi, nền tảng, khung hình>"
language: vi
# method: layers                # (tuỳ chọn, chỉ để ghi nhớ) cách dựng mặc định của dự án: layers | seedance | code. Công cụ chỉ đọc
                                 # method: trong EPISODE.md của từng tập (docs/CONVENTIONS.md §5)
format: {width: 1920, height: 1080, fps: 24}
owner_refs: {source: "", required: false}   # tư liệu của chủ dự án (vd. "Sách tranh SHK (Lương Siêu / Sam Trạch / An Lạc)").
                                 # required: true → khâu 1 của mỗi tập: liệt kê mọi sinh vật/thần (bảng `## Sinh vật của
                                 # tập` của EPISODE.md), xin ảnh chụp trang sách TRƯỚC vòng nghiên cứu bổ sung; status.py in
                                 # OWNER_REFS, G1/G2 cần ảnh (hoặc "không") cho mọi sinh vật. Ảnh sách có bản quyền: chỉ là
                                 # chuẩn tinh thần/chất lượng, thiết kế của lab là bản riêng (docs/CONVENTIONS.md §4).
---

# <Tên dự án> (<tên gốc nếu có>)

<!-- Một đoạn: mỗi tập dài bao nhiêu, kể về cái gì, dựng từ nguồn nào. Phong cách: styles/<style-id>/.
     Media: out/<project>/<ep<NN>|q<NN>t<NN>>/. -->

## Khán giả và lời hứa của series

<!-- Người xem là ai, cần biết trước gì; mỗi tập để lại điều gì. Mức trung thành với nguồn: điều nguồn nói thì vẽ
     đúng, điều nguồn không nói là diễn giải và phải ghi rõ trong CHARACTER.md/LOCATION.md (cột nguồn/diễn giải).
     Giới hạn nội dung (vd. không máu me). -->

## Giọng kể

<!-- Phần cộng thêm cho mục "Giọng kể và nhịp" của styles/<style-id>/STYLE.md: ai kể, xưng hô, cách đọc câu
     nguyên văn và tên riêng, điều không nói. -->

## Quy ước nguồn và tên

<!-- Văn bản gốc (link, bản nào), bản đối chiếu; cách trích nguyên văn; cách đọc tên (căn cứ); slug không dấu.
     Tài liệu gốc người dùng cung cấp nằm ở 01_TaiLieuGoc/ trên Drive, đặt tên theo docs/CONVENTIONS.md §11.4. -->

- Mỗi nhân vật: `characters/<slug>/CHARACTER.md`; mỗi bối cảnh: `locations/<slug>/LOCATION.md`
  (trên Drive: `02_KinhThu/NhanVat/<slug>/`, `02_KinhThu/BoiCanh/<slug>/`).

## Tư liệu của chủ dự án

<!-- owner_refs ở khối YAML: tên tư liệu (sách tranh, bản nào), chủ dự án đặt chuẩn gì ("ít nhất phải như này hoặc hơn").
     Ảnh chụp trang nằm ở out/<project>/assets/refs/<slug>/book/ (không lên git, không lên Drive), nguồn từng ảnh ghi trong
     out/<project>/assets/refs/<slug>/REFS.md. Chỉ để tham khảo tinh thần và chất lượng: không chép, không đưa vào phim. -->

## Nhân vật và bối cảnh

| Slug | Tên | Loại | Nguồn | Tập |
|---|---|---|---|---|

## Tập

| Tập | Thư mục | Chủ đề |
|---|---|---|

## Quy ước riêng của series

<!-- Quy tắc áp cho mọi tập: một tập mấy nhân vật chính, màu dành riêng, nhân vật dễ nhầm cần phân biệt... -->
