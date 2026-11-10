"""AI Film Lab - Ark image worker (AWS Lambda, python3.13).

Runs BytePlus ModelArk image generation outside the Claude cloud proxy, so slow
models (dola-seedream-5-0-pro) and 4K sizes are not cut at ~30 s.

Invoke asynchronously (InvocationType=Event) with:
  {"job_id": "pro-test-01", "prompt": "...", "model": "dola-seedream-5-0-pro-260628",
   "size": "2K", "ref_keys": ["refs/a.png"]}          # ref_keys optional, S3 keys in BUCKET

Writes to s3://$BUCKET:
  images/<job_id>.<ext>   (and images/<job_id>-<n>.<ext> for extra images)
  jobs/<job_id>.json      status: running -> succeeded | failed, plus model, usage, seconds, error

job_id is the request id printed by `tools/ark.py lambda-job prepare` (which also checks the episode budget and
writes the ledger's pending row); `lambda-job finish` reads jobs/<job_id>.json back into the ledger.
A job_id that already has a jobs/<job_id>.json is NOT run again (Lambda delivers async events at least once;
a second run would bill a second image): the handler returns {"skipped": "duplicate"}.

Env: BUCKET, SECRET_ID (Secrets Manager secret holding the Ark API key as plain
text), ARK_BASE (default https://ark.ap-southeast.bytepluses.com/api/v3).
"""
import base64
import json
import os
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
_key = None


def ark_key():
    global _key
    if _key is None:
        _key = SM.get_secret_value(SecretId=SECRET_ID)["SecretString"].strip()
    return _key


def sniff(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "bin", "application/octet-stream"


def put_status(job_id, **fields):
    S3.put_object(Bucket=BUCKET, Key=f"jobs/{job_id}.json", ContentType="application/json",
                  Body=json.dumps({"job_id": job_id, **fields}, ensure_ascii=False).encode())


def existing_status(job_id):
    """The job's status object if it exists. A missing key raises (NoSuchKey, or AccessDenied without
    s3:ListBucket): both mean 'not there'; a real S3 outage fails at the first put_status instead."""
    try:
        return json.loads(S3.get_object(Bucket=BUCKET, Key=f"jobs/{job_id}.json")["Body"].read())
    except Exception:
        return None


def ref_data_uri(key):
    raw = S3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    return f"data:{sniff(raw)[1]};base64," + base64.b64encode(raw).decode()


def handler(event, context):
    job_id = event.get("job_id") or context.aws_request_id
    model = event.get("model") or DEFAULT_MODEL
    t0 = time.time()
    if event.get("job_id"):
        seen = existing_status(job_id)
        if seen is not None:     # duplicate delivery or a repeated invoke: never generate (and bill) twice
            return {"job_id": job_id, "skipped": "duplicate", "status": seen.get("status")}
    put_status(job_id, status="running", model=model, started=t0)
    try:
        body = {"model": model, "prompt": event["prompt"], "size": event.get("size", "2K"),
                "response_format": "b64_json", "watermark": False}
        refs = event.get("ref_keys") or []
        if refs:
            uris = [ref_data_uri(k) for k in refs]
            body["image"] = uris if len(uris) > 1 else uris[0]
        req = urllib.request.Request(ARK_BASE + "/images/generations", method="POST",
                                     data=json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + ark_key())
        remaining = max(30, context.get_remaining_time_in_millis() / 1000 - 20)
        try:
            with urllib.request.urlopen(req, timeout=remaining) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:600]}")
        keys = []
        for i, d in enumerate(resp.get("data", [])):
            raw = base64.b64decode(d["b64_json"])
            ext, mime = sniff(raw)
            key = f"images/{job_id}.{ext}" if i == 0 else f"images/{job_id}-{i}.{ext}"
            S3.put_object(Bucket=BUCKET, Key=key, Body=raw, ContentType=mime)
            keys.append(key)
        put_status(job_id, status="succeeded", model=model, keys=keys, usage=resp.get("usage"),
                   seconds=round(time.time() - t0, 1))
        return {"job_id": job_id, "keys": keys}
    except Exception as e:  # record failure for the poller, then fail (no auto-retry: see config)
        put_status(job_id, status="failed", model=model, error=str(e)[:800],
                   seconds=round(time.time() - t0, 1))
        raise
