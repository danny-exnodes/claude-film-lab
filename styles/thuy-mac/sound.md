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
| plucked zither | guqin (`tools/audio/pluck.py` `guqin`) | giọng chính; bồi âm (`harmonic`) cho giấy trống, trượt dây (`bend`) cho sương |
| end-blown flute | xiao | câu nhạc dài khi lia cuộn tranh; không đè lên lời. `tools/audio` **không có** sáo: bản thu có giấy phép hoặc bỏ |
| frame drum | frame drum (`sfx.drum`, `sfx.drum_roll`) | bước chân dị thú, nhịp khi dồn cảnh |
| small gong | small gong (`sfx.gong`) | đóng triện, khoảnh khắc lộ diện (một tiếng) |
| bowed drone | – (series thêm; `sfx.drone`, xấp xỉ tổng hợp) | nền trầm dài trên D cho sự hiện diện của dị thú; tắt hẳn trong khoảng lặng (`silence` của `score.json`) |

Không dùng trống lớn/timpani của recipe trừ khi kịch bản có khối nặng (lở núi, sấm).
Nhạc code (khi người dùng đã chọn) và foley theo sự kiện dựng bằng `tools/audio/score.py` từ `score.json` của tập, với
`"scale": ["D", "F", "G", "A", "C"]` để nốt ngoài thang bị cảnh báo (`tools/audio/README.md`).

## Foley riêng của series

Theo nguyên tắc "foley follows the material" của recipe:
- Móng guốc trên đá: tiếng gỗ khô ngắn, nhẹ, có đuôi vang núi. → `sfx.hoof`
- Đuôi/lông lay (`strip-warp`): tiếng gió bút (brush air) của recipe, không dùng tiếng vải. → `sfx.brush_air`
  (vạt áo `cloth` cũng dùng `brush_air`; `sfx.cloth_flap` chỉ khi vải thật sự quật mạnh)
- Mắt mở/nhắm: một giọt mực ("tink" + tiếng ướt) – không dùng hiệu ứng "phép thuật". → `sfx.ink_drop`
- Sương: không có tiếng riêng; ambience gió núi rất thấp. → `sfx.wind` (cường độ thấp); sương dâng: `sfx.whoosh`
- Lửa, tàn lửa (`fire`, `embers`): → `sfx.fire` (nền), `sfx.ember` (từng tàn nổ)
- Bước chân trên đất/đá, va chạm nặng, mặt nước: → `sfx.footstep` (`surface`), `sfx.thump`, `sfx.water_ring`

Tên sau mũi tên là giá trị `sound` trong `score.json` (hàm cùng tên trong `tools/audio/sfx.py`).

## Lời bình

Giọng tiếng Việt (TTS hoặc người đọc, xem issue #8). Kiểm từng câu bằng whisper trên bản mix cuối như recipe §7.
Đọc nguyên văn Hán Việt chậm hơn lời thường ~15%, có nghỉ 0,4–0,6 s trước câu dịch.
