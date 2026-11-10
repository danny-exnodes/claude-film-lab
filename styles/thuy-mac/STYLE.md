# Thủy mặc (`thuy-mac`)

Trạng thái: **stable** (v1.0.0) · Kế thừa: `cinecode:ink-wash` (`/root/.claude/skills/cinecode/styles/ink-wash.md`)
· Dữ liệu máy đọc: `style.yaml` · Mẫu prompt: `prompts/` · Chuyển động: `motion.md` · Âm thanh: `sound.md`

Tài liệu này chỉ ghi điều series quyết định. Phần recipe cinecode đã nói (bản chất, năm sắc mực, ngữ pháp máy quay,
âm thanh, lỗi hay gặp) không chép lại: đọc recipe, rồi đọc mục "Quan hệ với recipe cinecode" dưới đây.

## Tinh thần

Tranh mực trên giấy dó cũ, kể bằng khoảng trống. Giấy trống là trời, nước, sương và im lặng; mực đậm chỉ
xuất hiện ở chỗ câu chuyện cần mắt người xem dừng lại. Sương là chất liệu chính của phim: nó nối các lớp tranh,
che mép, làm chuyển cảnh, và luôn là sương **chuyển động bằng code**, không bao giờ vẽ sẵn trong tranh.

Khác với recipe gốc (vẽ tất cả bằng nét bút code, kiểu tả ý), series dùng **tranh AI chi tiết** cho nhân vật,
dị thú và cảnh, rồi để code làm phần sống: sương, ánh sáng, nhịp lia, chuyển động nhỏ của bộ phận.

## Khi nào dùng

- Thần thoại, chí quái (Sơn Hải Kinh, Liêu Trai, truyện dị thú), truyền thuyết có núi sông.
- Thiền, ngụ ngôn, thơ: ít sự kiện, nhiều khoảng lặng.
- Cổ trang Á Đông: hành trình, ẩn sĩ, kiếm khách đứng yên trước biến cố.

Không hợp: hành động dồn dập nhiều nhân vật, đô thị hiện đại, dữ liệu/infographic, nội dung cần nhiều màu.

## Giới hạn

- **Nhân vật và dị thú ở trung cảnh, cận cảnh là tranh AI (L4/P), không vẽ bằng code.** Bộ người xieyi của cinecode
  (`hero.js`) chỉ dùng cho hình người rất nhỏ ở xa (cao dưới ~1/10 khung) hoặc khi kịch bản chủ ý muốn tả ý.
- Seedream không xuất nền trong suốt: mọi lớp trừ L1 phải vẽ trên nền phẳng rồi tách (xem bảng dưới).
- Seedream đếm kém: số đuôi, số tai, số mắt phải viết HOA trong prompt và đếm lại trên ảnh trước khi duyệt.
  Lỗi hay gặp: tự thêm mắt trên mặt, sai số đuôi, quầng sương quanh viền.
- Seedance (AI video) dễ vẽ lại phong cách và thêm chi tiết: chỉ dùng cho clip ngắn khi code không làm được
  (vd. dị thú quay đầu); chuyển động còn lại là code trên lớp tranh.
- Một màu son duy nhất (triện + một điểm nhấn); ochre chỉ cho ánh nắng thấp và tàn lửa. Không màu nào khác.

## Giọng kể và nhịp

(Mục này do skill `film-script` đọc.)

- **Giọng**: tiếng Việt, trầm, chậm, ít lời; như lời đề trên tranh (đề bạt), không giải thích điều hình đã nói.
  Câu ngắn, mỗi câu một ý. Ngôi thứ ba, thì hiện tại. Không cảm thán, không "các bạn có biết".
- **Nguyên văn**: câu chữ Hán then chốt đọc âm Hán Việt trước, rồi một câu dịch nghĩa. Chữ Hán hiện trên hình
  (cột dọc, `type.cjk`), phụ đề tiếng Việt ở khoảng giấy trống của shot (`type.latin`, nghiêng).
- **Mật độ lời**: khoảng 2,5–3 âm tiết/giây; tổng thời gian có lời ≤ 60–65% thời lượng tập. Mỗi chương có ít nhất
  một khoảng không lời ≥ 3 s.
