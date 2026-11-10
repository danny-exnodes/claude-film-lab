"""lambda/build_deploy.py: the build has no side effect unless asked, the zip is reproducible, and the printed
run_script program is executed here against an in-memory fake of call_boto3 (no AWS, no network)."""
import ast, asyncio, base64, contextlib, hashlib, importlib.util, io, json, os, subprocess, sys, unittest
from pathlib import Path

from helpers import REPO, TmpDirCase

SCRIPT = REPO / "lambda" / "build_deploy.py"
REPO_ZIP = REPO / "out" / "ark_image_worker.zip"
ZIP_KEY = "deploy/ark_image_worker.zip"


def load_build_deploy():
    spec = importlib.util.spec_from_file_location("film_build_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def zip_stamp():
    return REPO_ZIP.stat().st_mtime_ns if REPO_ZIP.exists() else None


class FakeAws:
    """The handful of AWS operations the deploy program uses, as one in-memory account."""

    def __init__(self):
        self.calls = []                 # (service, operation, params)
        self.bucket = False
        self.objects = {}               # key -> ETag as S3 returns it (quoted)
        self.secret = None
        self.role = None
        self.policy = None
        self.function = None            # {"Timeout": ..., "CodeSha256": ...}
        self.invoke_config = None
        self.sha_of = {}                # ETag -> CodeSha256 Lambda computes for that object
        self.sse = None                 # ServerSideEncryption HeadObject reports for every object

    def ops(self, service=None):
        return [op for svc, op, _ in self.calls if service in (None, svc)]

    async def call_boto3(self, *, service_name, operation_name, region_name=None, params=None):
        p = params or {}
        self.calls.append((service_name, operation_name, p))
        return getattr(self, operation_name)(**p)

    def GetCallerIdentity(self):
        return {"Account": "000000000000"}

    def HeadBucket(self, Bucket):
        if not self.bucket:
            raise RuntimeError("An error occurred (404) when calling the HeadBucket operation: Not Found")
        return {}

    def CreateBucket(self, Bucket, CreateBucketConfiguration):
        self.bucket = True
        return {}

    def PutPublicAccessBlock(self, **kw):
        return {}

    def HeadObject(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("An error occurred (404) when calling the HeadObject operation: Not Found")
        return {"ETag": self.objects[Key], "ContentLength": 1,
                **({"ServerSideEncryption": self.sse} if self.sse else {})}

    def DescribeSecret(self, SecretId):
        if self.secret is None:
            raise RuntimeError("ResourceNotFoundException: secret")
        return self.secret

    def CreateSecret(self, Name, Description, SecretString):
        self.secret = {"ARN": "arn:aws:secretsmanager:ap-southeast-1:000000000000:secret:" + Name}
        self.secret_string = SecretString
        return self.secret

    def GetRole(self, RoleName):
        if self.role is None:
            raise RuntimeError("NoSuchEntity: role")
        return {"Role": self.role}

    def CreateRole(self, RoleName, AssumeRolePolicyDocument, Description):
        self.role = {"Arn": "arn:aws:iam::000000000000:role/" + RoleName}
        return {"Role": self.role}

    def AttachRolePolicy(self, **kw):
        return {}

    def PutRolePolicy(self, RoleName, PolicyName, PolicyDocument):
        self.policy = json.loads(PolicyDocument)
        return {}

    def _config(self):
        return {"State": "Active", "LastUpdateStatus": "Successful", **self.function}

    def _sha(self, code):
        return self.sha_of[self.objects[code["S3Key"]]]

    def GetFunction(self, FunctionName):
        if self.function is None:
            raise RuntimeError("An error occurred (ResourceNotFoundException) when calling GetFunction")
        return {"Configuration": self._config()}

    def GetFunctionConfiguration(self, FunctionName):
        if self.function is None:
            raise RuntimeError("An error occurred (ResourceNotFoundException) when calling GetFunctionConfiguration")
        return self._config()

    def CreateFunction(self, FunctionName, Code, **cfg):
        self.function = {"Timeout": cfg["Timeout"], "CodeSha256": self._sha(Code)}
        return self._config()

    def UpdateFunctionCode(self, FunctionName, S3Bucket, S3Key):
        self.function["CodeSha256"] = self._sha({"S3Key": S3Key})
        return self._config()

    def UpdateFunctionConfiguration(self, FunctionName, **cfg):
        self.function["Timeout"] = cfg["Timeout"]
        return self._config()

    def PutFunctionEventInvokeConfig(self, FunctionName, **cfg):
        self.invoke_config = cfg
        return {}


class TestBuild(TmpDirCase, unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.tmp, capture_output=True, text=True)

    def test_import_writes_nothing(self):
        before = zip_stamp()
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                load_build_deploy()
        finally:
            os.chdir(cwd)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertEqual(zip_stamp(), before)

    def test_help_exits_0_and_writes_nothing(self):
        before = zip_stamp()
        r = self.run_script("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--zip-out", r.stdout)
        self.assertIn("--check", r.stdout)
        self.assertNotIn("call_boto3", r.stdout)             # usage, not the program
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertEqual(zip_stamp(), before)

    def test_check_prints_the_two_hashes_and_writes_nothing(self):
        before = zip_stamp()
        r = self.run_script("--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        bd = load_build_deploy()
        worker = hashlib.sha256((REPO / "lambda" / "ark_image_worker.py").read_bytes()).hexdigest()
        code = base64.b64encode(hashlib.sha256(bd.build_zip()).digest()).decode()
        self.assertEqual(r.stdout.split(), ["CodeSha256", code, "worker_sha256", worker])
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertEqual(zip_stamp(), before)

    def test_two_builds_are_byte_identical_and_default_run_is_as_documented(self):
        a, b = self.tmp / "a.zip", self.tmp / "sub" / "b.zip"
        before = zip_stamp()
        ra = self.run_script("--zip-out", str(a))
        rb = self.run_script("--zip-out", str(b))
        self.assertEqual((ra.returncode, rb.returncode), (0, 0), ra.stderr + rb.stderr)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(ra.stdout, rb.stdout)
        self.assertEqual(zip_stamp(), before)                # --zip-out elsewhere leaves out/ alone
        self.assertIn("call_boto3", ra.stdout)               # the program on stdout
        self.assertIn("CodeSha256", ra.stderr)               # the summary on stderr
        self.assertIn(hashlib.md5(a.read_bytes()).hexdigest(), ra.stdout)
        self.assertIn(base64.b64encode(hashlib.sha256(a.read_bytes()).digest()).decode(), ra.stdout)
        compile(ra.stdout, "deploy_run.py", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)

    def test_main_default_zip_path_is_the_documented_one(self):
        bd = load_build_deploy()
        self.assertEqual(bd.ZIP_PATH, REPO / "out" / "ark_image_worker.zip")
        self.assertEqual(bd.CFG["timeout"], 900)


class TestProgram(unittest.TestCase):
    """The generated program, run against FakeAws."""

    @classmethod
    def setUpClass(cls):
        cls.bd = load_build_deploy()
        cls.zip = cls.bd.build_zip()
        cls.program = cls.bd.render_program(cls.zip)
        cls.code = compile(cls.program, "deploy_run.py", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        cls.md5 = hashlib.md5(cls.zip).hexdigest()
        cls.sha = base64.b64encode(hashlib.sha256(cls.zip).digest()).decode()

    def setUp(self):
        self.aws = FakeAws()
        self.good = f'"{self.md5}"'
        self.aws.sha_of[self.good] = self.sha

    def run_program(self):
        g = {"call_boto3": self.aws.call_boto3, "json": json, "asyncio": asyncio}
        co = eval(self.code, g)
        if asyncio.iscoroutine(co):
            asyncio.run(co)
        return g["result"]

    def test_fresh_account_asks_for_the_zip(self):
        out = self.run_program()
        self.assertEqual(out["state"], "zip-missing")
        self.assertIn(ZIP_KEY, out["next"])
        self.assertEqual(self.aws.ops("lambda"), [])
        self.assertTrue(self.aws.bucket)
        self.assertEqual(self.aws.secret_string, "REPLACE_WITH_ARK_API_KEY")
        self.assertNotIn("error", out)

    def test_correct_zip_creates_the_function(self):
        self.run_program()
        self.aws.objects[ZIP_KEY] = self.good
        out = self.run_program()
        self.assertEqual((out["state"], out["code_matches_repo"]), ("Active", True))
        self.assertNotIn("next", out)
        self.assertNotIn("error", out)
        self.assertIn("lambda: created", out["steps"])
        self.assertEqual(self.aws.function["Timeout"], 900)
        self.assertEqual(self.aws.invoke_config, {"MaximumRetryAttempts": 0, "MaximumEventAgeInSeconds": 300})
        bucket_arn = "arn:aws:s3:::" + out["bucket"]
        stmts = self.aws.policy["Statement"]
        self.assertIn({"Effect": "Allow", "Action": "s3:ListBucket", "Resource": bucket_arn}, stmts)
        self.assertIn({"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": bucket_arn + "/*"},
                      stmts)

    def test_second_run_updates_and_still_matches(self):
        self.aws.objects[ZIP_KEY] = self.good
        self.run_program()
        out = self.run_program()
        self.assertEqual((out["state"], out["code_matches_repo"]), ("Active", True))
        self.assertIn("lambda: updated", out["steps"])

    def test_older_zip_in_the_bucket_is_reported_and_not_installed(self):
        self.aws.objects[ZIP_KEY] = self.good
        self.run_program()                                   # function exists with the right code
        self.aws.calls.clear()
        self.aws.objects[ZIP_KEY] = '"' + "0" * 32 + '"'     # a plain MD5 ETag of some other zip
        out = self.run_program()
        self.assertEqual(out["state"], "zip-stale")
        self.assertIn(ZIP_KEY, out["next"])
        self.assertNotIn("UpdateFunctionCode", self.aws.ops())
        self.assertNotIn("CreateFunction", self.aws.ops())
        self.assertNotIn("lambda: updated", out["steps"])

    def test_older_zip_on_a_fresh_account_creates_nothing(self):
        self.aws.objects[ZIP_KEY] = '"' + "0" * 32 + '"'
        out = self.run_program()
        self.assertEqual(out["state"], "zip-stale")
        self.assertEqual(self.aws.ops("lambda"), [])
        self.assertIsNone(self.aws.function)

    def test_code_mismatch_after_the_update_is_an_error(self):
        self.aws.objects[ZIP_KEY] = self.good
        self.run_program()
        odd = '"' + "1" * 32 + '-2"'                         # multipart ETag: the MD5 pre-check cannot judge it
        self.aws.objects[ZIP_KEY] = odd
        self.aws.sha_of[odd] = "b2xkLXdvcmtlci1jb2RlLXNoYTI1Ng=="
        out = self.run_program()
        self.assertIn("UpdateFunctionCode", self.aws.ops())
        self.assertEqual((out["state"], out["code_matches_repo"]), ("code-mismatch", False))
        self.assertIn(self.sha, out["error"])

    def test_kms_etag_is_not_an_md5_and_does_not_block_the_right_zip(self):
        kms = '"' + "2" * 32 + '"'                           # SSE-KMS: 32 hex digits, not the object's MD5
        self.aws.objects[ZIP_KEY] = kms
        self.aws.sha_of[kms] = self.sha                      # the right zip, as Lambda hashes it
        self.aws.sse = "aws:kms"
        out = self.run_program()
        self.assertEqual((out["state"], out["code_matches_repo"]), ("Active", True))
        self.aws.sha_of[kms] = "b2xkLXdvcmtlci1jb2RlLXNoYTI1Ng=="   # a wrong zip under KMS: caught at the end
        out = self.run_program()
        self.assertEqual(out["state"], "code-mismatch")
        self.aws.sse = "AES256"                              # the same ETag without KMS is a stale zip
        self.assertEqual(self.run_program()["state"], "zip-stale")

    def test_program_never_reads_the_secret_value(self):
        self.aws.objects[ZIP_KEY] = self.good
        self.run_program()
        self.run_program()
        self.assertNotIn("GetSecretValue", self.aws.ops())


if __name__ == "__main__":
    unittest.main()
