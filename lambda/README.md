# Lambda: tạo ảnh Ark ngoài proxy (pro, 4K)

`ark_image_worker.py` chạy trên AWS Lambda (`ap-southeast-1`, Python 3.13, 512 MB, timeout 900 s – chỉ tính tiền
thời gian chạy thật), gọi API ảnh Ark trực tiếp nên không bị giới hạn 30 s của proxy cloud. Kết quả ghi vào S3:

- `images/<job_id>.<png|jpg>` – ảnh
- `jobs/<job_id>.json` – trạng thái `running` → `succeeded` | `failed` (model, usage, seconds, error) và:
  - `sent` – `false` cho tới lúc request đi tới Ark. Job `failed` có `sent: false` (secret sai dạng, thiếu ảnh
    tham chiếu, thiếu prompt) **chưa gửi gì, không tạo ảnh**; `sent: true` thì coi như có thể đã tính phí.
    `lambda-job finish` ghi job `sent: false` là `failed-unsent` (đóng request, không tính vào trần), còn lại là `failed`
    (vẫn tính).
  - `deadline` (khi `running`) – giây epoch mà Lambda sẽ cắt lần chạy này. Quá `deadline` + 60 s mà vẫn `running`
    thì worker đã chết (hết giờ/hết bộ nhớ): **ngừng đọc lại**, không Invoke lại, báo người dùng. `lambda-job finish`
    nhận ra trường hợp này (thoát mã 1, in lệnh); đóng request bằng `lambda-job finish … --give-up` (dòng `failed`,
    vẫn tính).
  - `worker_sha256` – sha256 của file worker đang chạy; phải bằng `sha256sum lambda/ark_image_worker.py`
    (hoặc `python3 lambda/build_deploy.py --check`). Khác → đang chạy bản cũ, triển khai lại trước job kế tiếp.
    `lambda-job finish` so trường này với file trong repo và in `WARN` khi khác (hoặc khi thiếu).

**Quy tắc:** một lần gọi Lambda đi thẳng tới Ark, không qua `ark.py image`, nên **mọi job phải đi qua
`ark.py lambda-job prepare` → Invoke → `ark.py lambda-job finish`**. Không có ledger thì không gọi Lambda; `job_id`
luôn là id do `prepare` in ra (32 chữ số hex). Worker từ chối event không có id dạng đó (`{"error": "no job_id: use
ark.py lambda-job prepare"}`, không ghi gì, không gửi gì) và giữ chỗ `jobs/<job_id>.json` bằng ghi có điều kiện, nên
gọi lặp hay giao lại cùng `job_id` chỉ trả `skipped: duplicate`, không tạo ảnh thứ hai.

Khóa Ark được đọc lại từ Secrets Manager **mỗi job** (đổi khóa xong là dùng được ngay, không cần chờ hay triển khai
lại), kiểm dạng trước khi dùng (một dòng, ASCII in được, không khoảng trắng, ≥ 20 ký tự, không phải giá trị giả) và
bị xoá khỏi mọi thông báo lỗi. Lỗi `secret … is empty, a placeholder or malformed` → người dùng nhập lại khóa ở Console.

## Triển khai (một lần, hoặc sau khi sửa worker) – qua AWS MCP
Cần connector **AWS MCP** nạp được trong phiên (tool `aws___run_script`, `aws___get_presigned_url`). Connector báo
`needs_reconnect` hoặc không có tool → người dùng kết nối lại trong claude.ai, rồi thử lại (`docs/RUNBOOK.md`).

Sandbox của `run_script` chặn `import base64` và truyền `bytes` cho `call_boto3` thành chuỗi, nên **không đưa được file
nhị phân qua chương trình**: file zip của worker đi qua S3 bằng link ký sẵn.
1. `python3 lambda/build_deploy.py > out/deploy_run.py` – ghi thêm `out/ark_image_worker.zip` và in `CodeSha256` mong đợi
   (stderr). `--zip-out <file>` đổi nơi ghi zip; `--check` chỉ in `CodeSha256` và sha256 của worker, không ghi gì.
