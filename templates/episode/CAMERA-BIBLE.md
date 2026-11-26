# Camera bible – <Tên tập>

<!-- Mẫu (khâu 2b, agent film-dop; .claude/agents/film-dop.md). Chép vào projects/<project>/<thư mục tập>/CAMERA-BIBLE.md.
     Ngôn ngữ máy quay của cả tập: chuyển giữa chi tiết con vật và độ hùng vĩ của non sông. Viết bằng ý của mình, không
     chép lời từ phim hay sách tham chiếu. Mỗi quy tắc phải kiểm được trên shots.csv (cỡ cảnh, chuyển động, độ dài). -->

> Tập: <thư mục tập> · Phương pháp: <layers | seedance | code | blender> · Style: <id> · Độ dài: <n> s
> Đầu vào đã đọc: script.md, shots.csv, STYLE-FRAMES.md (khung chuẩn: …), LOCATION-REFS (nếu có), CHARACTER.md (…)

## Ý đồ hình ảnh

<!-- 3–5 câu: tập này nhìn thế giới thế nào (người quan sát lặng, kẻ săn, thần linh trên cao…), nhịp chung, cảm xúc
     từng chương. -->

## Thang cỡ cảnh (tam viễn)

<!-- Ba tầng xa của tranh sơn thuỷ: cao viễn (nhìn từ chân núi lên đỉnh), thâm viễn (nhìn từ trước núi vào sâu sau núi),
     bình viễn (nhìn từ núi gần ra núi xa ngang tầm). Mỗi tầng ứng với cỡ cảnh và chuyển động nào của tập; sinh vật
     chiếm bao nhiêu phần khung ở mỗi tầng. -->

| Tầng | Cỡ cảnh (`shot_size`) | Chuyển động (`camera`) | Sinh vật trong khung | Dùng khi |
|---|---|---|---|---|
| cao viễn | | | | |
| thâm viễn | | | | |
| bình viễn | | | | |
| chi tiết | | | | |

## Kỹ thuật chuyển cảnh

<!-- Chọn kỹ thuật cho từng chỗ nối, ghi shot: rack focus (đổi tiêu điểm từ chi tiết sang cảnh, hay ngược lại, trong
     một shot), pull-back reveal (lùi ra cho thấy sinh vật nhỏ giữa vùng đất rộng), graphic match cut (cắt giữa hai
     hình cùng dáng: mắt thú sang vầng trăng, vảy sang sóng đá), scale reveal (vật tưởng nhỏ hoá ra khổng lồ, hay
     ngược lại). Mỗi kỹ thuật ghi phương pháp dựng làm được không (blender: máy 3D thật; layers: push-in/parallax). -->

| Chỗ nối | Kỹ thuật | Cách làm với phương pháp của tập |
|---|---|---|

## Tham chiếu (ý, không chép)

<!-- Mỗi dòng: tác phẩm → ý mượn → shot dùng. Vd. phim tài liệu thiên nhiên (Planet Earth, Our Planet): chờ thú tự vào
     khung, ống kính dài nén lớp núi; Malick: máy trôi theo gió và ánh sáng; Tarkovsky: shot dài, để thời gian
     chảy; Kurosawa: thời tiết làm chuyển động, bố cục theo khối; Anh hùng (Hero): mỗi chương một màu; Ngoạ hổ tàng
     long: thân người trên ngọn cây, nhẹ; Ảnh (Shadow): mực và mưa, gần như đơn sắc. -->

## Nhịp theo chương

<!-- Mỗi chương: cỡ cảnh mở, chỗ cao trào, chỗ thở (shot dài, ít chuyển động), shot nào là chi tiết, shot nào là non sông. -->

| Chương | Shot | Mở | Cao trào | Thở |
|---|---|---|---|---|

## Sinh vật chính

<!-- Mỗi sinh vật chính (bảng "## Sinh vật của tập"): ít nhất một cận chi tiết (close, extreme-close, insert) và một
     cảnh nhỏ giữa non sông (extreme-wide). check_episode.py WARN khi thiếu (tập blender/code). -->

| Sinh vật | Cận chi tiết (shot, chi tiết gì) | Nhỏ giữa non sông (shot) | Góc máy riêng |
|---|---|---|---|

## Luật kiểm được

- Không hai shot liền nhau cùng cả `shot_size` lẫn `camera` (check_episode.py: ERROR).
- Mỗi sinh vật chính: ≥ 1 cận chi tiết + ≥ 1 `extreme-wide` (check_episode.py: WARN, tập blender/code).
-
