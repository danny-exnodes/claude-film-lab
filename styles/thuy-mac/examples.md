# Ví dụ đã duyệt – Thủy mặc

**Chưa có prompt nào được duyệt.** Ví dụ đầu tiên sẽ lấy từ tập đầu tiên làm bằng style này, sau khi người dùng
duyệt ở phiên chính (ghi đường dẫn tập dạng `projects/<project>/ep<NN>-<slug>/` và link Drive). Không commit ảnh; chỉ ghi chữ và link Drive.

## Cách ghi một ví dụ

Mỗi ví dụ là một mục `###`, chép từ dòng `approved=yes` trong `prompts.csv` của tập:

```markdown
### <lớp> – <chủ thể> (<project>/ep<NN>/s<NN>)
- File: `ep01_s03_L2_vach-da_v02.png` · model `seedream-5-0-lite-260128` · size `2560x1440` · seed `<seed hoặc trống>`
- Mẫu: `prompts/mid.txt` · refs: `<file;file>` · tách: `luminance 8/245`
- Drive: <link gói shot từ tools/bundle.py>
- Prompt (nguyên văn đã gửi):
  > ...
- Vì sao được duyệt / lưu ý khi dùng lại: ...
```

## Bài học (ghi khi có)

Ghi những điều thử ra được, mỗi dòng: ngày, lớp, điều học được (vd. "nền magenta vs trắng cho L4", "negative có bớt
triện không"). Bài học đổi quy cách → sửa `style.yaml`/`STYLE.md`, không chỉ ghi ở đây.

## Ví dụ

(trống)