2. Đưa nội dung `out/deploy_run.py` làm `code` cho tool `aws___run_script`. Chương trình idempotent: tạo
   bucket `ai-film-lab-<account>-apse1`, secret `ai-film-lab/ark-api-key` (giá trị giả), role
   `ai-film-lab-ark-worker`. Lần đầu (hoặc khi chưa tải zip) kết quả có `state: zip-missing` và tên bucket.
3. `aws___get_presigned_url` (`operation: upload`, key `deploy/ark_image_worker.zip`), rồi trong container:
   `curl -fsS -X PUT --data-binary @out/ark_image_worker.zip "<url>"` (200).
4. Chạy lại đúng chương trình ở bước 2: tạo hoặc cập nhật function `ai-film-lab-ark-image` từ object đó, tắt retry khi
   invoke bất đồng bộ (event quá 300 s chưa chạy thì bỏ). Kết quả phải có `state: Active` và `code_matches_repo: true`.
   `state: zip-stale` = bucket đang giữ zip khác bản vừa build (chưa tải bản mới): chương trình **không** cập nhật
   function; làm lại bước 3 rồi bước 4. `state: code-mismatch` (có dòng `error`) = function đang chạy mã khác repo:
   không Invoke; build lại, tải zip, chạy lại.
5. **Người dùng** mở AWS Console → Secrets Manager → `ai-film-lab/ark-api-key` → nhập API key Ark (plain text).
   Tạo key ở Ark Console → API Keys. Không dán key vào chat; Claude không đọc giá trị secret.

### Triển khai lại sau khi sửa `ark_image_worker.py`
Sửa worker đổi `CodeSha256`; function trên AWS vẫn chạy bản cũ cho tới khi làm đủ: bước 1 (build lại – chương trình
mới mang MD5 của zip mới) → bước 3 (tải zip mới) → bước 4 (chạy chương trình **mới**; cũng nâng timeout 900 s, thêm
`s3:ListBucket` cho role). Chạy bước 4 mà quên bước 3 → `zip-stale`, function không bị đổi. Kiểm sau cùng:
`code_matches_repo: true`, và `worker_sha256` trong status của job kế tiếp bằng `sha256sum lambda/ark_image_worker.py`.
Secret và khóa không bị đụng tới.

## Một job, từ đầu đến cuối
```bash
# 1. Kiểm ngân sách + giữ chỗ (dòng pending) + in payload. Vượt trần → thoát mã 3, không in payload.
python3 tools/ark.py lambda-job prepare "<prompt>" out/<project>/ep<NN>/plates/<tên>.png \
    --model dola-seedream-5-0-pro-260628 --size 2K [--ref <ảnh khóa>.png] \
    --payload out/<project>/ep<NN>/lambda/payload.json \
    --budget projects/<project>/ep<NN>-<slug>/budget.yaml --ledger out/<project>/ep<NN>/ledger.csv
```
- Trong agent thêm `FILM_AGENT=<tên agent>` như mọi lệnh tạo ảnh. Kích thước có tên (`2K`, `4K`) **không cố định tỉ
  lệ** (lần thử 2K trả 1664x2496, ảnh dọc): cần khung ngang thì truyền `--size <rộng>x<cao>`.
- Có `--ref`: ảnh được nén như `image --ref` (JPEG q90, cạnh dài ≤ 2048) vào `<thư mục out>/lambda-refs/<job_id>-<n>.jpg`;
  tải từng file lên bucket đúng key `refs/<job_id>-<n>.jpg` (payload đã có `ref_keys`) **trước** khi Invoke, bằng
  `aws___get_presigned_url` (`operation: upload`) + `curl -fsS -X PUT --data-binary @<file> "<url>"`. Thiếu file →
  job `failed`, `sent: false`, lỗi `ref not in bucket: <key>: upload it, then prepare a new job` (`job_id` đó không
  chạy lại được: tải ảnh lên rồi `prepare` job mới).

