# Lambda: tạo ảnh Ark ngoài proxy (pro, 4K)

`ark_image_worker.py` chạy trên AWS Lambda (`ap-southeast-1`, Python 3.13, 512 MB, timeout 300 s), gọi API ảnh
Ark trực tiếp nên không bị giới hạn 30 s của proxy cloud. Kết quả ghi vào S3:

- `images/<job_id>.<png|jpg>` – ảnh
- `jobs/<job_id>.json` – trạng thái `running` → `succeeded` | `failed` (model, usage, seconds, error)

**Quy tắc:** một lần gọi Lambda đi thẳng tới Ark, không qua `ark.py image`, nên **mọi job phải đi qua
`ark.py lambda-job prepare` → Invoke → `ark.py lambda-job finish`**. Không có ledger thì không gọi Lambda; `job_id`
luôn là id do `prepare` in ra (worker bỏ qua `job_id` đã có `jobs/<job_id>.json`, nên gọi lặp không tạo ảnh thứ hai).

## Triển khai (một lần, hoặc sau khi sửa worker) – qua AWS MCP
Cần connector **AWS MCP** nạp được trong phiên (tool `aws___run_script`, `aws___get_presigned_url`). Connector báo
`needs_reconnect` hoặc không có tool → người dùng kết nối lại trong claude.ai, rồi thử lại (`docs/RUNBOOK.md`).

Sandbox của `run_script` chặn `import base64` và truyền `bytes` cho `call_boto3` thành chuỗi, nên **không đưa được file
nhị phân qua chương trình**: file zip của worker đi qua S3 bằng link ký sẵn.
1. `python3 lambda/build_deploy.py > out/deploy_run.py` – ghi thêm `out/ark_image_worker.zip` và in `CodeSha256` mong đợi.
2. Đưa nội dung `out/deploy_run.py` làm `code` cho tool `aws___run_script`. Chương trình idempotent: tạo
   bucket `ai-film-lab-<account>-apse1`, secret `ai-film-lab/ark-api-key` (giá trị giả), role
   `ai-film-lab-ark-worker`. Lần đầu (hoặc khi chưa tải zip) kết quả có `state: zip-missing` và tên bucket.
3. `aws___get_presigned_url` (`operation: upload`, key `deploy/ark_image_worker.zip`), rồi trong container:
   `curl -sS -X PUT --data-binary @out/ark_image_worker.zip "<url>"` (200).
4. Chạy lại đúng chương trình ở bước 2: tạo hoặc cập nhật function `ai-film-lab-ark-image` từ object đó, tắt retry khi
   invoke bất đồng bộ. Kết quả phải có `state: Active` và `code_matches_repo: true`.
5. **Người dùng** mở AWS Console → Secrets Manager → `ai-film-lab/ark-api-key` → nhập API key Ark (plain text).
   Tạo key ở Ark Console → API Keys. Không dán key vào chat; Claude không đọc giá trị secret.

## Một job, từ đầu đến cuối
```bash
# 1. Kiểm ngân sách + giữ chỗ (dòng pending) + in payload. Vượt trần → thoát mã 3, không in payload.
python3 tools/ark.py lambda-job prepare "<prompt>" out/<project>/ep<NN>/plates/<tên>.png \
    --model dola-seedream-5-0-pro-260628 --size 2K [--ref <ảnh khóa>.png] \
    --payload out/<project>/ep<NN>/lambda/payload.json \
    --budget projects/<project>/ep<NN>-<slug>/budget.yaml --ledger out/<project>/ep<NN>/ledger.csv
```
- Trong agent thêm `FILM_AGENT=<tên agent>` như mọi lệnh tạo ảnh. `--size 4K` cho L1 4K.
- Có `--ref`: ảnh được nén như `image --ref` (JPEG q90, cạnh dài ≤ 2048) vào `<thư mục out>/lambda-refs/<job_id>-<n>.jpg`;
  tải từng file lên bucket đúng key `refs/<job_id>-<n>.jpg` (payload đã có `ref_keys`) **trước** khi Invoke, bằng
  `aws___get_presigned_url` (`operation: upload`) + `curl -X PUT --data-binary @<file> "<url>"`.

2. Invoke **một lần** với đúng payload đó (`aws___run_script`):
```python
payload = {...}   # nguyên văn JSON do `lambda-job prepare` in ra (job_id = req id trong ledger)
r = await call_boto3(service_name="lambda", operation_name="Invoke", region_name="ap-southeast-1",
                     params={"FunctionName": "ai-film-lab-ark-image", "InvocationType": "Event",
                             "Payload": json.dumps(payload)})
result = {"status": r.get("StatusCode")}   # 202 = đã nhận
result
```
3. Mỗi ~15 s: `aws___get_presigned_url` (`operation: download`) cho `jobs/<job_id>.json`, `curl -sS -o
   out/<project>/ep<NN>/lambda/<job_id>.json "<url>"`, đến khi `status` là `succeeded`/`failed` (404 = worker chưa
   bắt đầu). Link ký sẵn sống 15 phút, dùng lại được trong lúc chờ.
4. Lấy link tải bằng tool `aws___get_presigned_url` cho `images/<job_id>.<ext>` (key nằm trong `keys` của JSON), rồi trong container:
   `curl -sS -o out/<project>/ep<NN>/lambda/<job_id>.jpg "<presigned url>"` (S3 `ap-southeast-1` truy cập được từ container).
5. Ghi dòng cuối vào ledger và lưu ảnh về đúng tên (đổi định dạng theo đuôi file như `ark.py image`):
```bash
python3 tools/ark.py lambda-job finish --status-json out/<project>/ep<NN>/lambda/<job_id>.json \
    --image out/<project>/ep<NN>/lambda/<job_id>.jpg --ledger out/<project>/ep<NN>/ledger.csv
```
   `succeeded` → dòng `ok` (usage, `lambda; seconds=…`); `failed` → dòng `failed` (vẫn tính, không tự thử lại);
   `running` → không ghi gì, thoát mã 1 (đọc lại sau). Chạy `finish` lần hai không thêm dòng.

Job đã `prepare` mà không Invoke (hoặc không `finish`) để lại dòng `pending`: vẫn tính vào trần như mọi request bị bỏ dở
(`docs/CONVENTIONS.md` §7). Invoke xong mới biết lỗi cấu hình (chưa nhập khóa…) thì `finish` với `jobs/<job_id>.json`
báo `failed` để đóng request.

## Chi phí
AWS: vài giây Lambda + vài MB S3 mỗi ảnh (không đáng kể). Phí tạo ảnh tính bên BytePlus như thường; trần riêng của
model pro đặt ở `models.dola-seedream-5-0-pro-260628` trong `budget.yaml` của tập.

## Trạng thái
**Đã triển khai 2026-11-10** (tài khoản `…7711`, `ap-southeast-1`): bucket, secret (giá trị giả), role và function
`ai-film-lab-ark-image` ở trạng thái `Active`, `CodeSha256` khớp repo. **Chưa thử ảnh thật** (issue #13 bước 3): chờ
người dùng nhập khóa Ark vào secret; thời gian thực tế của pro 2K / 4K sẽ ghi vào `docs/MODELS.md` sau lần thử đầu.
