#!/usr/bin/env python3
"""Print an AWS MCP `run_script` program that deploys the Ark image worker.

  python3 lambda/build_deploy.py > out/deploy_run.py      # also writes out/ark_image_worker.zip
  # 1. pass the file's text as `code` to the AWS MCP tool aws___run_script (creates bucket, secret, role)
  # 2. upload out/ark_image_worker.zip to the bucket key deploy/ark_image_worker.zip with a presigned URL
  # 3. run the same program again: it creates/updates the function from that object

  python3 lambda/build_deploy.py --check                  # expected CodeSha256 + worker sha256, writes nothing

The printed program is idempotent: it creates what is missing and updates the
Lambda code/config if it already exists. It never reads the secret's value.
The Ark API key is entered by a person in the AWS Console (Secrets Manager),
never through chat.

The program knows the zip it was built with: a bucket object with another MD5 gives state `zip-stale` (nothing is
installed), and a function whose CodeSha256 is not the expected one at the end gives state `code-mismatch`.
"""
import argparse
import base64
import hashlib
import io
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
WORKER = HERE / "ark_image_worker.py"
CFG = {
    "region": "ap-southeast-1",
    "bucket_prefix": "ai-film-lab",          # bucket = <prefix>-<account>-apse1
    "secret_name": "ai-film-lab/ark-api-key",
    "role_name": "ai-film-lab-ark-worker",
    "function_name": "ai-film-lab-ark-image",
    "runtime": "python3.13",
    "memory": 512,
    "timeout": 900,                          # Lambda's maximum; only the time used is billed
    "event_age": 300,                        # an async event that could not start within 5 min is dropped
}

ZIP_KEY = "deploy/ark_image_worker.zip"
ZIP_PATH = HERE.parent / "out" / "ark_image_worker.zip"


def build_zip():
    """The worker as zip bytes. Fixed timestamp and mode: the same worker source always gives the same zip, hence
    the same CodeSha256 and the same S3 ETag."""
    # The run_script sandbox blocks `import base64` and passes bytes to call_boto3 as text, so the zip cannot
    # travel inside the program: it is written next to it and uploaded to the bucket with a presigned URL
    # (lambda/README.md).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("ark_image_worker.py", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, WORKER.read_bytes())
    return buf.getvalue()


def code_sha256(zip_bytes):
    """CodeSha256 as Lambda reports it for this zip."""
    return base64.b64encode(hashlib.sha256(zip_bytes).digest()).decode()


def worker_sha256():
    """What the worker writes as `worker_sha256` into every status (= sha256sum lambda/ark_image_worker.py)."""
    return hashlib.sha256(WORKER.read_bytes()).hexdigest()


