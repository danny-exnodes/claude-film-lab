# Âm thanh – Thủy mặc

Kế thừa `cinecode:ink-wash` §7 (cue theo hình không lặp vòng, im lặng thật, foley theo chất liệu, lời ít như đề bạt,
giảm nhạc ~8 dB dưới lời) và master −14 LUFS của cinecode. File này chỉ ghi lựa chọn của series
(`style.yaml: sound`).

## Thang âm

`D minor pentatonic` (D F G A C) = điệu Vũ (羽) dựng trên D – một trong các "Chinese pentatonic modes" recipe nêu.
Cả series giữ một chủ âm D để các tập nối nhau; muốn đổi màu trong tập, chuyển sang điệu khác **cùng năm nốt**
(vd. F cung – F G A C D) thay vì đổi chủ âm.

## Nhạc cụ

| `style.yaml` | Tương ứng recipe | Dùng trong series |
|---|---|---|
| plucked zither | guqin (`core/audio/pluck.py` `guqin`) | giọng chính; bồi âm (harmonics) cho giấy trống, trượt dây cho sương |
| end-blown flute | xiao | câu nhạc dài khi lia cuộn tranh; không đè lên lời |
| frame drum | frame drum | bước chân dị thú, nhịp khi dồn cảnh |
| small gong | small gong | đóng triện, khoảnh khắc lộ diện (một tiếng) |
| bowed drone | – (series thêm) | nền trầm dài trên D cho sự hiện diện của dị thú; tắt hẳn trong khoảng lặng |

Không dùng trống lớn/timpani của recipe trừ khi kịch bản có khối nặng (lở núi, sấm).

## Foley riêng của series

Theo nguyên tắc "foley follows the material" của recipe:
- Móng guốc trên đá: tiếng gỗ khô ngắn, nhẹ, có đuôi vang núi.
- Đuôi/lông lay (`strip-warp`): tiếng gió bút (brush air) của recipe, không dùng tiếng vải.
- Mắt mở/nhắm: một giọt mực ("tink" + tiếng ướt) – không dùng hiệu ứng "phép thuật".
- Sương: không có tiếng riêng; ambience gió núi rất thấp.

## Lời bình

Giọng tiếng Việt (TTS hoặc người đọc, xem issue #8). Kiểm từng câu bằng whisper trên bản mix cuối như recipe §7.
Đọc nguyên văn Hán Việt chậm hơn lời thường ~15%, có nghỉ 0,4–0,6 s trước câu dịch.
