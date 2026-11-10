# Ghép prompt, ví dụ và lỗi hay gặp

**Mã tập (`docs/CONVENTIONS.md` §2):** ví dụ dưới đây viết `ep<NN>` (dự án không chia quyển: thư mục `ep01-<slug>`, media `out/<project>/ep01/`, file `ep01_s03_...`). Dự án chia quyển dùng `q<NN>t<NN>`: thư mục tập `q01-t01-<slug>`, media `out/<project>/q01t01/`, file `q01t01_s03_L4_bac-di_v02.png`, clip `q01t01_s03_seedance25_v01.mp4`, bản dựng `q01t01_draft_v01.mp4`. Đọc mã tập từ `EPISODE.md` (`book` + `episode`) / tên thư mục tập, không tự đổi.

## 1. Thứ tự ghép

```
{style_block}            ← nguyên văn style.yaml, luôn đứng đầu
{subject}                ← nội dung lớp: chủ thể, tư thế, vị trí trong khung, cụm VIẾT HOA từ bảng giải phẫu
{constraints}            ← ràng buộc lớp (bảng lớp) + negative viết thành câu + nền phẳng (mã màu)
{light}                  ← style.yaml light, giống nhau cho mọi lớp của một shot
```
Mẫu theo vai trong `styles/<id>/prompts/` (vd. `bg.txt`, `mid.txt`, `fg.txt`, `character.txt`, `part.txt`): chọn mẫu
theo lớp, thay chỗ trống, lưu kết quả vào `projects/<project>/ep<NN>-<slug>/prompts/<tên-ảnh>.txt`. Không sửa mẫu của style
pack trong tập; cần đổi mẫu thì báo đạo diễn (style pack là chung cho mọi series).

## 2. Ví dụ `{subject}` và `{constraints}` (nhân vật L4, thủy mặc, minh họa)

```
subject: a goat-like beast standing in profile facing right, full body with generous margin,
  NINE TAILS fanned behind, FOUR EARS, EYES ON ITS BACK along the spine, NO EYES ON THE FACE,
  calm stance
constraints: isolated on a flat plain background <màu theo matte.per_layer.L4>, no ground, no cast shadow,
  no mist or halo around the outline, no text, no signature, no seal
```
Tiếng Anh cho prompt (model hiểu tốt hơn); cụm viết HOA là đặc điểm từ nguồn, phải khớp bảng giải phẫu.

## 3. Lớp bộ phận (P)

- Prompt: `only the <part>, same position and scale as the reference, nothing else` + nền phẳng.
- `--ref` = ảnh L4 đã duyệt của đúng shot đó (hoặc ảnh khóa nếu cùng góc).
- Đặt tên `ep01_s05_P1-duoi_bac-thi_v01.png`: mã lớp `P<n>-<bộ-phận>` ASCII kebab-case.

## 4. Kiểm tên file

Regex lớp (CONVENTIONS §2): `^ep\d{2}_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_[a-z0-9-]+_v\d{2}\.(png|jpg)$`.
Chủ thể là slug không dấu (`bac-thi`, `nui-co`). Bản sau tách alpha giữ cùng tên đuôi `.png` ở thư mục tách riêng hoặc
tăng phiên bản, theo cách `matte.py` ghi ra (xem `--help`), không ghi đè ảnh gốc.

## 5. Lỗi hay gặp → cách sửa

| Lỗi | Sửa |
|---|---|
| Thêm mắt trên mặt nhân vật có mắt ở chỗ khác | thêm `NO EYES ON THE FACE`, đưa đặc điểm mắt lên đầu `{subject}` |
| Sai số đuôi/tai | số bằng chữ HOA (`NINE TAILS`), thêm "evenly spaced, countable" |
| Quầng sương, viền trắng quanh nhân vật | `no mist or halo around the outline`; L4 dùng nền phẳng đúng mã màu |
| Bóng đổ, mặt đất dưới chân | `no ground, no cast shadow` |
| Chữ, triện, chữ ký | negative viết thành câu trong prompt |
| Video ra vuông | ảnh đầu vào vuông + `ratio=adaptive` → dùng ảnh 16:9 hoặc `--ratio 16:9` |
| rembg cắt mất vệt mực loang | lớp mực (L2/L3 thủy mặc) dùng `luminance`, không `rembg` |
| 502 sau ~30 s | không thử lại; giảm size, `--fast`; pro/4K chờ Lambda |
