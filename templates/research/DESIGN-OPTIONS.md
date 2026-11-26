# <Tên sinh vật> (<chữ Hán>) – hướng thiết kế

<!-- Mẫu cho khâu 3a, mức SÂU. film-iconographer chép vào projects/<project>/characters/<slug>/DESIGN-OPTIONS.md, cạnh
     ICONOGRAPHY.md (mọi khẳng định về nguồn nằm ở đó; ở đây chỉ dẫn mục). 2–3 hướng KHÁC NHAU RÕ RỆT (vd. theo hình
     tượng Hán / theo mỹ thuật Việt / tổng hợp). Mỗi hướng: 6–10 gạch đầu dòng, ảnh tham chiếu chính (tên file trong
     out/<project>/assets/refs/<slug>/iconography/), Prompt (EN) cho qwen-t2i, Edit (EN) cho qwen-edit.
     Đạo diễn chạy ở phiên local trên máy chủ lab (miễn phí, một việc GPU một lúc; --dry-run trước):
       python tools/comfy/comfy.py run qwen-t2i --prompt "<Prompt (EN)>" --out out/<project>/characters/<slug>/concept/<slug>_concept-a_v01.png --ledger out/<project>/<id>/ledger.csv
       python tools/comfy/comfy.py run qwen-edit --image <concept nền>.png --prompt "<Edit (EN)>" --out out/<project>/characters/<slug>/concept/<slug>_concept-a_v02.png --ledger out/<project>/<id>/ledger.csv
     Không đưa ảnh sách của chủ dự án hay ảnh tham chiếu tải về làm đầu vào. Người dùng chọn hướng (cổng 3a). -->

Canon (theo nguồn, mọi hướng đều giữ): <số sừng, số chân, màu, kích thước… dẫn mục 1.4 của ICONOGRAPHY.md>.
Mức tối thiểu: <độ kịch tính phải đạt, dẫn mục 4 của ICONOGRAPHY.md>.

## A. "<tên hướng>" – <dựa trên gì>

- <silhouette, tỉ lệ>
- <đầu, mặt, mắt>
- <thân, chân, đuôi>
- <da / lông / vảy, màu>
- <tư thế đặc trưng>
- <điểm khác hướng B, C>

**Ảnh chính**: `<slug>_ico_NN`, `<slug>_vn_NN`, `<slug>_real_NN` (giải phẫu)

**Prompt (EN)** (qwen-t2i):

```text
<A photorealistic … living creature, full body side view, … (silhouette, materials, palette of the style, light,
background plain), no text>
```

**Edit (EN)** (qwen-edit) – nền `out/<project>/characters/<slug>/concept/<file>.png`:

```text
<1–3 short imperative sentences: what to remove / change / add, then "keep everything else unchanged">
```

## B. "<tên hướng>" – <dựa trên gì>

## C. "<tên hướng>" – <dựa trên gì> (tuỳ chọn)

## Giải phẫu cho 3D (chung; hướng B, C chỉnh theo ghi chú)

| Mục | Giá trị |
|---|---|
| Kích thước (m): dài · cao vai · cao đầu | |
| Tỉ lệ thân : cổ : đầu : đuôi | |
| Khớp/xương cần rig | |
| Chất liệu bề mặt (SSS, roughness khô/ướt, normal, mask) | |
| Lông/vảy/lông vũ (hair curves, số lượng, độ dài) | |
| Cử động trong shot (dẫn `shots.csv`) | |

## Đề xuất thứ tự

<!-- Hướng nào thử trước, concept nào sửa bằng Edit thay vì tạo lại, vì sao. -->