- **Nhịp hình**: shot 3–13 s (CONVENTIONS §6), phần lớn 5–8 s. Cảnh mở rộng và tĩnh; dồn nhịp ngắn dần trước lúc
  dị thú lộ diện, rồi **một khoảng lặng thật** (recipe §7) ngay trước khoảnh khắc lộ diện.
- **Chuyển cảnh**: lia theo cuộn tranh (phải sang trái), loang mực, đẩy vào sương. Cắt cứng chỉ một lần mỗi tập,
  dành cho cận cảnh quyết định (recipe §6).
- **Cấu trúc gợi ý cho tập 60 s**: mở (cảnh núi, 10–15 s) → nguyên văn (15–20 s) → lộ diện (15–20 s) → ý nghĩa/
  dư âm (10–15 s). `film-script` được đổi, miễn ghi lý do trong `script.md`.

## Nguồn tham khảo hợp lệ

- **Được dùng làm tham chiếu hình và `--ref`**: tranh cổ thuộc phạm vi công cộng (sơn thủy Tống–Nguyên–Minh ở kho mở
  của bảo tàng; tranh minh họa Sơn Hải Kinh bản khắc Minh–Thanh như bản của Hồ Văn Hoán 胡文煥 1593,
  Tưởng Ứng Cảo 蔣應鎬 1597, Ngô Nhậm Thần 吳任臣, Uông Phất 汪紱; dùng bản quét từ kho mở, ghi rõ nguồn). Ghi nguồn vào cột `refs` của `prompts.csv`.
- **Chỉ để lấy không khí** (xem để cảm nhịp, không dùng gì cụ thể): phim thương mại và phim của xưởng hoạt hình,
  kể cả các phim recipe cinecode nêu. Không đưa tên phim, tên nhân vật, khung hình hay bố cục của chúng vào prompt,
  không dùng ảnh chụp từ phim làm `--ref`.
- Không nêu tên họa sĩ còn sống trong prompt. Không dùng ảnh có bản quyền làm `--ref`.

## Quan hệ với recipe cinecode `ink-wash`

**Kế thừa nguyên** (không ghi lại ở đây): §1 bản chất (mực trên giấy, lưu bạch, một màu son); bảng năm sắc mực §2
làm thước đo đậm nhạt khi duyệt tranh; §4 phụ đề kiểu đề bạt và thời gian giữ phụ đề; §5 nhân vật bước 12 fps,
máy quay 24 fps; §6 toàn bộ ngữ pháp máy quay và chuyển cảnh; §7 nguyên tắc âm thanh (cue theo hình, im lặng thật,
foley theo chất liệu, giảm nhạc ~8 dB dưới lời); §9 lỗi hay gặp khi vẽ nét bằng code.

**Series quyết định khác** (ghi đè):

| Mục recipe | Recipe nói | Series làm | Vì sao |
|---|---|---|---|
| §2 Figures are xieyi | người vẽ vài nét bằng code | nhân vật/dị thú là tranh AI chi tiết (L4/P) | dị thú Sơn Hải Kinh cần giải phẫu đúng nguồn, code không vẽ nổi |
| §2 Paper is procedural | giấy do compositor vẽ | L1 mang giấy do AI vẽ; lớp trong suốt không có giấy; code phủ một lớp vân giấy nhẹ lên toàn khung | để các lớp AI nằm trên cùng một mặt giấy, không lặp vân giấy hai lần |
| §3 Colour | chỉ mực + một son | thêm `ochre` cho nắng thấp và tàn lửa; giấy `#EFE6D3` | không khí chiều tà của series; son vẫn chỉ một chỗ |
| §4 Calligraphy | thư pháp vẽ theo khung font bút lông | nguyên văn chữ Hán dùng `Noto Serif CJK TC`, không giả thư pháp | trích dẫn học thuật phải đọc được, đúng chữ |
| §5 Painted into existence | nét hiện theo thứ tự vẽ | tranh AI hiện bằng loang mực hoặc quét ngưỡng độ đậm (đậm hiện trước) | tranh AI không có thứ tự nét |
| §7 Instruments | guqin, xiao, trống lớn, timpani, trống khung, gong nhỏ | thêm bowed drone; thang D minor pentatonic | xem `sound.md` |
| §10 Engine | `ink.js`, `land.js`... vẽ mọi thứ | chỉ dùng cho nét phụ (vệt mực, triện `seal.js`, phụ đề `subs.js`); cảnh chính là tranh AI | như trên |