PROGRAM = r'''
CFG = __CFG__
ZIP_KEY = "__ZIP_KEY__"
EXPECTED_SHA256 = "__SHA__"
ZIP_MD5 = "__MD5__"
R = CFG["region"]
out = {"steps": []}

def step(msg): out["steps"].append(msg)

async def c(service, op, region=R, **params):
    return await call_boto3(service_name=service, operation_name=op, region_name=region, params=params or None)

acct = (await c("sts", "GetCallerIdentity"))["Account"]
bucket = f'{CFG["bucket_prefix"]}-{acct}-apse1'
out["account"] = acct; out["bucket"] = bucket

# 1. S3 bucket (private)
try:
    await c("s3", "HeadBucket", Bucket=bucket); step(f"bucket {bucket}: exists")
except Exception:
    await c("s3", "CreateBucket", Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": R})
    step(f"bucket {bucket}: created")
await c("s3", "PutPublicAccessBlock", Bucket=bucket, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})

# 2. Secret (placeholder only; a person sets the real value in the console)
try:
    sec = await c("secretsmanager", "DescribeSecret", SecretId=CFG["secret_name"]); step("secret: exists")
except Exception:
    sec = await c("secretsmanager", "CreateSecret", Name=CFG["secret_name"],
                  Description="BytePlus Ark API key for AI Film Lab (set the value in the console)",
                  SecretString="REPLACE_WITH_ARK_API_KEY")
    step("secret: created with placeholder - set the real value in the AWS Console")
secret_arn = sec["ARN"]

# 3. IAM role (s3:ListBucket on the bucket: a missing key then answers NoSuchKey instead of AccessDenied)
trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
new_role = False
try:
    role = (await c("iam", "GetRole", RoleName=CFG["role_name"]))["Role"]; step("role: exists")
except Exception:
    role = (await c("iam", "CreateRole", RoleName=CFG["role_name"], AssumeRolePolicyDocument=trust,
                    Description="AI Film Lab Ark image worker"))["Role"]
    new_role = True; step("role: created")
await c("iam", "AttachRolePolicy", RoleName=CFG["role_name"],
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
await c("iam", "PutRolePolicy", RoleName=CFG["role_name"], PolicyName="film-lab-worker",
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": f"arn:aws:s3:::{bucket}/*"},
            {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": f"arn:aws:s3:::{bucket}"},
            {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": secret_arn}]}))

# 4. Lambda function (code from the zip uploaded to the bucket with a presigned URL)
upload = (f"upload out/ark_image_worker.zip to s3://{bucket}/{ZIP_KEY} (get_presigned_url, operation "
          "upload; curl -fsS -X PUT --data-binary @out/ark_image_worker.zip <url>), then run this program again")
try:
    head = await c("s3", "HeadObject", Bucket=bucket, Key=ZIP_KEY)
    etag = str(head.get("ETag") or "").strip('"').lower()
    # A plain ETag is the object's MD5. Multipart or KMS ETags have another shape: left to the check at the end.
    if len(etag) == 32 and all(ch in "0123456789abcdef" for ch in etag) and etag != ZIP_MD5:
        out["state"] = "zip-stale"
        out["next"] = "the bucket holds another zip than this program was built with: " + upload
except Exception:
    out["state"] = "zip-missing"
    out["next"] = upload
blocked = out.get("state") in ("zip-missing", "zip-stale")   # nothing is created or updated from a wrong zip
code = {"S3Bucket": bucket, "S3Key": ZIP_KEY}
env = {"Variables": {"BUCKET": bucket, "SECRET_ID": secret_arn}}
fn = CFG["function_name"]
try:
    if blocked: raise RuntimeError("zip-blocked")
    await c("lambda", "GetFunction", FunctionName=fn)
    await c("lambda", "UpdateFunctionCode", FunctionName=fn, **code)
    for _ in range(30):
        st = await c("lambda", "GetFunctionConfiguration", FunctionName=fn)
        if st.get("LastUpdateStatus") != "InProgress": break
        await asyncio.sleep(2)
    await c("lambda", "UpdateFunctionConfiguration", FunctionName=fn, Runtime=CFG["runtime"],
            Handler="ark_image_worker.handler", MemorySize=CFG["memory"], Timeout=CFG["timeout"], Environment=env)
    step("lambda: updated")
except Exception as e:
    if "ResourceNotFound" not in str(e) and "zip-blocked" not in str(e): raise
    last = None
    for attempt in range(0 if blocked else 12):   # a new role takes a few seconds to become assumable
        try:
            await c("lambda", "CreateFunction", FunctionName=fn, Runtime=CFG["runtime"], Role=role["Arn"],
                    Handler="ark_image_worker.handler", Code=code,
                    MemorySize=CFG["memory"], Timeout=CFG["timeout"], Environment=env,
                    Description="AI Film Lab: BytePlus Ark image generation outside the 30 s proxy")
            last = None; break
        except Exception as e2:
            last = e2
            if "role" in str(e2).lower() and "assume" in str(e2).lower():
                await asyncio.sleep(5); continue
            raise
    if last: raise last
    if not blocked: step("lambda: created")
# Async invokes: no automatic retry (a retry would bill a second image)
for _ in range(0 if blocked else 30):
    st = await c("lambda", "GetFunctionConfiguration", FunctionName=fn)
    if st.get("State") == "Active" and st.get("LastUpdateStatus") != "InProgress": break
    await asyncio.sleep(2)
if not blocked:
    await c("lambda", "PutFunctionEventInvokeConfig", FunctionName=fn, MaximumRetryAttempts=0,
            MaximumEventAgeInSeconds=CFG["event_age"])
    step("lambda: async retries disabled")
    out["function"] = fn; out["state"] = st.get("State")
    out["code_sha256"] = st.get("CodeSha256"); out["code_matches_repo"] = st.get("CodeSha256") == EXPECTED_SHA256
    if not out["code_matches_repo"]:
        out["state"] = "code-mismatch"
        out["error"] = (f"the function runs CodeSha256 {st.get('CodeSha256')}, this repo's worker is "
                        f"{EXPECTED_SHA256}: do not invoke; build again, upload the zip, run this program again")
result = out
result
'''


def render_program(zip_bytes):
    """The run_script program for this zip (its CodeSha256 and MD5 are embedded)."""
    return (PROGRAM.replace("__CFG__", repr(CFG)).replace("__ZIP_KEY__", ZIP_KEY)
            .replace("__SHA__", code_sha256(zip_bytes)).replace("__MD5__", hashlib.md5(zip_bytes).hexdigest())
            .strip())


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the worker zip and print the AWS MCP run_script program that deploys it "
                    "(program on stdout, summary on stderr). Steps: lambda/README.md.")
    ap.add_argument("--zip-out", metavar="PATH", default=str(ZIP_PATH),
                    help="where to write the worker zip (default: out/ark_image_worker.zip in the repo)")
    ap.add_argument("--check", action="store_true",
                    help="print the expected CodeSha256 and the worker sha256 only; write nothing")
    args = ap.parse_args(argv)
    data = build_zip()
    if args.check:
        print(f"CodeSha256 {code_sha256(data)}")
        print(f"worker_sha256 {worker_sha256()}")
        return 0
    zip_path = pathlib.Path(args.zip_out)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(data)
    print(f"zip: {zip_path} ({len(data)} bytes) -> s3 key {ZIP_KEY} · expected CodeSha256 {code_sha256(data)} · "
          f"worker sha256 {worker_sha256()}", file=sys.stderr)
    print(render_program(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
