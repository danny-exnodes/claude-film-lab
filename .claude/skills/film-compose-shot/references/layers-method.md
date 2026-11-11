# Phương pháp `layers`: dựng bằng ảnh và code, không Seedance

Đọc file này khi `EPISODE.md` của tập ghi `method: layers`. Tập ghi `method: seedance` (hoặc không có khóa `method`,
được hiểu là `seedance`) thì theo `seedance-layer.md`, không theo file này. **Một tập chỉ một phương pháp**: không trộn
hai cách trong cùng một tập, không đổi sau G1 khi chưa hỏi người dùng.

`layers` nghĩa là: mọi hình là ảnh của model tạo ảnh giá thấp, tạo theo lô (`ark.py image-batch`), tách thành lớp, ghép
2.5D, và **mọi chuyển động là code**. Không gọi `ark.py video`, không có khung đầu Seedance, không có thư mục `clips/`,
`budget.yaml` có `video_seconds: 0`, cột `ai_motion` của `shots.csv` để trống ở mọi shot.

Tài liệu liên quan: chữ ký và tham số của từng module `compose-api.md`; vải, tư thế và cách canh thẳng plate tư thế
`layers-character.md`; số liệu riêng của style `styles/<id>/motion.md`.

## 1. Quy tắc dàn cảnh

Bài học G3 của tập đầu tiên: người dùng loại thú **trượt hoặc xoay như hình cắt dán** và **bộ phận hiện rời** (cánh,
đuôi trôi một mình). Từ đó, với `layers`:

1. **Nhân vật giữ tư thế.** Thân không đổi vị trí, không xoay, không co giãn theo thời gian (ngoài `breath` 0,8 %).
   Người xem thấy một bức tranh đang sống, không thấy một con rối bị kéo.
2. **Chuyển động nằm ở bốn chỗ**, theo thứ tự ưu tiên:
   - biến dạng tại chỗ của phần mềm: vạt áo, tay áo, tóc (`cloth`); đuôi, tai, lông, cỏ (`strip-warp`); tán cây, bụi
     (`foliage`); thở (`breath`); mí mắt (`eyelid`);
   - không khí: sương (`mist-bands`), khói (`smoke`), lửa (`fire`), tàn lửa (`embers`), quầng sáng (`sun-glow`);
   - máy quay: đẩy vào, lùi ra, lia, trôi, parallax giữa các lớp;
   - hành động lớn: **đổi bậc giữa 2–4 plate tư thế** (`pose-cycle`, hoạt hình giới hạn 8–12 fps, cắt thẳng từ tư thế
     này sang tư thế kia), không bao giờ nội suy vị trí hay góc xoay của cả thân.
3. **Shot giữ khung luôn có ít nhất hai chuyển động độc lập cộng máy quay** (vd. vạt áo + khói + đẩy vào chậm). Hai
   chuyển động độc lập = khác module hoặc khác `salt`/pha, không lay đồng loạt.
4. **Không có bộ phận nào hiện một mình.** Lớp `P` chỉ chồng khít lên L4 thân đầy đủ. Muốn cho xem một bộ phận: phóng
   máy quay vào đúng vùng đó trên L4 đầy đủ (phóng ≤ 2,2 lần, ghi điểm x,y).
5. **Nhân vật nhìn từ sau lưng hoặc ba phần tư sau là mặc định.** Lưng và áo choàng cho vải nhiều diện tích để bay, che
   mặt (đỡ phải làm mắt, miệng), và đặt người xem cùng hướng nhìn với nhân vật. Chính diện chỉ khi kịch bản cần.
6. **Chân chạm đất.** L4 đặt bằng `place` với `pivot: 'feet'` trên mặt đứng của L3; nhân vật giới thiệu cao ≥ 40 % khung;
   L1/L2 phía sau nhạt 40–60 % để nhân vật không chìm vào cùng tông.
