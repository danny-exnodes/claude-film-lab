---
name: film-prompt-layers
description: >-
  Viết prompt và tạo các lớp tranh 2.5D (L1 nền, L2 tầng giữa, L3 tiền cảnh, L4 nhân vật, P bộ phận, FX) bằng Seedream
  cho AI Film Lab, theo style pack styles/<id>/style.yaml: ghép khối phong cách, tạo ảnh có ledger/ngân sách, tách alpha
  theo lớp (tools/layers/matte.py), đánh dấu điểm neo (anchors.py mark), đặt tên và ghi prompts.csv. Dùng ở khâu 3–5
  (cổng G2), khi nói "prompt lớp", "tạo lớp tranh", "ảnh khóa nhân vật", "shot mẫu", "tách nền", "điểm neo", "plates".
---

# film-prompt-layers – prompt và lớp tranh

Ai dùng: `film-art-director` (khâu 3: viết thiết kế và prompt, **không tạo ảnh**), `film-plate-maker` (khâu 4–5: tạo ảnh,
tách nền, neo). Hợp đồng file: `docs/CONVENTIONS.md` §2, §3, §6, §7. Model và giới hạn: `docs/MODELS.md`.

## 1. style.yaml quyết định mọi thứ

Đọc `projects/<project>/SERIES.md` → `style: <id>` → `styles/<id>/style.yaml`. Không chép giá trị style vào skill hay prompt
bằng tay; luôn đọc lại từ file:
- `style_block`: câu đặt **đầu mọi prompt ảnh**, nguyên văn.
- `negative`: gửi qua `--negative` **và** viết thành ràng buộc trong prompt ("no text, no signature…"), vì chưa xác minh
  model có áp dụng `--negative`.
- `palette`, `light`: dùng trong `{constraints}`/`{light}`; mọi lớp của một shot cùng hướng sáng.
- `layers.<mã>`: size, nền đặc hay không, ghi chú ràng buộc. `matte.per_layer.<mã>`: cách tách alpha và ngưỡng.
- `models`: `image` (mặc định), `draft` (`--fast`), `pro` (chỉ Lambda), `video`.
- Mẫu prompt: `styles/<id>/prompts/*.txt` với chỗ trống `{style_block}`, `{subject}`, `{constraints}`, `{light}`.
- `STYLE.md` của style: lý do các quyết định (nền của từng lớp, giới hạn model, nguồn tham khảo hợp lệ). Đọc trước khi
  viết prompt đầu tiên của một series.

Chi tiết ghép prompt, ví dụ và lỗi hay gặp: `references/prompt-assembly.md`.

## 2. Bảng lớp (mặc định; style.yaml ghi đè)

| Lớp | Size | Nền khi vẽ | Tách alpha (`matte.per_layer`) | Ràng buộc |
|---|---|---|---|---|
| L1 nền | 2K ngang, rộng hơn khung 20–30% để lia | đặc | `none` | nửa dưới ít chi tiết; không tiền cảnh, nhân vật, chữ, triện |
| L2 tầng giữa | 2K ngang | phẳng (`paper_bg` hoặc `key_bg`) | thủy mặc: `luminance` (giữ vệt mực loang) | giữa khung trống; chân đá tan dần; không trời, không sương vẽ sẵn |
| L3 tiền cảnh | 2K ngang | phẳng | thủy mặc: `luminance` | mặt đứng đủ rộng cho nhân vật; cùng hướng sáng |
| L4 nhân vật | 2K, toàn thân có lề | phẳng | `rembg` (ngưỡng 60/200) | không bóng đổ, không mặt đất |
| P<n>-<bộ-phận> | như L4 | phẳng | `rembg` | "only the <part>, same position and scale", ảnh L4 làm `--ref` |
| FX | tùy | phẳng | theo style | ít dùng: sương, khói, tàn lửa, mưa làm bằng code |

Không vẽ sương, khói, tàn lửa, mưa vào tranh: phần đó là `code_motion` để chuyển động được.
Nền phẳng lấy màu từ `matte.paper_bg` (luminance) hoặc `matte.key_bg` (chroma) đúng theo method của lớp đó.

## 3. Nhân vật (khâu 3, art-director)

1. Bảng giải phẫu trong `projects/<project>/characters/<slug>/CHARACTER.md`: mỗi đặc điểm một dòng, cột "nguồn" (mệnh đề
   chữ Hán từ `research.md`) hoặc "diễn giải". Mỗi đặc điểm thành **một cụm viết HOA** trong prompt
   (`NINE TAILS`, `FOUR EARS`, `EYES ON ITS BACK`, `NO EYES ON THE FACE`).
2. Prompt khóa nhân vật (front, toàn thân) → ảnh khóa duyệt ở G2 → các góc khác dùng ảnh khóa làm `--ref`.
3. Biến thể trạng thái (mắt nhắm, cúi đầu): đổi đúng một chi tiết, ảnh khóa làm `--ref`. Seedream Pro chỉ qua Lambda
   (đã triển khai; `ark.py lambda-job prepare` → Invoke → `finish`, do đạo diễn chạy ở phiên chính, agent không gọi).
