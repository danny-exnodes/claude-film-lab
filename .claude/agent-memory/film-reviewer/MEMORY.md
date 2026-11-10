# Bộ nhớ film-reviewer

Lỗi hay gặp khi kiểm sản phẩm. Mỗi mục: ngày · lỗi · dấu hiệu nhận ra · khâu phải quay lại. Giữ dưới 200 dòng.

## Đã biết từ trước (2026-11-10, từ docs/MODELS.md, docs/RUNBOOK.md)
- Model `ModelNotOpen`: `seedream-5-0-260128`, `dreamina-seedance-2-0-*` chưa kích hoạt. `prompts.csv` ghi model đó là
  dấu hiệu dòng bịa hoặc ảnh không tạo được → Chặn, khâu 4/5.
- Proxy cắt ở ~30 s (502): ledger có `cut-502` thì không được có dòng thử lại cùng prompt ngay sau đó → Nên sửa (quy trình).
  `prompts.csv` ghi model pro hoặc size 4K trong v1.0.0 (Lambda chưa có) → kiểm lại.
- Seedream trả JPEG: lớp cần alpha mà không có bản tách (hoặc nền phẳng còn trong ảnh) → Chặn, khâu 5.
- Ảnh đầu vào vuông → video vuông (960×960): `check-<v>.txt` báo clip không 16:9 → Chặn, khâu 6.
- `rembg` trên lớp mực thủy mặc làm mất vệt loang, viền cứng: L2/L3 phải tách bằng `luminance` → Nên sửa hoặc Chặn, khâu 5.

## Kịch bản
- Dấu gạch ngang trong lời; câu không có mốc; câu cách nhau < 3 s; câu trích không có trong `research.md` nguyên văn.