7. **Shot ngắn, giữ có máy quay.** Phần lớn shot 3–6 s; cảnh rộng mở đầu có thể dài hơn nếu có lia. Một tư thế giữ quá
   6 s mà chỉ có máy quay sẽ bị đọc là "đứng yên": cắt sang cỡ cảnh khác hoặc đổi tư thế.
8. **Đi là đổi cảnh, không phải trượt.** Nhân vật cần "đi tới": hoặc chu kỳ bước tại chỗ (`pose-cycle`) trong khi
   **nền** trôi ngược lại nhờ máy quay và parallax, hoặc cắt giữa hai shot giữ tư thế ở hai chỗ khác nhau.

## 2. Kịch bản muốn gì → `layers` làm thế nào

| Kịch bản muốn | `layers` làm | `code_motion` | Ảnh cần thêm |
|---|---|---|---|
| Thú hoặc người bước đi | chu kỳ 3–4 plate tư thế tại chỗ, nền trôi; hoặc máy quay di chuyển trên một tư thế giữ rồi cắt | `pose-cycle` (+ `parallax`) hoặc chỉ máy quay | 2–3 plate tư thế (`L4b`, `L4c`, `L4d`), hoặc 0 |
| Quay đầu, giơ tay, rút kiếm | đổi bậc 2–3 plate tư thế, giữ tư thế cuối | `pose-cycle` | 1–2 |
| Áo choàng, tay áo, tóc trong gió | vùng vải lay tại chỗ, mép dính vào thân đứng yên | `cloth` | 0 |
| Đuôi, tai, lông, cỏ | dải lệch theo sóng từ gốc ra ngọn | `strip-warp` | 0 |
| Cây, bụi, tán lá | tán nghiêng nhẹ theo cơn gió, gốc đứng yên | `foliage` | 0 |
| Chiến trường, làng cháy | cột khói + lưỡi lửa + tàn lửa + ánh lửa hắt lên lớp gần | `smoke;fire;embers` | 0 (không vẽ khói lửa vào tranh) |
| Thở | phóng dọc rất nhẹ quanh chân | `breath` | 0 |
| Chớp mắt, mắt mở dần | mí trượt trên hộp mắt | `eyelid` | 0 |
| Sương, mây trôi | dải sương nhiều độ sâu, ngược chiều | `mist-bands` | 0 |
| Nắng, bình minh | quầng sáng sau núi | `sun-glow` | 0 |
| Nước chảy, sóng, thác | **không có**: phủ sương lên mặt nước, hoặc cắt sang cảnh khác; lấp lánh nhẹ thì để `sun-glow` | `mist-bands` | 0 |
| Đám đông, đàn thú | một con, nhân bản bằng code, lệch pha (`salt`) | theo con gốc | 0 |
| Bay, lao tới, vật lộn, biến hình liên tục | **không làm được** bằng `layers`: viết lại thành tư thế giữ + máy quay + cắt, hoặc người dùng chọn `method: seedance` cho tập | – | – |

Ánh lửa hắt (`COMPOSE.fire.glow`) thuộc id `fire`; `parallax` và `push-in` là máy quay, dùng cho mọi shot. Id phải có
trong `tools/compose/motions.json` **và** trong `style.yaml` `motion:` của style.

## 3. Chi phí mỗi shot (chỉ có ảnh)

`layers` không tiêu giây video nào. Số ảnh của một shot:

| Thành phần | Số ảnh | Ghi chú |
|---|---|---|
| Nền L1/L2/L3 | 0 khi dùng lại, 3 khi là bối cảnh mới | một bộ nền cho mỗi bối cảnh, dùng lại 3–7 shot (`reuse_of`), đổi khung bằng máy quay |
| Nhân vật L4 | 1 cho mỗi nhân vật mỗi tư thế gốc | dùng lại giữa các shot cùng tư thế |
| Plate tư thế `L4b`… | 0–3 | chỉ khi shot có `pose-cycle`; ảnh khóa làm `--ref`, model flash |
| Bộ phận `P` | 0, hiếm khi 1 | lay nhẹ là `cloth`/`strip-warp` trên L4, không cần ảnh |
| Khói, lửa, sương, tàn lửa, vải, lá | 0 | code |

