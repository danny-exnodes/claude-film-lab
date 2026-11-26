---
# Mẫu trạng thái tập – docs/CONVENTIONS.md §5. Chép vào projects/<project>/<thư mục tập>/EPISODE.md và điền.
# Mã tập (§2): dự án không chia quyển → ep<NN> (thư mục ep01-<slug>, media out/<project>/ep01, bỏ dòng book:);
# dự án chia quyển → q<NN>t<NN> (thư mục q01-t01-<slug>, media out/<project>/q01t01, giữ book:).
# KHÔNG đặt tên STATE.md (tên đó thuộc cinecode).
series: <project>            # slug dự án, trùng tên thư mục projects/<project>/
book: 1                      # (tuỳ chọn) số quyển; có book → mã tập q<book>t<episode>; không chia quyển thì xoá dòng này
episode: 1                   # số tập (số nguyên; chia quyển thì đánh số trong quyển)
slug: <slug>                 # slug tập, thư mục là ep<NN>-<slug> hoặc q<NN>-t<NN>-<slug>
style: <style-id>            # thường bằng style trong SERIES.md; thư mục styles/<style-id>/
length_s: 60                 # thời lượng đích (giây); shot cuối trong shots.csv kết thúc đúng số này
method: layers               # cách dựng: layers = chỉ model ảnh + chuyển động bằng code, không gọi Seedance (ai_motion trống,
                             # video_seconds: 0); seedance = clip Seedance cho cử động nhân vật. Chọn cùng người dùng ở khâu 0;
                             # sau G1 không tự đổi, phải hỏi người dùng. Thiếu dòng này = seedance (tập cũ).
                             # code = nhân vật và cảnh vẽ hoàn toàn bằng code (tools/toon/), không model nào, style engine: code,
                             # budget images: 0 và video_seconds: 0 (.claude/skills/film-compose-shot/references/code-method.md).
                             # blender = model 3D render bằng Blender trên máy của chủ lab (phiên local), style engine: blender,
                             # images: 0, shots3d/s<NN>.json mỗi shot (.claude/skills/film-compose-shot/references/blender-method.md).
# video_engine: comfy        # (tuỳ chọn, chỉ với method seedance hoặc blender) clip khâu 6: seedance (mặc định, trả tiền) hoặc
                             # comfy = clip MiniMax H3 chạy local bằng ComfyUI, miễn phí, chỉ trên máy của chủ lab
                             # (.claude/skills/film-compose-shot/references/local-video.md). Tập blender có ai_motion phải ghi khóa này.
stage: 0                     # khâu hiện tại 0..11 theo docs/WORKFLOW.md
gates: {G1: null, G2: null, G3: null, G4: null}   # ngày người dùng duyệt YYYY-MM-DD, hoặc null
media: out/<project>/q01t01  # thư mục media (git bỏ qua): out/<project>/<mã tập> (ep01 nếu không chia quyển)
drive: "ClaudeFilmLab/<ProjectName>/03_KichBan/q01-t01-<slug>"   # thư mục chữ trên Drive (ep01-<slug> nếu không chia quyển)
---

# <Tên tập>

## Ghi chú người dùng (nguyên văn)

<!-- Chép nguyên văn yêu cầu, góp ý, quyết định của người dùng; mỗi mục có ngày. Không tóm tắt, không sửa chữ. -->

## Đã khóa (không làm lại)

<!-- Thứ đã duyệt và không được tạo lại/sửa: ảnh khóa, lớp, kịch bản, giọng đọc... mỗi dòng: thứ gì, file/link, ngày,
     cổng nào. -->

## Việc tiếp theo

<!-- Danh sách việc cụ thể cho khâu hiện tại, việc đầu tiên ở trên cùng. -->

## Sinh vật của tập

<!-- Mọi sinh vật/thần của tập (khâu 1, trước vòng nghiên cứu bổ sung; docs/CONVENTIONS.md §5). Tập không có sinh vật: để
     bảng trống. slug = thư mục characters/<slug>/ = mã model A-<slug> (blender) hoặc C-<slug> (code).
     Chính: có | không (sinh vật chính cần concept duyệt trước khi dựng model, tập blender/code).
     Ảnh sách: có (ảnh chụp trang trong out/<project>/assets/refs/<slug>/book/) | không (chủ dự án xác nhận sách không có)
     | chờ. Concept: chờ | duyệt <ngày> <file> (chủ dự án chọn; ghi thêm vào characters/<slug>/CHARACTER.md
     mục "## Concept đã duyệt"). status.py: OWNER_REFS, cổng G1/G2. Tập blender/code: khung chuẩn mỗi sinh vật chính
     ghi trong STYLE-FRAMES.md (khâu 3b); mỗi sinh vật chính có ≥ 1 cận chi tiết và ≥ 1 extreme-wide trong shots.csv. -->

| slug | Tên | Chính | Ảnh sách | Concept |
|---|---|---|---|---|

## Nhật ký

<!-- Mỗi khâu một dòng: ngày | khâu | kết quả | giờ đẩy Drive (YYYY-MM-DD HH:MM UTC, hoặc "chưa"). -->

| Ngày | Khâu | Kết quả | Đẩy Drive |
|---|---|---|---|
