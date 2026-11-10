# <Tên trường phái> (`<id>`)

<!-- Mẫu STYLE.md. Chép cả styles/_template/ thành styles/<id>/, giữ nguyên TÊN các mục ## (skill lõi tìm theo tên mục,
     vd. film-script đọc "## Giọng kể và nhịp"). Xóa các khối chú thích như thế này khi điền xong.
     Ví dụ đã điền: styles/thuy-mac/STYLE.md. -->

Trạng thái: **draft** · Kế thừa: `cinecode:<id>` hoặc không · Dữ liệu máy đọc: `style.yaml` · Mẫu prompt: `prompts/`
· Chuyển động: `motion.md` · Âm thanh: `sound.md`

## Tinh thần

<!-- 1 đoạn: chất liệu, cảm giác, điều làm trường phái này khác các trường phái khác. Không chép recipe cinecode. -->

## Khi nào dùng

<!-- Gạch đầu dòng: đề tài, thể loại hợp; một dòng "Không hợp:" -->

## Giới hạn

<!-- Phần nào phải là tranh AI, phần nào code vẽ được; giới hạn của model (đếm, chữ, nền trong suốt);
     quy tắc màu. -->

## Giọng kể và nhịp

<!-- (film-script đọc mục này.) Giọng lời bình, mật độ lời (âm tiết/giây, % thời lượng có lời), độ dài shot
     điển hình trong khoảng 3-13 s của CONVENTIONS §6, cách chuyển cảnh, cấu trúc gợi ý cho tập 60 s. -->

## Nguồn tham khảo hợp lệ

<!-- Nguồn được dùng làm tham chiếu/--ref (phạm vi công cộng, ghi nguồn), nguồn chỉ để lấy không khí
     (phim thương mại: không tên, hình, bố cục trong prompt). Không tên họa sĩ còn sống trong prompt. -->

## Quan hệ với recipe cinecode `<id>`

<!-- Kế thừa nguyên: liệt kê số mục recipe. Ghi đè: bảng | Mục recipe | Recipe nói | Series làm | Vì sao |.
     Nếu base: null, ghi "không kế thừa" và viết motion.md/sound.md đầy đủ. -->

## Quy cách lớp và tách nền

<!-- Bảng | Lớp | Nền khi tạo | Tách alpha | Ghi chú |, khớp style.yaml (layers, matte).
     Bắt buộc ghi QUYẾT ĐỊNH màu nền L4/P và lý do (rembg không cần màu khóa; chroma cần key_bg; luminance cần
     paper_bg). Quy tắc chung: không vẽ sương, khói, tàn lửa, mưa vào tranh – đó là code. -->

## Mẫu prompt

<!-- prompts/*.txt gửi nguyên văn sau khi điền đúng bốn chỗ trống: {style_block} (từ style.yaml), {subject} (nội dung
     lớp; nhân vật: các cụm giải phẫu VIẾT HOA từ CHARACTER.md), {constraints} (ràng buộc riêng của shot, có thể
     trống), {light} (từ style.yaml). Không có chỗ trống nào khác; không có dòng chú thích trong file .txt.
     Mẫu trong _template ghi nền "flat plain white background": đổi chữ "white" theo quyết định nền ở mục trên.
     bg.txt = L1, mid.txt = L2, fg.txt = L3, character.txt = L4, part.txt = P (L4 làm --ref),
     edit-eyes-closed.txt = biến thể trạng thái (L4 làm --ref, thường model pro qua Lambda). -->