4. Lỗi hay gặp, ghi thành ràng buộc: tự thêm mắt trên mặt, sai số đuôi/tai, quầng sương quanh viền, bóng đổ dưới chân.
5. Mỗi prompt lưu thành file `projects/<project>/ep<NN>-<slug>/prompts/<tên-file-ảnh-không-đuôi>.txt` và một dòng
   `prompts.csv` (cột `file` ghi tên ảnh sẽ tạo, `usage` và `approved` để trống).

## 4. Tạo ảnh (khâu 4–5, plate-maker)

Mọi lần tạo ảnh đều có ledger và trần (thiếu là lỗi quy trình):
```
FILM_AGENT=film-plate-maker python3 tools/ark.py image "$(cat <prompt_file>)" \
  out/<project>/ep<NN>/plates/ep<NN>_s<NN>_<lớp>_<chủ-thể>_v<NN>.png --size <layers.<lớp>.size trong style.yaml> \
  [--ref <ảnh khóa>.png] [--negative "<negative>"] [--seed <n>] \
  --ledger out/<project>/ep<NN>/ledger.csv --budget projects/<project>/ep<NN>-<slug>/budget.yaml
```
- **G2 trước hàng loạt:** khâu 4 chỉ tạo ảnh khóa nhân vật và đủ lớp của **một** shot mẫu (2K, hoặc `--fast` để nháp).
  Không tạo shot khác cho tới khi `gates.G2` có ngày trong EPISODE.md.
- Không dùng `--force`. Ảnh pro hoặc 4K vượt giới hạn 30 s của proxy → chỉ qua Lambda (đã triển khai), ở phiên chính, luôn bằng
  `ark.py lambda-job prepare` → Invoke → `finish` để vào ledger (`lambda/README.md`); agent tạo lớp dùng 2K của model `image`.
- `--seed` và `--negative` có trong ark.py nhưng **chưa xác minh** model áp dụng: ghi seed vào `prompts.csv` để tham
  khảo, không hứa tái tạo y hệt.
- `--ref` được ark.py tự nén JPEG q90, cạnh ≤ 2048; file trên đĩa giữ nguyên.
- **502 sau ~30 s:** ledger ghi `cut-502`; **không thử lại** (có thể đã tính phí). Báo đạo diễn.
- Mã thoát 3 (`refused-budget`): dừng ngay, báo đạo diễn số đã dùng và trần.
- Phiên bản luôn tăng (`_v01`, `_v02`…), không ghi đè. Song song tối đa 3 plate-maker, mỗi agent nhóm shot riêng.

## 5. Tách alpha, kiểm, neo

1. Tách alpha theo style (method, ngưỡng low/high, màu nền lấy từ `matte.per_layer`, `P1-x` dùng khóa `P`):
   ```
   python3 tools/layers/matte.py <ảnh gốc> --style styles/<id> --layer <mã> --preview <xem-thử>.png
   ```
   Bỏ OUT thì ảnh tách ghi vào `plates/matte/<cùng tên>.png` – đây là quy tắc (CONVENTIONS §3); matte.py từ chối ghi đè
   ảnh gốc và từ chối OUT đã có (`--overwrite` chỉ để thay một bản tách). Cờ tường minh chỉ dùng khi
   đạo diễn ghi trong hợp đồng. Thủy mặc: L2/L3 `luminance` (rembg cắt mất vệt mực loang), L4/P `rembg`.
2. Kiểm bằng mắt (Read ảnh `--preview`, ghép trên nền đỏ): viền trắng, quầng sương, lỗ thủng (thân sáng trùng nền),
   mực bị cắt. Lỗi thì báo, không tự tạo lại ảnh ngoài hợp đồng.
3. Điểm neo: Claude đọc ảnh, đề xuất tọa độ (mắt, đường chân, mặt đá, gốc đuôi), ghi bằng
   `python3 tools/layers/anchors.py set <tập>/anchors.json <file> <tên-điểm> X Y`, rồi
   `python3 tools/layers/anchors.py mark <ảnh> <tập>/anchors.json <xem-thử>.png` vẽ dấu chữ thập. Đạo diễn đưa ảnh
   xem thử cho **người duyệt**; điểm sai thì sửa bằng `set`. Ghi rõ trong báo cáo điểm nào chưa được duyệt.
4. Ghi/ cập nhật dòng `prompts.csv`: `file,shot,layer,model,size,prompt_file,refs,seed,usage,approved,drive_link`
   (`usage` = JSON usage Ark nguyên văn, đặt trong ngoặc kép; `refs` cách nhau bởi `;`; `approved` chỉ đạo diễn ghi `yes`).

## 6. Không làm

- Không nêu tên họa sĩ còn sống hay phim thương mại trong prompt; không dùng ảnh có bản quyền làm `--ref`.
- Không gen thử ngoài hợp đồng giao việc; không tạo lại lớp đã khóa trong EPISODE.md.
- Không in hay tìm API key.