2. Invoke **một lần** với đúng payload đó (`aws___run_script`):
```python
payload = {...}   # nguyên văn JSON do `lambda-job prepare` in ra (job_id = req id trong ledger)
r = await call_boto3(service_name="lambda", operation_name="Invoke", region_name="ap-southeast-1",
                     params={"FunctionName": "ai-film-lab-ark-image", "InvocationType": "Event",
                             "Payload": json.dumps(payload)})
result = {"status": r.get("StatusCode")}   # 202 = đã nhận
result
```
3. Mỗi ~15 s: `aws___get_presigned_url` (`operation: download`) cho `jobs/<job_id>.json`, `curl -fsS -o
   out/<project>/ep<NN>/lambda/<job_id>.json "<url>"`, đến khi `status` là `succeeded`/`failed`. `-f` là bắt buộc:
   không có nó, trang lỗi XML của S3 bị lưu thành file status (curl thoát mã 22 với 404 = worker chưa bắt đầu, 403 =
   link hết hạn → xin link mới). Link ký sẵn sống 15 phút, dùng lại được trong lúc chờ. **Ngừng đọc lại** khi quá
   `deadline` + 60 s (trường `deadline` trong status `running`; chưa có status nào sau 6 phút kể từ Invoke cũng ngừng).
4. Lấy link tải bằng tool `aws___get_presigned_url` cho `images/<job_id>.<ext>` (key nằm trong `keys` của JSON), rồi trong container:
   `curl -fsS -o out/<project>/ep<NN>/lambda/<job_id>.jpg "<presigned url>"` (S3 `ap-southeast-1` truy cập được từ container).
5. Ghi dòng cuối vào ledger và lưu ảnh về đúng tên (đổi định dạng theo đuôi file như `ark.py image`):
```bash
python3 tools/ark.py lambda-job finish --status-json out/<project>/ep<NN>/lambda/<job_id>.json \
    --image out/<project>/ep<NN>/lambda/<job_id>.jpg --ledger out/<project>/ep<NN>/ledger.csv
```
   `succeeded` → dòng `ok` (usage, `lambda; seconds=…`); `failed` → dòng `failed` (vẫn tính, không tự thử lại), hoặc
   `failed-unsent` khi `sent: false` (không tính; sửa nguyên nhân rồi `prepare` job mới); `running` → không ghi gì,
   thoát mã 1 (đọc lại sau); `running` quá `deadline` + 60 s → thoát mã 1 kèm lệnh `… --give-up` (dòng `failed`, vẫn
   tính). File status không phải object JSON, hoặc `--image` không phải ảnh PNG/JPEG/WebP/GIF (trang lỗi XML của S3 khi
   `curl` thiếu `-f`) → thoát mã 2, không ghi gì: tải lại bằng `curl -fsS -o` rồi chạy lại. Chạy `finish` lần hai không
   thêm dòng.

Job đã `prepare` mà không Invoke (hoặc không `finish`) để lại dòng `pending`: vẫn tính vào trần như mọi request bị bỏ dở
(`docs/CONVENTIONS.md` §7). Chắc chắn không Invoke nữa → đóng nó: `python3 tools/ark.py ledger-close --req <job_id>
--ledger <ledger> --status abandoned` (dòng `abandoned`, vẫn tính; `tools/status.py` hết báo OPEN). Invoke xong mới biết
lỗi cấu hình (chưa nhập khóa…) thì `finish` với `jobs/<job_id>.json` báo `failed` để đóng request (`sent: false` →
`failed-unsent`, không tính).

## Chi phí
AWS: vài giây Lambda + vài MB S3 mỗi ảnh (không đáng kể). Phí tạo ảnh tính bên BytePlus như thường; trần riêng của
model pro đặt ở `models.dola-seedream-5-0-pro-260628` trong `budget.yaml` của tập.

## Trạng thái
**Đã triển khai 2026-11-10** (tài khoản `…7711`, `ap-southeast-1`): bucket, secret, role và function
`ai-film-lab-ark-image`. **Ảnh thật đầu tiên đã tạo 2026-11-10** (issue #13 bước 3): Pro 2K, 77 s, trả về 1664x2496 –
kích thước có tên không cố định tỉ lệ, luôn truyền `<rộng>x<cao>`. 4K chưa đo.

**Worker đã gia cố được triển khai lại 2026-11-11**: timeout 900 s, `CodeSha256` khớp repo
(`python3 lambda/build_deploy.py --check`). Chưa có job nào chạy trên bản này: status của job đầu tiên phải có
`worker_sha256` khớp repo, và nên xem nó có `sent`/`deadline` để biết đường ghi có điều kiện hoạt động.
