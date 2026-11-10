"""AI Film Lab - Ark image worker (AWS Lambda, python3.13).

Runs BytePlus ModelArk image generation outside the Claude cloud proxy, so slow
models (dola-seedream-5-0-pro) and 4K sizes are not cut at ~30 s.

Invoke asynchronously (InvocationType=Event) with the payload printed by `tools/ark.py lambda-job prepare`:
  {"job_id": "<32 hex digits>", "prompt": "...", "model": "dola-seedream-5-0-pro-260628",
   "size": "2K", "ref_keys": ["refs/<job_id>-1.jpg"]}   # ref_keys optional, S3 keys in BUCKET

Writes to s3://$BUCKET:
  images/<job_id>.<ext>   (and images/<job_id>-<n>.<ext> for extra images)
  jobs/<job_id>.json      status: running -> succeeded | failed, plus model, usage, seconds, error and
                          sent           false until the request to Ark goes out: a failed job with sent=false
                                         generated nothing
                          deadline       (running) epoch seconds at which Lambda kills this invocation: a status
                                         still `running` after it is dead
                          worker_sha256  sha256 of this file, to compare with `sha256sum lambda/ark_image_worker.py`

job_id is the request id printed by `lambda-job prepare` (which also checks the episode budget and writes the
ledger's pending row); `lambda-job finish` reads jobs/<job_id>.json back into the ledger. An event without such an
id is refused before anything is read, written or sent. The job is claimed by creating jobs/<job_id>.json with a
conditional write, so a job_id that already has a status is NOT run again (Lambda delivers async events at least
once; a second run would bill a second image): the handler returns {"skipped": "duplicate"}.

The Ark key is read from Secrets Manager on every invocation, checked for shape before use, and removed from
every error text before it is stored or raised.

Env: BUCKET, SECRET_ID (Secrets Manager secret holding the Ark API key as plain
text), ARK_BASE (default https://ark.ap-southeast.bytepluses.com/api/v3).
"""
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

import boto3

S3 = boto3.client("s3")
SM = boto3.client("secretsmanager")
BUCKET = os.environ["BUCKET"]
SECRET_ID = os.environ["SECRET_ID"]
ARK_BASE = os.environ.get("ARK_BASE", "https://ark.ap-southeast.bytepluses.com/api/v3")
DEFAULT_MODEL = "dola-seedream-5-0-pro-260628"
PLACEHOLDER = "REPLACE_WITH_ARK_API_KEY"
JOB_ID = re.compile(r"[0-9a-f]{32}")                 # tools/ark.py new_req()
KEY_SHAPE = re.compile(r"[\x21-\x7e]{20,}")          # one line, printable ASCII, no spaces
MISSING = {"NoSuchKey", "404", "NotFound", "AccessDenied", "403"}   # S3 answers 403 for a missing key without ListBucket
TAKEN = {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}
with open(__file__, "rb") as _f:
    WORKER_SHA256 = hashlib.sha256(_f.read()).hexdigest()


def aws_code(e):
    """Error code of an AWS exception without importing botocore: ClientError carries it in `response`."""
    resp = getattr(e, "response", None)
    if isinstance(resp, dict):
        code = (resp.get("Error") or {}).get("Code")
        if code:
            return str(code)
    return type(e).__name__


def fetch_secret():
    """The secret as stored, ends trimmed. Read on every invocation: a warm instance must not keep an old key."""
    return (SM.get_secret_value(SecretId=SECRET_ID).get("SecretString") or "").strip()


def redact(text, secret):
    """`text` without the key: every occurrence of the secret (and of each of its lines), then everything from the
    first 'Bearer ' on (http.client quotes the whole header value when it refuses it)."""
    secret = secret or ""
    for part in [secret] + [p for p in secret.split() if len(p) >= 6]:
        if part:
            text = text.replace(part, "<redacted>")
    i = text.find("Bearer ")
    return text if i < 0 else text[:i] + "Bearer <redacted>"