Một shot dùng lại nền thường tốn **1–4 ảnh**; shot chỉ đổi máy quay trên tài sản đã có tốn **0**. Tạo theo lô:
art-director viết `jobs.csv` cho từng nhóm shot, plate-maker chạy
`python3 tools/ark.py image-batch <jobs.csv> --budget B --ledger L [--parallel N] [--dry-run]` (kiểm trần cho cả lô trước
request đầu tiên; ảnh đã có trên đĩa được bỏ qua nên chạy lại sau khi bị ngắt không trả tiền hai lần). Trước G2 đạo diễn
đưa người dùng dòng `FORECAST` của `tools/status.py` (số ảnh còn phải tạo so với trần).

## 4. Không bao giờ

- Không gọi `tools/ark.py video`, `tools/compose/keyframe.py` (khung đầu Seedance), `tools/layers/matte_seq.py`; không
  yêu cầu đạo diễn cấp clip; không ghi gì vào `ai_motion`.
- Không nội suy `x`, `y`, góc xoay hay tỉ lệ của cả thân nhân vật theo thời gian (trượt, lắc, nảy, "đi" bằng cách dịch
  lớp). Dịch chuyển chậm của cả hình chỉ đến từ máy quay và parallax của sân khấu.
- Không cho một lớp `P` hiện mà không có L4 bên dưới; không xoay bộ phận quanh khớp như rối giấy.
- Không trộn dần dài giữa hai tư thế (bóng ma): `pose-cycle` cắt thẳng, trộn tối đa 2 khung.
- Không vẽ khói, lửa, sương, tàn lửa, mưa vào tranh; không vẽ bóng đổ, mặt đất, quầng sáng vào L4.
- Không vẽ nhân vật hay dị thú bằng nét code.
- Không kéo dài một tư thế giữ để "lấp" thời lượng: cắt shot, đổi cỡ cảnh.
- Không tạo thêm plate tư thế ngoài `shots.csv` và hợp đồng; thiếu thì báo đạo diễn.

## 5. Danh sách kiểm của compositor trước G3

Chạy trên `make.py stills` (hai khung cách nhau 1–2 s của mỗi shot) và bản nháp:

- [ ] `EPISODE.md` ghi `method: layers`; film.html không có lớp `seq` nào, không tham chiếu `clips/`.
- [ ] **Không thân nào trượt**: giữa hai khung của cùng shot, điểm chân của mỗi nhân vật đứng yên so với L3 (chỉ lệch
      theo máy quay, cùng lượng với L3).
- [ ] **Không bộ phận nào hiện một mình**: mọi `P` được vẽ ngay sau L4 của nó, cùng `place`.
- [ ] **Mỗi shot giữ khung có ≥ 2 chuyển động độc lập + máy quay**; ghi vào bảng shot của `review/` tên các chuyển động.
- [ ] `pose-cycle`: các plate tư thế chồng khít ở điểm chân (không nhảy khi đổi bậc), fps 8–12, không trộn quá 2 khung;
      tư thế cuối được giữ ≥ 0,5 s trước khi cắt.
- [ ] `cloth`/`strip-warp`/`foliage`: mép dính vào thân hoặc gốc không hở, không có vạch dọc, biên độ trong giới hạn
      của `styles/<id>/motion.md`; hai vùng cạnh nhau lệch pha.
- [ ] Khói, lửa: màu lấy từ `palette` của style; lửa không làm cháy trắng khung; đúng một điểm nhấn màu của style.
- [ ] Nhân vật giới thiệu ≥ 40 % cao khung, chân chạm L3, nền sau nhạt hơn nhân vật.
- [ ] `make.py` không báo `TOO STILL` ở shot nào ngoài các khoảng lặng cố ý đã ghi trong `STATE.md`.
- [ ] `capture.mjs --verify` in `deterministic: yes`.
