# Đội dựng 3D – luật chung (method: blender)

<!-- Mẫu. Đạo diễn chép vào projects/<project>/<thư mục tập>/TEAM-3d.md, điền bảng phân công, đưa đường dẫn file này vào
     hợp đồng của MỌI film-3d-artist chạy song song (.claude/skills/film-pipeline/SKILL.md mục 4, "Đội dựng 3D song song").
     Chỉ lập đội sau cổng thiết kế sinh vật (khâu 3a): mỗi sinh vật chính đã có concept duyệt. -->

## Phân công

<!-- Chia theo nhóm sinh vật (chim, thú, thuỷ tộc…) hoặc bối cảnh, không chia theo shot. Mỗi model đúng một agent. -->

| Agent (`FILM_AGENT`) | Model (`A-<slug>`) | Concept đã duyệt | Shot dùng | Ghi chú |
|---|---|---|---|---|
| film-3d-artist-<nhóm> | | `out/<project>/characters/<slug>/concept/…` | | |

## Phạm vi file (mỗi agent chỉ ghi ở đây)

- Model của mình: `out/<project>/characters/<slug>/` (GLB, `.blend`, texture), turntable
  `out/<project>/<id>/renders3d/turntable-<slug>[_v<NN>]/`.
- `projects/<project>/characters/<slug>/NOTES.md`: một file mỗi model (mục dưới).
- `shots3d/s<NN>.json` chỉ của shot được giao trong bảng trên.
- Thư mục tạm riêng theo `FILM_AGENT` (vd. `out/_tmp/<FILM_AGENT>/`), không dùng chung script phụ với agent khác.
- **Không sửa** `ASSETS.md`, `shots.csv`, `EPISODE.md`, `TEAM-3d.md`, file của agent khác: đạo diễn gộp `NOTES.md` vào
  `ASSETS.md` khi cả đội xong.

## Hàng đợi GPU (một GPU 16 GB cho cả lab)

- `python tools/blender/blender.py render|still|turntable|keyframes` và `python tools/comfy/comfy.py run` tự giữ khoá
  GPU của lab: lệnh chờ khi agent khác đang render, không cần tự canh. Không đặt `FILM_GPU_QUEUE=0`.
- Lệnh GPU khác (script Blender tự viết, `blender -b … --python …`): `python tools/gpu_run.py --label <FILM_AGENT> -- <lệnh>`.
- Ai đang giữ GPU: `python tools/gpu_run.py status`. Chờ lâu thì làm phần không cần GPU (dựng lưới, vật liệu, `check`).
- Blender chạy bằng Python/Blender của **Windows** (PowerShell hoặc Git Bash: `python tools/blender/blender.py …`),
  không bao giờ qua `bash` của WSL (WSL không có Blender, không thấy GPU).

## `NOTES.md` mỗi model (`projects/<project>/characters/<slug>/NOTES.md`)

```
# <slug> – ghi chú dựng (<FILM_AGENT>)
## Đã xong
- <bước, file, lệnh check/turntable đã chạy>
## Còn lại
- <bước tiếp theo, đủ để agent khác làm tiếp không cần hỏi>
## Nguồn và giấy phép
| id (A-<slug>) | Nguồn (preset/GLB/.blend) | Tác giả / link | Giấy phép | Ghi chú |
## Phút GPU
- <lệnh>: <phút>
```

- Ghi `## Đã xong` / `## Còn lại` **sau mỗi bước lớn** và chắc chắn trước khi hết lượt (khoảng 15 lượt cuối: dừng việc
  mới, ghi `NOTES.md`, trả báo cáo). Agent được giao tiếp đọc `NOTES.md` trước, làm đúng phần "Còn lại".
- Gộp bước: một lệnh/script làm trọn một việc (dựng + lưu + `check`), không chạy từng thao tác nhỏ.

## Luật dựng

- Chỉ dựng theo concept đã duyệt trong hợp đồng (`CHARACTER.md` `## Concept đã duyệt`), đọc `ICONOGRAPHY.md`. Ảnh thú
  thật chỉ cho giải phẫu và chất liệu, không cho silhouette. Ảnh sách của chủ dự án: chuẩn chất lượng, không chép.
- Không model không rõ giấy phép; không tải model/asset từ mạng khi hợp đồng không ghi nguồn và giấy phép.
- Không ghi đè đầu ra: thư mục mới `_v<NN>`. Không gọi dịch vụ trả tiền, không hỏi người dùng, không tải lên Drive.
