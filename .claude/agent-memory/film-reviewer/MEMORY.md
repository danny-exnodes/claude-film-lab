# Bộ nhớ film-reviewer

Lỗi hay gặp khi kiểm sản phẩm. Mỗi mục: ngày · lỗi · dấu hiệu nhận ra · khâu phải quay lại. Giữ dưới 200 dòng.

## Đã biết từ trước (2026-11-10, từ docs/MODELS.md, docs/RUNBOOK.md)
- Model `ModelNotOpen`: `seedream-5-0-260128`, `dreamina-seedance-2-0-*` chưa kích hoạt. `prompts.csv` ghi model đó là
  dấu hiệu dòng bịa hoặc ảnh không tạo được → Chặn, khâu 4/5.
- Proxy cắt ở ~30 s (502): ledger có `cut-502` thì không được có dòng thử lại cùng prompt ngay sau đó → Nên sửa (quy trình).
  `prompts.csv` ghi model pro hoặc size 4K: hợp lệ khi ledger có dòng `lambda` cùng req; không có thì Chặn.
- Seedream trả JPEG: lớp cần alpha mà không có bản tách (hoặc nền phẳng còn trong ảnh) → Chặn, khâu 5.
- Ảnh đầu vào vuông → video vuông (960×960): `check-<v>.txt` báo clip không 16:9 → Chặn, khâu 6.
- `rembg` trên lớp mực thủy mặc làm mất vệt loang, viền cứng: L2/L3 phải tách bằng `luminance` → Nên sửa hoặc Chặn, khâu 5.

## Kịch bản
- Dấu gạch ngang trong lời; câu không có mốc; câu cách nhau < 3 s; câu trích không có trong `research.md` nguyên văn.

## Kịch bản
- 2026-11-10 · Câu dịch thơ tán/nguyên văn trùng gần hết chữ với bản dịch sách người dùng gửi · so từng câu với sources/*/chep-noi-dung.md · khâu 2. Thơ tán: đọc Hán Việt rồi dịch lại.
- 2026-11-10 · Tên Hán Việt trùng từ thông dụng khi đọc TTS ("con ngu", "tên nó là loại/lục") · thêm danh từ loại ("con", "cá").
- 2026-11-10 · Prompt Seedance không nhắc lại đặc điểm giải phẫu; bàn tay viết chữ sinh chữ giả · cột ai_motion.
- 2026-11-12 · Tập 3D code: chữ trên hình nằm cả ở `ui.label` lẫn `makeTextPlane`/`pageText`/`map.numbers` trong `_ch*.js` → grep CJK + `String(` trong scenes và helper chung.
- 2026-11-12 · Phụ đề/nhãn hiện trước lời vài giây (đặt theo câu kế tiếp), nhãn gắn chấm bản đồ bị chấm mực đè, chữ đặt trên vật tối → đối t cục bộ với mốc lời, soi khung · khâu 8.
- 2026-11-12 · Loang mực đổi cảnh phủ kín khung thành màn đen 1–2 s; thú ở shot giới thiệu nhỏ hơn 40 % khi không có trong danh sách sửa · khâu 8.
- 2026-11-12 · Chuỗi chữ Hán trong bản thô wiki có chú `{{*|…}}` chen giữa → Grep thô không ra; grep bản không chú hoặc grep hai nửa.
