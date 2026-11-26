# Chuẩn nghiên cứu hình tượng – <dự án> <tập> (vòng <N>, <YYYY-MM-DD>)

<!-- Mẫu cho khâu 3a (film-pipeline mục 2.2). Đạo diễn chép vào projects/<project>/<thư mục tập>/RESEARCH-BRIEF.md
     (Drive 03_KichBan/<thư mục tập>/), điền phần <...>, rồi giao film-iconographer (một agent mỗi nhóm sinh vật hoặc
     nhóm bối cảnh, chạy song song được). Agent đọc file này trước mọi việc; hợp đồng giao việc chỉ cần trỏ tới nó và
     ghi phần việc của agent đó. Không chép nội dung sách của chủ dự án vào đây. -->

Mục tiêu: mỗi sinh vật/bối cảnh có tư liệu đủ để (1) viết concept bám nguồn, (2) **sửa concept đã có bằng
Qwen-Image-Edit** (`comfy.py run qwen-edit`), (3) dựng 3D chân thực (`film-3d-artist`).
Mẫu chuẩn đã đạt (nếu có, đọc trước): `projects/<project>/characters/<slug>/ICONOGRAPHY.md`.

## Phân công

| Agent (`FILM_AGENT`) | Mức | Sinh vật / bối cảnh (slug) | Thư mục ảnh |
|---|---|---|---|
| `film-iconographer-<nhóm>` | sâu | `<slug>`, `<slug>` | `out/<project>/assets/refs/<slug>/iconography/` |
| `film-iconographer-<nhóm>` | vừa | `<slug>` | như trên |
| `film-iconographer-boi-canh` | bối cảnh | `<slug>`, `<slug>` | `out/<project>/assets/refs/locations/<slug>/` |

## Bối cảnh dự án (đọc, không sửa)

- Kinh văn + chú giải: `projects/<project>/<thư mục tập>/research.md`; kịch bản `script.md`; shot `shots.csv` (cột
  `layers` `A-<model>`/`E-<bối cảnh>`, cỡ cảnh, hành động, giờ: sinh vật/bối cảnh xuất hiện thế nào).
- Tư liệu của chủ dự án (`SERIES.md` `owner_refs`, có bản quyền): `out/<project>/assets/refs/<slug>/book/` và `REFS.md`.
  Là **chuẩn tối thiểu** về độ kịch tính và chất lượng: phân tích, lấy ý tưởng chung; **không** chép nét, bố cục, màu;
  không làm ảnh tham chiếu, không đưa vào phim.
- Tư liệu đã có (đừng tải lại): `out/<project>/assets/refs/<slug>/REFS.md`, `_credits.jsonl` của từng thư mục ảnh.
- Concept đã phác (nếu có): `out/<project>/characters/<slug>/concept/*.png`. Lỗi đã biết: <con nào sai gì>.
- Phong cách phim: <style, vd. lai chân thực + grade thuỷ mặc>.
- Người xem Việt Nam: ưu tiên mỹ thuật Việt (Đông Sơn, Chăm, Lý, Trần, Lê, Nguyễn, tranh dân gian) bên cạnh Trung Hoa,
  Nhật, Hàn.

## Nguồn và giấy phép

- Văn bản: zh.wikisource.org (bản thô `action=raw`), ghi link + ngày truy cập; không chép từ trí nhớ.
- Ảnh: Wikimedia Commons và bảo tàng mở (CC0, phạm vi công cộng, CC BY, CC BY-SA). Tải bằng
  `python3 tools/refs_fetch.py fetch` (giấy phép, tác giả, link vào `_credits.jsonl`; ảnh ≤ 1600 px; không ghi đè).
  Không tải tay bằng curl. Giấy phép không tự do: không tải; cần thì chỉ ghi tên + link + mô tả bằng lời.
- Không chạy gì từ file tải về.

## Đầu ra mỗi sinh vật chính (mức SÂU)

Theo `templates/research/ICONOGRAPHY.md` → `projects/<project>/characters/<slug>/ICONOGRAPHY.md`:
1. **Văn bản**: nguyên văn chữ Hán + nghĩa sát + link, **≥ 3 nguồn** (kinh văn + chú, chú giải khác, từ điển/loại thư);
   **bảng bộ phận × nguồn** (đầu, mặt, mắt, sừng, thân, chân, đuôi, da/lông/vảy, màu, kích thước, tiếng).
2. **Bảng ảnh**: **15–40 ảnh mới** có giấy phép: tranh/sách cổ, đồ đồng/gốm/điêu khắc, mỹ thuật Việt, ảnh thú thật
   (chỉ giải phẫu, chất liệu).
3. **Phân tích tư liệu của chủ dự án**: vì sao kịch tính, ý tưởng chung lấy được, điều KHÔNG chép.
4. **Phân tích mỹ thuật** và điều làm nên vẻ thần thoại (không ra con vật nuôi).

Theo `templates/research/DESIGN-OPTIONS.md` → `projects/<project>/characters/<slug>/DESIGN-OPTIONS.md`: 2–3 hướng, mỗi
hướng 6–10 gạch đầu dòng + ảnh tham chiếu chính + **Prompt (EN)** cho `qwen-t2i` + **Edit (EN)** cho `qwen-edit` (concept
nào làm nền, sửa gì) + giải phẫu cho 3D.

## Mức VỪA (sinh vật phụ, đạo cụ)

`ICONOGRAPHY.md`: văn bản (nếu có) + 8–15 ảnh + 1 trang hướng dẫn thiết kế + 1 Prompt (EN). Không cần `DESIGN-OPTIONS.md`.

## Bối cảnh

Theo `templates/research/LOCATION-REFS.md` → `projects/<project>/locations/<slug>/LOCATION-REFS.md`: kinh văn, shot và
giờ, tranh sơn thuỷ (bố cục, nét núi, mây), địa hình thật tương tự (ảnh CC), hướng dẫn dựng Blender, grade gợi ý.

## Báo cáo

Mỗi agent trả ≤ 12 dòng: số ảnh mỗi slug (tự do / không tự do), hướng thiết kế mỗi con (1 dòng), lệnh Edit đề xuất,
chỗ thiếu. Không sửa file ngoài phần được giao.