def sniff(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "bin", "application/octet-stream"


def put_status(job_id, _create_only=False, **fields):
    extra = {"IfNoneMatch": "*"} if _create_only else {}
    S3.put_object(Bucket=BUCKET, Key=f"jobs/{job_id}.json", ContentType="application/json",
                  Body=json.dumps({"job_id": job_id, "worker_sha256": WORKER_SHA256, **fields},
                                  ensure_ascii=False).encode(), **extra)


def existing_status(job_id):
    """The job's status object, or None when it does not exist (NoSuchKey, or AccessDenied while the role has no
    s3:ListBucket). Any other S3 error is raised: 'could not read' must never be taken for 'not seen'."""
    try:
        return json.loads(S3.get_object(Bucket=BUCKET, Key=f"jobs/{job_id}.json")["Body"].read())
    except Exception as e:
        if aws_code(e) in MISSING:
            return None
        raise


def claim(job_id, **fields):
    """Create the running status. True: this invocation owns the job. False: a status already exists."""
    try:
        put_status(job_id, _create_only=True, **fields)
        return True
    except Exception as e:
        if aws_code(e) in TAKEN:
            return False
        if type(e).__name__ != "ParamValidationError":
            raise
    # The runtime's botocore does not know IfNoneMatch: read, then write (not atomic).
    if existing_status(job_id) is not None:
        return False
    put_status(job_id, **fields)
    return True


def ref_data_uri(key):
    try:
        raw = S3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception as e:
        if aws_code(e) in MISSING:
            raise RuntimeError(f"ref not in bucket: {key}: upload it, then prepare a new job") from None
        raise
    return f"data:{sniff(raw)[1]};base64," + base64.b64encode(raw).decode()


def handler(event, context):
    job_id = event.get("job_id") if isinstance(event, dict) else None
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        # Not from `lambda-job prepare`: no ledger row, no duplicate guard. Nothing is read, written or sent.
        return {"error": "no job_id: use ark.py lambda-job prepare"}
    model = event.get("model") or DEFAULT_MODEL
    t0 = time.time()
    running = {"status": "running", "model": model, "started": t0,
               "deadline": round(t0 + context.get_remaining_time_in_millis() / 1000, 1)}
    if not claim(job_id, sent=False, **running):
        # duplicate delivery or a repeated invoke: never generate (and bill) twice
        try:
            seen = existing_status(job_id) or {}
        except Exception:
            seen = {}
        return {"job_id": job_id, "skipped": "duplicate", "status": seen.get("status")}
    sent, secret, error = False, None, None
    try:
        if not event.get("prompt"):
            raise RuntimeError("no prompt in the event")
        body = {"model": model, "prompt": event["prompt"], "size": event.get("size", "2K"),
                "response_format": "b64_json", "watermark": False}
        refs = event.get("ref_keys") or []
        if refs:
            uris = [ref_data_uri(k) for k in refs]
            body["image"] = uris if len(uris) > 1 else uris[0]
        secret = fetch_secret()
        if secret == PLACEHOLDER or not KEY_SHAPE.fullmatch(secret):
            raise RuntimeError(f"secret {SECRET_ID} is empty, a placeholder or malformed: "
                               "enter it again in the console")
        req = urllib.request.Request(ARK_BASE + "/images/generations", method="POST",
                                     data=json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + secret)
        put_status(job_id, sent=True, **running)
        sent = True
        timeout = max(1, int(context.get_remaining_time_in_millis() / 1000 - 20))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:600]}")
        keys = []
        for i, d in enumerate(resp.get("data", [])):
            raw = base64.b64decode(d["b64_json"])
            ext, mime = sniff(raw)
            key = f"images/{job_id}.{ext}" if i == 0 else f"images/{job_id}-{i}.{ext}"
            S3.put_object(Bucket=BUCKET, Key=key, Body=raw, ContentType=mime)
            keys.append(key)
        put_status(job_id, status="succeeded", model=model, sent=True, keys=keys, usage=resp.get("usage"),
                   seconds=round(time.time() - t0, 1))
        return {"job_id": job_id, "keys": keys}
    except Exception as e:
        # Only the redacted text leaves this block: the original exception (its message and traceback can hold
        # the key) is neither stored nor chained, so CloudWatch does not get it either.
        error = redact(str(e) or type(e).__name__, secret)[:800]
    # record the failure for the poller, then fail (no auto-retry: see the deploy config)
    put_status(job_id, status="failed", model=model, sent=sent, error=error, seconds=round(time.time() - t0, 1))
    raise RuntimeError(error) from None
