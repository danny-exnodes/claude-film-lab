#!/usr/bin/env python3
"""Print an AWS MCP `run_script` program that deploys the Ark image worker.

  python3 lambda/build_deploy.py > out/deploy_run.py      # also writes out/ark_image_worker.zip
  # 1. pass the file's text as `code` to the AWS MCP tool aws___run_script (creates bucket, secret, role)
  # 2. upload out/ark_image_worker.zip to the bucket key deploy/ark_image_worker.zip with a presigned URL
  # 3. run the same program again: it creates/updates the function from that object

The printed program is idempotent: it creates what is missing and updates the
Lambda code/config if it already exists. It never reads the secret's value.
The Ark API key is entered by a person in the AWS Console (Secrets Manager),
never through chat.
"""
import base64
import hashlib
import io
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
CFG = {
    "region": "ap-southeast-1",
    "bucket_prefix": "ai-film-lab",          # bucket = <prefix>-<account>-apse1
    "secret_name": "ai-film-lab/ark-api-key",
    "role_name": "ai-film-lab-ark-worker",
    "function_name": "ai-film-lab-ark-image",
    "runtime": "python3.13",
    "memory": 512,
    "timeout": 300,
}

ZIP_KEY = "deploy/ark_image_worker.zip"
ZIP_PATH = HERE.parent / "out" / "ark_image_worker.zip"

# The run_script sandbox blocks `import base64` and passes bytes to call_boto3 as text, so the zip cannot travel
# inside the program: it is written next to it and uploaded to the bucket with a presigned URL (lambda/README.md).
# Fixed timestamp and mode: the same worker source always gives the same zip, hence the same CodeSha256.
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    info = zipfile.ZipInfo("ark_image_worker.py", date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, (HERE / "ark_image_worker.py").read_bytes())
ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
ZIP_PATH.write_bytes(buf.getvalue())
CODE_SHA256 = base64.b64encode(hashlib.sha256(buf.getvalue()).digest()).decode()
print(f"zip: {ZIP_PATH} ({len(buf.getvalue())} bytes) -> s3 key {ZIP_KEY} · expected CodeSha256 {CODE_SHA256}",
      file=sys.stderr)

PROGRAM = r'''
CFG = __CFG__
ZIP_KEY = "__ZIP_KEY__"
EXPECTED_SHA256 = "__SHA__"
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

# 3. IAM role
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
            {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": secret_arn}]}))

# 4. Lambda function (code from the zip uploaded to the bucket with a presigned URL)
try:
    await c("s3", "HeadObject", Bucket=bucket, Key=ZIP_KEY)
except Exception:
    out["next"] = (f"upload out/ark_image_worker.zip to s3://{bucket}/{ZIP_KEY} (get_presigned_url, operation "
                   "upload; curl -X PUT --data-binary @out/ark_image_worker.zip <url>), then run this program again")
    out["state"] = "zip-missing"
code = {"S3Bucket": bucket, "S3Key": ZIP_KEY}
env = {"Variables": {"BUCKET": bucket, "SECRET_ID": secret_arn}}
fn = CFG["function_name"]
try:
    if out.get("state") == "zip-missing": raise RuntimeError("zip-missing")
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
    if "ResourceNotFound" not in str(e) and "zip-missing" not in str(e): raise
    last = None
    for attempt in range(0 if out.get("state") == "zip-missing" else 12):   # a new role takes a few seconds to become assumable
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
    if out.get("state") != "zip-missing": step("lambda: created")
# Async invokes: no automatic retry (a retry would bill a second image)
for _ in range(0 if out.get("state") == "zip-missing" else 30):
    st = await c("lambda", "GetFunctionConfiguration", FunctionName=fn)
    if st.get("State") == "Active" and st.get("LastUpdateStatus") != "InProgress": break
    await asyncio.sleep(2)
if out.get("state") != "zip-missing":
    await c("lambda", "PutFunctionEventInvokeConfig", FunctionName=fn, MaximumRetryAttempts=0, MaximumEventAgeInSeconds=3600)
    step("lambda: async retries disabled")
    out["function"] = fn; out["state"] = st.get("State")
    out["code_sha256"] = st.get("CodeSha256"); out["code_matches_repo"] = st.get("CodeSha256") == EXPECTED_SHA256
result = out
result
'''

print(PROGRAM.replace("__CFG__", repr(CFG)).replace("__ZIP_KEY__", ZIP_KEY).replace("__SHA__", CODE_SHA256).strip())
