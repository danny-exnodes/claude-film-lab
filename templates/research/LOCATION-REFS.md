# <Tên bối cảnh> (<chữ Hán>) – tư liệu bối cảnh (`E-<slug>`)

<!-- Mẫu cho khâu 3a, bối cảnh của tập blender (và code/layers khi đạo diễn giao). film-iconographer chép vào
     projects/<project>/locations/<slug>/LOCATION-REFS.md (Drive 02_KinhThu/BoiCanh/<slug>/), điền theo
     RESEARCH-BRIEF.md. Ảnh tải bằng tools/refs_fetch.py vào out/<project>/assets/refs/locations/<slug>/ (git bỏ qua,
     không lên Drive), tên <slug>_<loại>_<NN>_<mô-tả>.jpg, loại = old (tranh sơn thuỷ, sách cổ) | vn (mỹ thuật, kiến
     trúc Việt) | real (địa hình thật). Giấy phép, tác giả, link lấy từ _credits.jsonl. 10–25 ảnh mỗi bối cảnh.
     Asset CC0 dựng 3D (HDRI, texture PBR, model scan) KHÔNG tải ở đây: đề xuất id ở mục 5, đạo diễn xem
     tools/assets.py plan và hỏi người dùng trước khi tải. -->

## 1. Kinh văn

> <nguyên văn chữ Hán: núi, sông, khoáng vật, cây cỏ, thần>

Nghĩa sát: … · Link: … (oldid …, truy cập YYYY-MM-DD). Chú giải khác (nếu có): …

## 2. Shot dùng bối cảnh và giờ

<!-- Từ shots.csv (cột layers có E-<slug>): shot, giờ trong ngày, cỡ cảnh, máy quay, cần thấy gì. -->

| Shot | Giờ | Cần gì (khối, nước, sương, ánh sáng, độ cao máy) |
|---|---|---|
| s<NN> | | |

## 3. Tranh và ảnh (bảng ảnh, đọc tranh)

| File | Loại | Nội dung / dùng cho shot nào | Tác giả · niên đại · nơi giữ | Giấy phép | Link |
|---|---|---|---|---|---|
| `<slug>_old_01_<mô-tả>.jpg` | tranh sơn thuỷ | | | | |
| `<slug>_real_01_<mô-tả>.jpg` | ảnh thật | | | | |

Đọc tranh (bố cục tam viễn cao/sâu/bằng, nét núi – thuẫn pháp, mây và khoảng trống, tầng xa gần):
- …

## 4. Địa hình thật tương tự

<!-- Nơi có dạng tương tự (karst, núi đá đỏ, núi lửa, cửa sông, biển mây, vách đá ven biển…): tên, vì sao giống,
     ảnh CC ở mục 3. Kiến trúc tế lễ cổ nếu có. -->

- …

## 5. Hướng dẫn dựng Blender

<!-- Khối địa hình (preset mountains/rocks/water/ground hay model scan), đá, nước, sương (mist, mist_range), cây; ánh
     sáng theo giờ của từng shot. HDRI và texture: id CC0 đã có trong out/<project>/assets/ASSETS_MANIFEST.csv, hoặc
     đề xuất id mới (Poly Haven / ambientCG) để đạo diễn lập kế hoạch tải bằng tools/assets.py. -->

| Giờ | Shot | Mặt trời `[độ cao, phương vị]` | HDRI (`world.hdri`) | Texture (`materials`) | Ghi chú |
|---|---|---|---|---|---|
| | | | | | |

- Khối và tỉ lệ (m):
- Nước, sương:
- Asset CC0 cần tải thêm (id, nguồn, độ phân giải, dùng cho shot nào):

## 6. Grade gợi ý

<!-- Theo style của tập (vd. thuỷ mặc: giảm bão hoà, nâng đen về mực, giấy ấm ở vùng sáng). -->

- …

## 7. Thiếu

- …