## Quy cách lớp và tách nền

Bảng đầy đủ trong `style.yaml` (`layers`, `matte`). Quy tắc chung: **không bao giờ vẽ sương, khói, tàn lửa, mưa vào
tranh** – đó là code (`motion.md`), để chúng chuyển động được và các lớp ghép không lộ mép.

| Lớp | Nền khi tạo | Tách alpha | Ghi chú |
|---|---|---|---|
| L1 | đặc (giấy vẽ sẵn) | none | 2560x1440, rộng hơn khung để lia; nửa dưới nhạt |
| L2, L3 | giấy trắng phẳng `#FFFFFF` | luminance 8/245 | alpha = 1 − độ sáng: giữ gradient mực loang, như mực thấm trên giấy |
| L4, P | giấy trắng phẳng `#FFFFFF` | rembg 60/200 | thân đặc, viền cứng; P dùng L4 làm `--ref` |

`style_block` nói "on aged rice paper, visible paper grain"; với L2–L4 mẫu prompt ghi đè: nền **trắng phẳng, không vân
giấy ngoài khối vẽ**. Nếu không, vân giấy bị luminance tách thành một lớp bụi mờ đè lên L1.

**Quyết định nền L4/P: trắng phẳng (`paper_bg`), không dùng magenta `key_bg`.**
- rembg là mô hình tách chủ thể, không tách theo màu khóa: nền magenta không giúp gì cho rembg.
- Pixel bán trong suốt ở viền mực ăn màu nền. Magenta để lại viền hồng thấy rõ trên giấy ấm; trắng để lại viền
  sáng gần như trùng màu giấy khi ghép.
- Nền trắng là "mực trên giấy" tự nhiên, không chống lại `style_block`. (Giả thuyết: Seedream dễ nhuộm tranh hoặc bỏ
  qua nền magenta khi prompt nói giấy dó – chưa thử A/B.)
- Cùng một ảnh có thể tách lại bằng luminance để so sánh mà không phải gen lại (không tốn phí).
- Rủi ro: dị thú thân sáng (như dê) trùng màu nền → rembg đục lỗ thân. Chống: `character.txt` bắt thân phủ mực nhạt
  và viền đậm khép kín; kiểm bằng cách ghép lên nền đỏ. Nếu vẫn lỗi: đổi nền L4 sang xám trung tính phẳng (vd.
  `#8C8378`) cho shot đó và ghi vào `examples.md`.

## Mẫu prompt

`prompts/*.txt` gửi nguyên văn sau khi điền bốn chỗ trống `{style_block}`, `{subject}`, `{constraints}`, `{light}`
(không có dòng chú thích trong file). `{subject}` là nội dung lớp (với nhân vật: các cụm giải phẫu VIẾT HOA từ
`CHARACTER.md`); `{constraints}` là ràng buộc riêng của shot (bố cục, hướng nhìn, cỡ cảnh), có thể để trống.

| File | Lớp | Ghi chú |
|---|---|---|
| `bg.txt` | L1 | không đĩa mặt trời (vầng sáng là `sun-glow`) |
| `mid.txt` | L2 | giữa khung trống, chân đá tan dần, không trời |
| `fg.txt` | L3 | mặt đứng cho nhân vật |
| `character.txt` | L4 | toàn thân, lề rộng, thân phủ mực nhạt |
| `part.txt` | P | `{subject}` = tên bộ phận (vd. "nine tails"); L4 làm `--ref` |
| `edit-eyes-closed.txt` | biến thể L4 | `{subject}` = mắt cần nhắm (vd. "the two eyes on its back"); model `pro` qua Lambda, L4 làm `--ref` |
