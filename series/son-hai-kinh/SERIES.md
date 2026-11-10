---
series: son-hai-kinh
title: Sơn Hải Kinh
style: thuy-mac
audience: "Người xem nói tiếng Việt từ 13 tuổi, thích thần thoại và văn hóa Á Đông; xem trên YouTube ngang 16:9"
language: vi
format: {width: 1920, height: 1080, fps: 24}
---

# Sơn Hải Kinh (山海經)

Mỗi tập 60–90 s giới thiệu **một** dị thú, thần hay ngọn núi trong *Sơn Hải Kinh*, dựng từ nguyên văn chữ Hán.
Phong cách: `styles/thuy-mac/` (tranh AI theo lớp + chuyển động bằng code). Thư mục media: `out/son-hai-kinh/ep<NN>/`.

## Khán giả và lời hứa của series

- Người xem phổ thông, không cần biết chữ Hán. Mỗi tập để lại: một hình ảnh lạ khó quên, một câu nguyên văn đọc
  bằng âm Hán Việt, và nghĩa của nó.
- **Trung thành với nguồn**: điều gì nguồn nói thì vẽ đúng; điều gì nguồn không nói thì là diễn giải và phải ghi
  rõ trong `CHARACTER.md`/`LOCATION.md` (cột "nguồn"/"diễn giải"). Không bịa truyện, không gán công dụng mới.
- Không dọa trẻ nhỏ bằng máu me; cái lạ đến từ hình dáng và sự im lặng, không từ bạo lực.

## Giọng kể

Theo mục "Giọng kể và nhịp" của `styles/thuy-mac/STYLE.md`, cộng thêm cho series:
- Người kể là người đọc sách cổ, không phải người thuyết minh khoa học: không "theo các nhà nghiên cứu", không đoán
  nguồn gốc sinh học của dị thú.
- Câu nguyên văn chính đọc âm Hán Việt, sau đó một câu dịch. Tên riêng đọc Hán Việt (Bác Thi, Cơ Sơn, Quách Phác).
- Khi các bản chép khác nhau (vd. "bốn tai" và "bốn mắt"), có thể nói một câu "có bản chép…", không giảng giải dài.

## Quy ước nguồn và tên

- **Văn bản gốc**: `山海經` trên Wikisource tiếng Trung (bản Tứ khố toàn thư, có chú của Quách Phác 郭璞),
  https://zh.wikisource.org/wiki/山海經 – đối chiếu khi cần với `山海經 (四庫全書本)` và `山海經廣注` của
  Ngô Nhậm Thần trên cùng trang. Không dùng ctext.org (chặn truy cập tự động, xem `docs/RUNBOOK.md`).
- Trích nguyên văn **đúng từng chữ** như trang nguồn, kèm link; chú giải đặt trong 〈 〉.
- **Tên**: đọc âm Hán Việt. Chữ hiếm đọc theo chú âm cổ (Quách Phác, phiên thiết trong Quảng vận/Tập vận qua
  Khang Hy tự điển) và ghi căn cứ trong `CHARACTER.md`. Slug không dấu (`bac-thi`, `nui-co`).
- Mỗi nhân vật: `characters/<slug>/CHARACTER.md`; mỗi bối cảnh: `locations/<slug>/LOCATION.md`.

## Nhân vật và bối cảnh

| Slug | Tên | Loại | Nguồn | Tập |
|---|---|---|---|---|
| `bac-thi` | Bác Thi 猼訑 | dị thú | Nam Sơn Kinh, Cơ Sơn | ep01 |
| `nui-co` | Cơ Sơn 基山 (núi Cơ) | bối cảnh | Nam Sơn Kinh | ep01 |

## Tập

| Tập | Thư mục | Chủ đề |
|---|---|---|
| 01 | `ep01-bac-thi/` | Bác Thi – dê chín đuôi, mắt trên lưng |

## Quy ước riêng của series

- Một tập = một dị thú/thần chính; dị thú khác cùng núi chỉ xuất hiện thoáng qua (không cần ảnh khóa).
- Màu son (`accent`) của series dành cho triện ký tên ở cuối mỗi tập; trong truyện chỉ dùng khi nguồn nói rõ màu đỏ.
- Hai dị thú hàng xóm có nét giống nhau (Bác Thi chín đuôi ở Cơ Sơn, cáo chín đuôi 九尾狐 ở Thanh Khâu 青丘 ngay
  phía đông) phải phân biệt rõ bằng hình dáng thân và đầu.
