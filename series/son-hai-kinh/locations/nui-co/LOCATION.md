# Cơ Sơn (基山, núi Cơ) – `nui-co`

Nơi ở của Bác Thi (`characters/bac-thi/`). *Sơn Hải Kinh · Nam Sơn Kinh*, dãy đầu tiên (南山經之首). Style: `styles/thuy-mac/`.

## Nguồn nguyên văn

https://zh.wikisource.org/wiki/山海經/南山經 (bản Tứ khố, chú Quách Phác; truy cập 2026-11-10)

> 又東三百里，曰基山，其陽多玉，其陰多怪木。有獸焉，其狀如羊，九尾四耳，其目在背，其名曰猼訑〈愽施二音。施一作阤〉，佩之不畏〈不知恐畏〉。有鳥焉，其狀如雞而三首六目、六足三翼，其名曰𪁺𩿧，〈𪁺𩿧急性，敞孚二音〉食之無臥〈使人必眠〉。

Chú Quách Phác dùng để hiểu đoạn trên (cùng trang, ở mục khác):
- Núi Nữu Dương (杻陽之山): 〈山南爲陽，山北爲陰〉 – sườn nam là "dương", sườn bắc là "âm".
- Núi Viên Dực (猨翼之山): 〈凡言怪者，皆謂兒狀倔奇不常也。〉 – hễ nói "quái" là chỉ hình dáng kỳ dị, khác thường
  (chữ 兒 trong bản chép Wikisource, nghĩa là 皃 "dáng vẻ").

**Âm Hán Việt (câu núi)**: Hựu đông tam bách lý, viết Cơ sơn, kỳ dương đa ngọc, kỳ âm đa quái mộc.
**Dịch**: Lại đi về phía đông ba trăm dặm là núi Cơ; sườn nam nhiều ngọc, sườn bắc nhiều cây hình thù kỳ dị.

**Vị trí trong dãy**: núi thứ bảy của dãy Nam Sơn đầu tiên. Phía tây 300 dặm là núi Thiền Viên (亶爰之山, chú 〈亶音蟬〉; "多水，無草木，
不可以上"); phía đông 300 dặm là Thanh Khâu (青丘之山, có cáo chín đuôi 「其狀如狐而九尾」).

## Đặc điểm

| # | Đặc điểm | Loại | Căn cứ | Cách vẽ |
|---|---|---|---|---|
| 1 | Sườn nam nhiều ngọc | nguồn | 「其陽多玉」 | đá trơn nhạt màu, gân trắng như ngọc lộ trên vách – **chỉ bằng mực**, không màu xanh ngọc |
| 2 | Sườn bắc nhiều cây lạ | nguồn | 「其陰多怪木」 + chú 「凡言怪者，皆謂兒狀倔奇不常也」 | cây thân xoắn vặn, cành như móng vuốt, gốc trồi; lạ ở **hình dáng**, không phát sáng, không ma quái |
| 3 | Sườn nam là sườn được nắng | nguồn (chú) | 〈山南爲陽，山北爲陰〉 | sườn ngọc quay về phía nắng thấp bên phải (`light`); sườn cây lạ chìm trong mực đậm |
| 4 | Có chim 𪁺𩿧 (ba đầu, sáu mắt, sáu chân, ba cánh) | nguồn | 「有鳥焉，其狀如雞而三首六目、六足三翼」 | chỉ thoáng qua nếu kịch bản cần; không thiết kế trong ep01 |
| 5 | Núi cao, dốc, có gờ đá bằng | diễn giải | nguồn không tả địa hình | gờ đá phẳng ở sườn nam làm mặt đứng (L3) cho Bác Thi |
| 6 | Không có nước chảy | diễn giải | nguồn không nhắc sông suối ở Cơ Sơn (khác các núi có "…之水出焉") | không vẽ thác, suối |
| 7 | Không người, không đền miếu | diễn giải | nguồn không nhắc | không kiến trúc, không đường mòn |

## Nội dung lớp (`{subject}` cho `styles/thuy-mac/prompts/`)

Viết sẵn để `film-prompt-layers` điền vào mẫu; `{constraints}` theo từng shot.

| Lớp | Mẫu | `{subject}` |
|---|---|---|
| L1 | `bg.txt` | distant ranges of a lone high mountain, its sunlit southern slope with pale smooth rock faces streaked with white jade-like veins, its shaded northern slope dark with masses of twisted trees, layered far peaks fading into empty paper |
| L2 | `mid.txt` | steep rocky slopes of the shaded northern side of the mountain, clusters of strange twisted trees with contorted gnarled trunks, claw-like bare branches and exposed roots, growing from cracks in dark rock |
| L3 | `fg.txt` | a broad flat ledge of pale smooth rock on the sunlit southern slope, white jade-like veins along its edge, a few small twisted roots at one end |
| L1 (lia dài) | `bg.txt` | a long handscroll panorama of a mountain range seen from the side, a lone high mountain with a sunlit jade slope and a shaded slope of twisted trees in the middle |

## Ảnh tham chiếu

Chưa có. Bộ lớp được duyệt sẽ ghi ở `EPISODE.md` của tập và `styles/thuy-mac/examples.md` (link Drive).
