# Phát hành

Phiên bản theo SemVer, ghi trong `CHANGELOG.md`. Từ phiên Claude Code cloud **không tạo được tag và GitHub Release**:
`git push` một tag bị proxy trả 403 và API tạo release không được phép. Vì vậy việc chia đôi:

## 1. Claude làm (trong phiên, qua PR)
1. Trên nhánh mới từ `main`: đổi `## [Unreleased]` thành `## [x.y.z] - YYYY-MM-DD`, thêm lại một mục `## [Unreleased]`
   trống phía trên, và cập nhật link cuối file:
   ```
   [Unreleased]: https://github.com/danny-exnodes/claude-film-lab/compare/vx.y.z...HEAD
   [x.y.z]: https://github.com/danny-exnodes/claude-film-lab/compare/v<bản trước>...vx.y.z
   ```
   Chọn số: đổi phá vỡ hợp đồng (`docs/CONVENTIONS.md`, cờ CLI, schema) → major; thêm tính năng → minor; chỉ sửa → patch.
2. Chạy và ghi kết quả vào PR: `python3 -m unittest discover -s tests` và `tools/doctor.sh` (không tính phí: bản đầy đủ gửi một request video không hợp lệ, Ark từ chối trước khi tạo task).
3. Soạn nội dung release từ mục CHANGELOG của bản đó vào `docs/releases/vx.y.z.md` (tiêu đề + phần thân để dán;
   việc người dùng phải làm sau khi nâng cấp đặt lên đầu).
4. Mở PR tên `Release vx.y.z`. Không tự merge.

## 2. Claude không làm
- Không `git tag`, không `git push --tags`, không `git push origin vx.y.z`, không gọi API tạo release.
- Gặp 403 ở các lệnh trên là **đúng như dự kiến**: không thử lại, không tìm đường vòng; báo người dùng làm mục 3.

Ngoại lệ: trong phiên **local** (máy chủ dự án, `gh` đã đăng nhập), khi chủ dự án **yêu cầu trực tiếp** trong phiên đó
("merge và phát hành"), Claude được merge PR phát hành và tạo tag + release bằng
`gh release create vx.y.z --target main --title vx.y.z --notes-file docs/releases/vx.y.z.md`. Không bao giờ tự làm khi
không được yêu cầu, và không bao giờ từ phiên cloud.

## 3. Người dùng làm (sau khi PR được merge)
1. GitHub → **Releases** → **Draft a new release**.
2. **Choose a tag** → gõ `vx.y.z` → *Create new tag on publish*; **Target**: `main` (commit merge của PR phát hành).
3. Tiêu đề `vx.y.z`; phần mô tả: dán nội dung `docs/releases/vx.y.z.md`.
4. **Publish release**.
5. Xoá nhánh `release/*` (hoặc nhánh của PR) nếu còn; nên bật *Settings → General → Automatically delete head branches*.
6. Có thay đổi `docs/setup-script.sh` trong bản này → dán lại vào Setup script của môi trường Film Lab.

## Đã phát hành
| Bản | Tag trỏ tới | Ghi chú |
|---|---|---|
| `v1.0.0` | `f0fe000` (2026-11-10) | tạo tay; nhánh `release/v1.0.0` còn trên remote, xoá được |
| `v1.1.0` | `db93b4a` (2026-11-11) | tạo tay |
| `v1.2.0` | `df6258c` (2026-11-25) | tạo tay |
| `v1.3.0` | commit merge của PR `Release v1.3.0` (2026-11-25) | Claude tạo bằng `gh release create` từ phiên local, theo yêu cầu trực tiếp của chủ dự án |
| `v1.4.0` | commit merge của PR `Release v1.4.0` (2026-11-25) | Claude tạo từ phiên local, theo yêu cầu trực tiếp của chủ dự án |
| `v1.5.0` | commit merge của PR `Release v1.5.0` (2026-11-26) | Claude tạo từ phiên local, theo yêu cầu trực tiếp của chủ dự án |
