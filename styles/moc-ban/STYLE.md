# Mộc bản (`moc-ban`) – NHÁP

> **Trạng thái: draft.** Tạo bằng cách chép `styles/_template/` và điền trong vài phút, không sửa skill nào – để
> kiểm chứng rằng thêm trường phái chỉ là thêm dữ liệu (issue #5). Chưa gen thử ảnh nào; mọi giá trị là đề xuất.
> Trước khi dùng cho tập thật: thử 1 ảnh `--fast` mỗi lớp, chỉnh `style.yaml`, đổi `status: stable`.

Trạng thái: **draft** · Kế thừa: `cinecode:woodcut` (`/root/.claude/skills/cinecode/styles/woodcut.md`)
· Dữ liệu máy đọc: `style.yaml` · Mẫu prompt: `prompts/` · Chuyển động: `motion.md` · Âm thanh: `sound.md`

## Tinh thần

Mỗi shot là một tờ in khắc gỗ: đen là gỗ còn nguyên, trắng là chỗ dao đã khoét. Ánh sáng được "khắc" ra. Hợp với
truyện dân gian, sử ký, lao động – nơi sức nặng quan trọng hơn sự mềm mại của mực loang.

## Khi nào dùng

- Truyện dân gian, sử, truyện lao động, ngụ ngôn có xung đột rõ; chuỗi tranh không lời.
- Không hợp: cảnh cần sương mềm, gradient, nhiều màu.

## Giới hạn

- Nhân vật ở trung/cận cảnh là tranh AI (L4/P). Seedream dễ vẽ thành tranh mực xám hoặc ảnh lọc ngưỡng: prompt phải
  nhấn "carved lines follow the form", negative có `grey wash`, `gradient shading`.
- Chỉ một bản màu (`palette.plate`) cho một vật quan trọng (recipe §3); bản màu do code tô vào chỗ trắng, không vẽ.

## Giọng kể và nhịp

Lời ít, thấp, mộc như chú thích dưới tranh (recipe §7 "Voice"); phụ đề nằm ở lề giấy dưới, không đè hình
(recipe §4). Shot là các "tờ in" khóa khung 5–10 s; cắt cứng = một lần in mới (recipe §5), không hòa tan.

## Nguồn tham khảo hợp lệ

Tranh khắc gỗ đã thuộc phạm vi công cộng (ghi nguồn, dùng bản quét từ kho mở); mộc bản Việt Nam cổ ở kho số hóa
công khai. Tác phẩm còn bản quyền và phim thương mại chỉ để lấy không khí: không tên, hình, bố cục trong prompt.
Không tên họa sĩ (kể cả họa sĩ recipe nêu) trong prompt.

## Quan hệ với recipe cinecode `woodcut`

Kế thừa nguyên: §1, §3, §5, §6, §7, §9. Ghi đè (nháp):

| Mục recipe | Recipe nói | Series làm | Vì sao |
|---|---|---|---|
| §2 Figures / §10 engine | khắc mọi thứ bằng code | nhân vật, cảnh chính là tranh AI; code làm khung lề, bản màu, đốm khắc | giống thủy mặc: chi tiết cần tranh AI |
| §4 Type | IM Fell English | `Noto Serif` cho phụ đề | IM Fell English không có dấu tiếng Việt |

## Quy cách lớp và tách nền

| Lớp | Nền khi tạo | Tách alpha | Ghi chú |
|---|---|---|---|
| L1 | đặc | none | tờ in nền, có lề giấy do code vẽ |
| L2, L3 | trắng phẳng | luminance 40/215 | chỉ có đen/trắng nên ngưỡng cứng hơn thủy mặc |
| L4, P | trắng phẳng | rembg 60/200 | rembg không cần màu khóa; viền đen trên trắng tách sạch |

Không vẽ khói, mưa, tia sáng động vào tranh – đó là code.

## Mẫu prompt

Dùng nguyên mẫu `prompts/*.txt` chép từ `_template` (nền "flat plain white background"), chưa chỉnh riêng.
