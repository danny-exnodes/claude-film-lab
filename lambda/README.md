# Lambda: tạo ảnh Ark ngoài proxy (pro, 4K)

`ark_image_worker.py` chạy trên AWS Lambda (`ap-southeast-1`, Python 3.13, 512 MB, timeout 300 s), gọi API ảnh
Ark trực tiếp nên không bị giới hạn 30 s của proxy cloud. Kết quả ghi vào S3:

- `images/<job_id>.<png|jpg>` – ảnh
- `jobs/<job_id>.json` – trạng thái `running` → `succeeded` | `failed` (model, usage, seconds, error)

## Triển khai (một lần, hoặc sau khi sửa worker) – qua AWS MCP
1. `python3 lambda/build_deploy.py > out/deploy_run.py`
2. Đưa nội dung `out/deploy_run.py` làm `code` cho tool `aws___run_script`. Chương trình idempotent: tạo
   bucket `ai-film-lab-<account>-apse1`, secret `ai-film-lab/ark-api-key` (giá trị giả), role
   `ai-film-lab-ark-worker`, function `ai-film-lab-ark-image`; tắt retry khi invoke bất đồng bộ.
3. **Người dùng** mở AWS Console → Secrets Manager → `ai-film-lab/ark-api-key` → nhập API key Ark (plain text).
   Tạo key ở Ark Console → API Keys. Không dán key vào chat.

## Gọi một job (aws___run_script)
```python
payload = {"job_id": "pro-test-01", "prompt": "…", "model": "dola-seedream-5-0-pro-260628", "size": "2K"}
r = await call_boto3(service_name="lambda", operation_name="Invoke", region_name="ap-southeast-1",
                     params={"FunctionName": "ai-film-lab-ark-image", "InvocationType": "Event",
                             "Payload": json.dumps(payload)})
result = {"status": r.get("StatusCode")}   # 202 = đã nhận
result
```
Ảnh tham chiếu: tải lên `refs/…` trong bucket rồi truyền `"ref_keys": ["refs/a.png"]`.

## Theo dõi và tải về
- Đọc `jobs/<job_id>.json` bằng `GetObject` (run_script) mỗi ~15 s đến khi `succeeded`/`failed`.
- Lấy link tải bằng tool `aws___get_presigned_url` cho `images/<job_id>.<ext>`, rồi trong container:
  `curl -sS -o out/<dự án>/<shot>.png "<presigned url>"` (S3 `ap-southeast-1` truy cập được từ container).

## Chi phí
AWS: vài giây Lambda + vài MB S3 mỗi ảnh (không đáng kể). Phí tạo ảnh tính bên BytePlus như thường.
