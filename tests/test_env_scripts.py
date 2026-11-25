"""tools/doctor.sh and .claude/hooks/session-start.sh, run for real against temp directories.

Nothing here touches the real /opt/byteplus, site-packages or the Ark host, and nothing is installed:
ARK_DIR, FILM_LAB_STAMP, HOME and CLAUDE_ENV_FILE point into a temp dir, ARK_BASE at a closed port or
at the local fake server below, and shims for python3 (pip, the u2net prefetch), apt-get and fc-list
come first on PATH.
"""
import concurrent.futures, http.server, json, os, re, shutil, stat, subprocess, sys, tempfile, threading, unittest
from pathlib import Path

import helpers

REPO = helpers.REPO
BASH, GIT = shutil.which("bash"), shutil.which("git")
CLOSED = os.environ["ARK_BASE"]            # helpers points it at a closed local port
REAL_LINK = Path("/opt/byteplus/ark.py")
ark = helpers.load("ark.py")
TASK_ID = "cgt-FAKE-TASK-1"


def must_be_redirectable(*scripts):
    """Refuse to run a script that could write to the machine-wide ark.py link or pip stamp:
    the only mention of the real directory in code must be the ARK_DIR default."""
    for path in scripts:
        text = Path(path).read_text()
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        if "/opt/byteplus" in code.replace("${ARK_DIR:-/opt/byteplus}", ""):
            raise AssertionError(f"{path}: hardcoded /opt/byteplus; not running it (use $ARK_DIR)")
        if "pip install -q" in code and "${FILM_LAB_STAMP:-" not in code:
            raise AssertionError(f"{path}: the pip stamp path ignores FILM_LAB_STAMP; not running it")


def real_link_target():
    return os.readlink(REAL_LINK) if REAL_LINK.is_symlink() else None


def base_env(tmp, **extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k not in ("FILM_LAB", "CINECODE_FORMATS", "CHROME_PATH",
                                                     "CLAUDE_PROJECT_DIR", "CLAUDE_ENV_FILE", "ARK_API_KEY")}
    env.update(ARK_BASE=CLOSED, ARK_DIR=str(tmp / "ark"), NO_PROXY="127.0.0.1,localhost",
               no_proxy="127.0.0.1,localhost", HTTPS_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9")
    env.update(extra)
    return env


def run(cmd, env, cwd=None):
    r = subprocess.run([str(c) for c in cmd], env=env, cwd=cwd, capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout, r.stderr


def write_exec(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class FakeArk(http.server.BaseHTTPRequestHandler):
    """Local stand-in for Ark. The first path segment is the scenario: <models>_<post>."""

    def log_message(self, *a):
        pass

    def answer(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        kind = self.path.split("/")[1].split("_")[0]
        row = lambda i, s="Active": {"id": i, "domain": "VideoGeneration", "task_type": ["x"], "status": s}
        rows = [row(ark.VIDEO_DEFAULT, "Shutdown" if kind == "shutdown" else "Active"),
                row(ark.IMAGE_FAST), row(ark.LAMBDA_DEFAULT), row("retired-model-000000", "Shutdown")]
        self.answer(200, {"data": [] if kind == "empty" else rows})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        kind = self.path.split("/")[1].split("_")[1]
        if kind == "task":
            return self.answer(200, {"id": TASK_ID})
        code, name = (404, "ModelNotOpen") if kind.startswith("notopen") else (400, "InvalidParameter")
        # "notopenmix": a ModelNotOpen answer whose message happens to mention InvalidParameter
        self.answer(code, {"error": {"code": name, "message": "fake InvalidParameter" if kind == "notopenmix" else "fake"}})


# Stand-in for tools/ark.py that fails the way ark.py does when the host is unreachable: today with an
# uncaught URLError (a traceback), or with a clean `network error: ...` exit. doctor must handle both.
FAKE_ARK = """import os, sys, urllib.error
VIDEO_DEFAULT = "fake-video-000000"
IMAGE_FAST = "fake-fast-000000"
LAMBDA_DEFAULT = "fake-pro-000000"
def call(method, path, body=None, timeout=300):
    if os.environ["FAKE_ARK"] == "exit":
        sys.exit("network error: [Errno 111] Connection refused")
    raise urllib.error.URLError("[Errno 111] Connection refused")
if __name__ == "__main__":
    call("GET", "/models")
"""


def tts_jobs(td):
    """Doctor scenarios for the narration lines (tts, tts-watermark, --episode). python3 runs with -S, so what is
    really installed (vieneu, perth, torch in a cloud session) never leaks in: only the stand-ins below exist,
    plus PyYAML, which --episode needs to read EPISODE.md."""
    import yaml
    nosite = td / "nosite"
    nosite.mkdir()
    write_exec(nosite / "python3", f'#!/bin/bash\nexec "{sys.executable}" -S "$@"\n')
    (td / "base").mkdir()
    os.symlink(Path(yaml.__file__).parent, td / "base" / "yaml")

    def stubs(kind, dists, perth_body=""):
        d = td / kind
        mods = {"vieneu": "vieneu", "resemble-perth": "perth", "torch": "torch"}
        for name, ver in dists:
            (d / mods[name]).mkdir(parents=True)
            (d / mods[name] / "__init__.py").write_text(perth_body if name == "resemble-perth" else "")
            info = d / f"{name.replace('-', '_')}-{ver}.dist-info"
            info.mkdir()
            (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {ver}\n")
        return f"{d}{os.pathsep}{td / 'base'}"
    full = [("vieneu", "3.8.3"), ("resemble-perth", "1.0.1"), ("torch", "2.15.0+cpu")]
    ok, old = stubs("tts_ok", full), stubs("tts_old", [("vieneu", "3.7.0")])
    broken = stubs("tts_broken", full, "raise ImportError('perth stubbed out by the test')\n")
    none = str(td / "base")
    (td / "hf_cached" / "hub" / "models--pnnbao-ump--VieNeu-TTS-v3-Turbo" / "snapshots" / "abc123").mkdir(parents=True)

    def episode(name, g3, script):
        d = td / name
        d.mkdir()
        (d / "EPISODE.md").write_text("---\nstage: 10\ngates: {G1: 2026-11-01, G2: 2026-11-03, G3: %s, G4: null}\n"
                                      "---\n# Tập\n" % g3, encoding="utf-8")
        (d / "script.md").write_text(script, encoding="utf-8")
        return str(d)
    past = episode("ep_past", "2026-11-06", "# Lời bình\n[00:00] Một.\n[00:05] Hai.\n")
    before = episode("ep_before", "null", "# Lời bình\n[00:00] Một.\n")
    silent = episode("ep_silent", "2026-11-06", "# Không có lời bình\n")
    path = str(nosite) + os.pathsep + os.environ["PATH"]

    def env(pythonpath, hf="hf_none"):
        return {"PATH": path, "PYTHONPATH": pythonpath, "HF_HOME": str(td / hf), "HF_HUB_CACHE": ""}
    return {
        "tts_none": ([None, "--quick"], env(none)),
        "tts_ok": ([None, "--quick"], env(ok)),
        "tts_cached": ([None, "--quick"], env(ok, "hf_cached")),
        "tts_old": ([None, "--quick"], env(old)),
        "tts_full": ([None], env(ok)),
        "tts_full_broken": ([None], env(broken)),
        "ep_past": ([None, "--quick", "--episode", past], env(none)),
        "ep_past_ok": ([None, "--episode", past, "--quick"], env(ok)),
        "ep_before": ([None, "--quick", "--episode", before], env(none)),
        "ep_silent": ([None, "--quick", "--episode", silent], env(none)),
        "ep_missing": ([None, "--quick", "--episode", str(td / "nowhere")], env(none)),
        "ep_noarg": ([None, "--quick", "--episode"], env(none)),
    }


@unittest.skipUnless(BASH and GIT, "needs bash and git")
class TestDoctor(unittest.TestCase):
    """Every scenario runs once, in parallel, in setUpClass; the tests assert on single lines only
    (ffmpeg, chrome, fonts and the like depend on the machine)."""

    @classmethod
    def setUpClass(cls):
        cls.td = Path(os.path.realpath(tempfile.mkdtemp(prefix="film-doctor-")))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeArk)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        fake = "http://127.0.0.1:%d/" % cls.srv.server_address[1]
        # full mode really imports rembg and onnxruntime (1-12 s): stand-ins keep the runs fast and
        # independent of what is installed; "broken" has an onnxruntime that cannot be imported
        for kind, body in (("fast", "__version__ = 'stub'\n"), ("broken", "raise ImportError('stubbed out by the test')\n")):
            for mod in ("rembg", "onnxruntime"):
                (cls.td / kind / mod).mkdir(parents=True)
                (cls.td / kind / mod / "__init__.py").write_text(body if mod == "onnxruntime" else "")
        fast, broken = {"PYTHONPATH": str(cls.td / "fast")}, {"PYTHONPATH": str(cls.td / "broken")}
        shims = cls.td / "shims"
        shims.mkdir()
        write_exec(shims / "node", "#!/bin/bash\necho v20.11.1\n")
        old_path = str(shims) + os.pathsep + os.environ["PATH"]
        doctor = REPO / "tools" / "doctor.sh"
        must_be_redirectable(doctor)
        (cls.td / "fakelab" / "tools").mkdir(parents=True)
        shutil.copy2(doctor, cls.td / "fakelab" / "tools" / "doctor.sh")
        (cls.td / "fakelab" / "tools" / "ark.py").write_text(FAKE_ARK)
        jobs = {
            "notopen": (["ok_notopen"], fast),
            "notopenmix": (["ok_notopenmix"], fast),
            "task": (["ok_task"], fast),
            "invalid": (["ok_invalid"], fast),
            "empty": (["empty_invalid", "--quick"], {}),
            "shutdown": (["shutdown_invalid", "--quick"], {}),
            "closed": ([None], fast),
            "closed_quick": ([None, "--quick"], {"PATH": old_path}),
            "no_onnx": (["ok_invalid"], broken),
            "net_traceback": ([None], dict(fast, FAKE_ARK="raise", DOCTOR="fake")),
            "net_exit": ([None], dict(fast, FAKE_ARK="exit", DOCTOR="fake")),
            "help": ([None, "--help"], {}),
            "h": ([None, "-h"], {}),
            "bogus": ([None, "--bogus"], {}),
            "two_args": ([None, "--quick", "extra"], {}),
        }
        jobs.update(tts_jobs(cls.td))

        def go(item):
            name, ((scn, *args), extra) = item
            env = base_env(cls.td, ARK_BASE=fake + scn if scn else CLOSED, **extra)
            script = cls.td / "fakelab" / "tools" / "doctor.sh" if extra.get("DOCTOR") else doctor
            return name, run([BASH, script, *args], env)

        before = real_link_target()
        with concurrent.futures.ThreadPoolExecutor(6) as pool:
            cls.r = dict(pool.map(go, jobs.items()))
        cls.link_unchanged = before == real_link_target()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.td, ignore_errors=True)

    def line(self, name, check):
        """The report line of one check, e.g. '  FAIL  video-model   ...'."""
        out = self.r[name][1]
        found = [l for l in out.splitlines() if re.match(r"\s+(OK|FAIL|WARN|INFO)\s+%s\s" % re.escape(check), l)]
        self.assertEqual(len(found), 1, f"{check} lines in:\n{out}\n{self.r[name][2]}")
        return found[0]

    def test_model_not_open_is_counted(self):
        rc, out, _ = self.r["notopen"]
        self.assertRegex(self.line("notopen", "video-model"), r"FAIL .*%s not activated" % ark.VIDEO_DEFAULT)
        self.assertNotEqual(rc, 0)
        self.assertIn("check(s) failed", out)
        self.assertNotIn("all checks passed", out)

    def test_model_not_open_wins_over_an_invalid_parameter_mention(self):
        self.assertRegex(self.line("notopenmix", "video-model"), r"FAIL .*%s not activated" % ark.VIDEO_DEFAULT)
        self.assertNotIn("all checks passed", self.r["notopenmix"][1])

    def test_accepted_task_fails_with_its_id(self):
        rc, out, _ = self.r["task"]
        l = self.line("task", "video-model")
        self.assertRegex(l, r"FAIL .*unexpected task %s created: it may be billed, cancel it" % TASK_ID)
        self.assertNotEqual(rc, 0)
        self.assertNotIn("all checks passed", out)

    def test_invalid_parameter_means_activated(self):
        self.assertRegex(self.line("invalid", "video-model"), r"OK .*%s activated" % ark.VIDEO_DEFAULT)
        self.assertRegex(self.line("invalid", "ark-ping"), r"OK .*3 models visible")
        self.assertIn("image-models", self.r["invalid"][1])

    def test_result_line_matches_the_fail_lines(self):
        for name in ("notopen", "task", "invalid", "closed", "empty"):
            rc, out, _ = self.r[name]
            n = len(re.findall(r"^\s+FAIL\s", out, re.M))
            self.assertEqual(rc, n, out)
            self.assertIn("Result: all checks passed" if n == 0 else f"Result: {n} check(s) failed", out)

    def test_empty_model_list_fails(self):
        self.assertRegex(self.line("empty", "ark-ping"), r"FAIL .*no model")
        self.assertNotEqual(self.r["empty"][0], 0)

    def test_shutdown_default_model_fails_and_is_named(self):
        self.assertRegex(self.line("shutdown", "ark-ping"), r"FAIL .*Shutdown.*%s" % ark.VIDEO_DEFAULT)

    def test_closed_port_is_one_line_without_traceback(self):
        for name in ("closed", "closed_quick", "net_traceback", "net_exit"):
            rc, out, err = self.r[name]
            self.assertRegex(self.line(name, "ark-ping"), r"FAIL .*Ark host unreachable: .*refused")
            self.assertNotIn("Traceback", out + err)
            self.assertNotIn("all checks passed", out)
        for name in ("closed", "net_traceback", "net_exit"):
            self.assertRegex(self.line(name, "video-model"), r"FAIL .*Ark host unreachable: .*refused")

    def test_full_mode_really_imports_onnxruntime(self):
        self.assertRegex(self.line("no_onnx", "rembg"), r"FAIL .*import fails.*stubbed out by the test")
        self.assertRegex(self.line("invalid", "rembg"), r"(OK .*imported|FAIL )")   # FAIL: rembg not installed here

    def test_old_node_fails(self):
        self.assertRegex(self.line("closed_quick", "node"), r"FAIL .*v20\.11\.1.*22")
        self.assertRegex(self.line("closed", "node"), r"(OK|FAIL) ")

    def test_missing_session_variables_warn_with_the_export_line(self):
        self.assertRegex(self.line("closed_quick", "env-film-lab"), r'WARN .*export FILM_LAB="/')
        self.assertRegex(self.line("closed_quick", "env-formats"), r"WARN .*export CINECODE_FORMATS=")
        self.line("closed_quick", "ffprobe")

    def test_help_prints_usage_and_runs_nothing(self):
        for name in ("help", "h"):
            rc, out, err = self.r[name]
            self.assertEqual(rc, 0, out + err)
            self.assertIn("--quick", out)
            self.assertNotIn("AI Film Lab doctor (", out)
            self.assertNotIn("Result:", out)

    def test_unknown_argument_is_a_usage_error(self):
        for name in ("bogus", "two_args"):
            rc, out, err = self.r[name]
            self.assertEqual(rc, 2, out + err)
            self.assertIn("--quick", err)
            self.assertEqual(out, "")

    def test_real_link_untouched(self):
        self.assertTrue(self.link_unchanged)

    # --- narration (#37) ----------------------------------------------------------------------------------------
    def test_tts_missing_is_a_warning_with_the_install_line(self):
        rc, out, _ = self.r["tts_none"]
        self.assertRegex(self.line("tts_none", "tts"), r"WARN .*missing module\(s\) vieneu.*requirements-tts\.txt")
        self.assertRegex(self.line("tts_none", "tts-watermark"), r"WARN .*missing module\(s\) perth, torch")
        self.assertEqual(rc, len(re.findall(r"^\s+FAIL\s", out, re.M)), out)

    def test_tts_installed_and_pinned(self):
        self.assertRegex(self.line("tts_ok", "tts"), r"OK .*vieneu 3\.8\.3, v3 Turbo model not cached")
        self.assertRegex(self.line("tts_cached", "tts"), r"OK .*vieneu 3\.8\.3, v3 Turbo model cached")
        self.assertRegex(self.line("tts_ok", "tts-watermark"), r"OK .*resemble-perth 1\.0\.1 \+ torch 2\.15\.0\+cpu")

    def test_tts_other_version_warns(self):
        self.assertRegex(self.line("tts_old", "tts"), r"WARN .*vieneu 3\.7\.0, pinned 3\.8\.3 in requirements-tts\.txt")

    def test_full_mode_imports_the_tts_modules(self):
        self.assertRegex(self.line("tts_full", "tts"), r"OK .*vieneu 3\.8\.3 \(imported\)")
        self.assertRegex(self.line("tts_full", "tts-watermark"), r"OK .*\(imported\)")
        self.assertRegex(self.line("tts_full_broken", "tts-watermark"), r"WARN .*import fails.*perth stubbed out")

    def test_watermark_fails_only_for_an_episode_past_g3_with_narration(self):
        rc, out, err = self.r["ep_past"]
        self.assertRegex(self.line("ep_past", "tts-watermark"), r"FAIL .*passed G3 \(2026-11-06\) with narration")
        self.assertEqual(rc, len(re.findall(r"^\s+FAIL\s", out, re.M)), out + err)
        self.assertNotIn("all checks passed", out)
        self.assertRegex(self.line("ep_past", "tts"), r"WARN ")                 # vieneu itself stays a warning
        self.assertRegex(self.line("ep_past_ok", "tts-watermark"), r"OK ")
        self.assertRegex(self.line("ep_before", "tts-watermark"), r"WARN ")
        self.assertRegex(self.line("ep_silent", "tts-watermark"), r"WARN ")

    def test_episode_argument_errors_are_usage_errors(self):
        rc, out, err = self.r["ep_missing"]
        self.assertEqual((rc, out), (2, ""), err)
        self.assertIn("doctor: --episode:", err)
        self.assertIn("EPISODE.md", err)
        rc, out, err = self.r["ep_noarg"]
        self.assertEqual((rc, out), (2, ""), err)
        self.assertIn("--episode", err)


PY_SHIM = """#!/bin/bash
# python3 shim for the hook tests: pip and the u2net prefetch never run for real.
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
  echo "$*" >> "$SHIM_LOG.pip"
  exit "${SHIM_PIP_RC:-0}"
fi
for a in "$@"; do
  case "$a" in *"from rembg import new_session"*) echo prefetch >> "$SHIM_LOG.u2net"; exit 0;; esac
done
exec %s "$@"
"""


class HookLab:
    """A temp git repo holding copies of the hook, doctor.sh, ark.py and requirements.txt (committed, so
    `git worktree add` works), with its own ARK_DIR, stamp, HOME, CLAUDE_ENV_FILE and PATH shims."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.lab = tmp / "lab"
        for rel in (".claude/hooks/session-start.sh", "tools/doctor.sh", "tools/ark.py", "requirements.txt"):
            (self.lab / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, self.lab / rel)
        shims = tmp / "shims"
        shims.mkdir()
        write_exec(shims / "python3", PY_SHIM % sys.executable)
        write_exec(shims / "apt-get", '#!/bin/bash\necho "$*" >> "$SHIM_LOG.apt"\nexit 0\n')
        write_exec(shims / "fc-list", '#!/bin/bash\n[ -n "${SHIM_NO_FONT:-}" ] || echo "Noto Serif CJK JP"\n')
        (tmp / "home").mkdir()
        self.env = base_env(tmp, CLAUDE_CODE_REMOTE="true", HOME=str(tmp / "home"),
                            CLAUDE_ENV_FILE=str(tmp / "env.sh"), FILM_LAB_STAMP=str(tmp / "stamp"),
                            SHIM_LOG=str(tmp / "shim"), PATH=str(shims) + os.pathsep + os.environ["PATH"])
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                 "commit", "-q", "-m", "fixture")

    def git(self, *args):
        rc, out, err = run([GIT, "-C", self.lab, *args], self.env)
        if rc:
            raise RuntimeError(err)

    def hook(self, lab=None, **extra):
        return run([BASH, (lab or self.lab) / ".claude/hooks/session-start.sh"], dict(self.env, **extra))

    def doctor(self, lab):
        return run([BASH, lab / "tools/doctor.sh", "--quick"], self.env)

    def calls(self, kind):
        f = self.tmp / f"shim.{kind}"
        return f.read_text().splitlines() if f.exists() else []

    def link(self):
        return os.readlink(self.tmp / "ark" / "ark.py")

    def stamp(self):
        return (self.tmp / "stamp").exists()


def scn_pip_fails(L):
    first = L.hook(SHIM_PIP_RC="1")
    state = (L.stamp(), len(L.calls("pip")))
    L.hook(SHIM_PIP_RC="1")
    return dict(first=first, state=state, pip_after_second=len(L.calls("pip")))


def scn_healthy(L):
    first = L.hook()
    state = (L.stamp(), len(L.calls("pip")), L.link())
    env_lines = (L.tmp / "env.sh").read_text().splitlines()
    second = L.hook()
    return dict(first=first, state=state, env_lines=env_lines, second=second, pip_after_second=len(L.calls("pip")))


def scn_no_font(L):
    return dict(first=L.hook(SHIM_NO_FONT="1"), apt=L.calls("apt"))


def scn_not_cloud(L):
    return dict(first=L.hook(CLAUDE_CODE_REMOTE=""), ark_dir=(L.tmp / "ark").exists())


def scn_worktree(L):
    L.hook()
    before = L.link()
    wt = L.tmp / "wt"
    L.git("worktree", "add", "-q", "--detach", str(wt))
    hook = L.hook(lab=wt)
    after = L.link()
    doctor_ok = L.doctor(wt)
    (L.tmp / "ark" / "ark.py").unlink()
    return dict(before=before, hook=hook, after=after, doctor_ok=doctor_ok, doctor_bad=L.doctor(wt))


@unittest.skipUnless(BASH and GIT, "needs bash and git")
class TestSessionStartHook(unittest.TestCase):
    """Each scenario gets its own HookLab; they run once, in parallel, in setUpClass."""

    @classmethod
    def setUpClass(cls):
        must_be_redirectable(REPO / ".claude/hooks/session-start.sh", REPO / "tools/doctor.sh")
        cls.td = Path(os.path.realpath(tempfile.mkdtemp(prefix="film-hook-")))
        scns = dict(pip_fails=scn_pip_fails, healthy=scn_healthy, no_font=scn_no_font, not_cloud=scn_not_cloud,
                    worktree=scn_worktree)

        def go(item):
            name, fn = item
            (cls.td / name).mkdir()
            lab = HookLab(cls.td / name)
            return name, (lab, fn(lab))

        before = real_link_target()
        with concurrent.futures.ThreadPoolExecutor(len(scns)) as pool:
            done = dict(pool.map(go, scns.items()))
        cls.link_unchanged = before == real_link_target()
        cls.lab = {k: v[0] for k, v in done.items()}
        cls.r = {k: v[1] for k, v in done.items()}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def test_real_link_untouched(self):
        self.assertTrue(self.link_unchanged, "the real /opt/byteplus/ark.py link moved")

    def test_pip_failure_still_prints_the_report(self):
        r = self.r["pip_fails"]
        rc, out, err = r["first"]
        self.assertEqual(rc, 0, out + err)
        self.assertIn("film-lab: pip install failed (rc 1)", out)
        self.assertEqual(out.count("AI Film Lab doctor (quick)"), 1)
        self.assertLess(out.index("pip install failed"), out.index("AI Film Lab doctor"))
        self.assertEqual(r["state"], (False, 1), "no stamp after a failed install")
        self.assertEqual(r["pip_after_second"], 2, "the next start retries")

    def test_valid_stamp_skips_pip(self):
        r = self.r["healthy"]
        rc, out, err = r["first"]
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("pip install failed", out)
        self.assertEqual(r["state"][:2], (True, 1))
        rc, out, err = r["second"]
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(r["pip_after_second"], 1, "pip ran again although the stamp was valid")
        self.assertEqual(out.count("AI Film Lab doctor (quick)"), 1)

    def test_exports_reach_the_env_file_and_the_doctor(self):
        lab, r = self.lab["healthy"].lab, self.r["healthy"]
        want = [f'export FILM_LAB="{lab}"', f'export CINECODE_FORMATS="{lab}/formats"',
                'export FILM_THREE="/opt/film-lab/vendor/three/build/three.module.js"']
        if os.getuid() == 0:
            want.append(f'export CHROME_PATH="{lab}/tools/compose/chrome-root.sh"')
        self.assertEqual(r["env_lines"], want)
        out = r["first"][1]
        self.assertRegex(out, r"OK\s+env-film-lab\s+FILM_LAB=%s\n" % re.escape(str(lab)))
        self.assertRegex(out, r"OK\s+env-formats")

    def test_link_points_at_the_repo(self):
        self.assertEqual(self.r["healthy"]["state"][2], str(self.lab["healthy"].lab / "tools" / "ark.py"))
        self.assertRegex(self.r["healthy"]["first"][1], r"OK\s+ark\.py\s.*-> repo")

    def test_missing_font_goes_through_apt(self):
        r = self.r["no_font"]
        rc, out, err = r["first"]
        self.assertEqual(rc, 0, out + err)
        self.assertEqual([c.split()[0] for c in r["apt"]], ["update", "install"])
        self.assertIn("AI Film Lab doctor (quick)", out)

    def test_installs_are_time_boxed(self):
        code = (REPO / ".claude/hooks/session-start.sh").read_text()
        for want in ("timeout 120 apt-get update", "timeout 300 apt-get install", "timeout 600 python3 -m pip install",
                     "timeout 240 python3 -c"):
            self.assertIn(want, code)

    def test_not_a_cloud_session_does_nothing(self):
        r = self.r["not_cloud"]
        self.assertEqual(r["first"][:2], (0, ""))
        self.assertFalse(r["ark_dir"])

    def test_worktree_keeps_the_link_on_the_main_checkout(self):
        lab, r = self.lab["worktree"].lab, self.r["worktree"]
        rc, out, err = r["hook"]
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(r["before"], str(lab / "tools" / "ark.py"))
        self.assertEqual(r["after"], r["before"])
        self.assertIn("stays on the main checkout", out)
        self.assertIn("AI Film Lab doctor (quick)", out)
        # doctor run from the worktree accepts the main checkout's link ...
        self.assertRegex(r["doctor_ok"][1], r"OK\s+ark\.py\s.*main checkout \(linked worktree\)")
        # ... and when the link is wrong, sends the engineer to the main checkout's hook
        self.assertRegex(r["doctor_bad"][1],
                         r"FAIL\s+ark\.py\s.*%s" % re.escape(str(lab / ".claude/hooks/session-start.sh")))


SETUP_PY_SHIM = """#!/bin/bash
# python3 shim for the setup-script tests: pip and the model prefetch never run for real.
echo "$*" >> "$SHIM_LOG"
for word in ${SHIM_FAIL:-}; do
  case "$*" in *"$word"*) exit 1;; esac
done
exit 0
"""


def tts_block():
    """The narration step of docs/setup-script.sh, between its '# --- tts: begin' and '# --- tts: end' markers."""
    text = (REPO / "docs" / "setup-script.sh").read_text(encoding="utf-8")
    m = re.search(r"^# --- tts: begin\n(.*?)^# --- tts: end$", text, re.S | re.M)
    if not m:
        raise AssertionError("docs/setup-script.sh: tts markers missing")
    return m.group(1)


def requirement_pins(name):
    lines = (REPO / name).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]


@unittest.skipUnless(BASH and shutil.which("timeout"), "needs bash and timeout")
class TestSetupScriptTts(unittest.TestCase):
    """The narration step of the environment setup script (#37), run with a python3 shim: every pip call is logged,
    SHIM_FAIL makes the calls that mention a word fail."""

    def setUp(self):
        self.td = Path(os.path.realpath(tempfile.mkdtemp(prefix="film-setup-tts-")))
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        (self.td / "bin").mkdir()
        write_exec(self.td / "bin" / "python3", SETUP_PY_SHIM)
        script = self.td / "tts.sh"
        script.write_text('log() { echo "[setup] $*"; }\n' + tts_block() + "exit 0\n", encoding="utf-8")
        self.script = script

    def run_block(self, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("FILM_TTS")}
        e.update(PATH=str(self.td / "bin") + os.pathsep + os.environ["PATH"], SHIM_LOG=str(self.td / "calls"),
                 TTS_LOG=str(self.td / "setup-tts.log"), **env)
        rc, out, err = run([BASH, self.script], e)
        calls = (self.td / "calls").read_text().splitlines() if (self.td / "calls").exists() else []
        return rc, out + err, calls

    def test_pins_equal_requirements_tts_and_the_tool(self):
        block = tts_block()
        pins = requirement_pins("requirements-tts.txt")
        self.assertEqual(sorted(p.split("==")[0] for p in pins), ["resemble-perth", "vieneu"])
        for pin in pins:
            self.assertIn(f'"{pin}"', block, f"docs/setup-script.sh must install {pin}")
        torch = re.search(r"^# torch-cpu: (torch==\S+)$", (REPO / "requirements-tts.txt").read_text(), re.M).group(1)
        self.assertIn(f'"{torch}"', block)
        tts = helpers.load("tts/vieneu_tts.py", "film_vieneu_tts_env")
        self.assertIn(f"vieneu=={tts.VIENEU_PIN}", pins)
        for pin in [torch] + [p for p in pins if not p.startswith("vieneu")]:
            self.assertIn(pin, tts.WATERMARK_INSTALL)
        self.assertIn("--break-system-packages", tts.WATERMARK_INSTALL)

    def test_the_session_hook_never_installs_torch(self):
        names = " ".join(requirement_pins("requirements.txt")).lower()
        for heavy in ("torch", "vieneu", "perth"):
            self.assertNotIn(heavy, names)

    def test_installs_vieneu_then_cpu_torch_then_perth(self):
        rc, out, calls = self.run_block()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(calls), 3, calls)
        self.assertTrue(all(c.startswith("-m pip install") and "--break-system-packages" in c for c in calls), calls)
        self.assertIn("vieneu==3.8.3", calls[0])
        self.assertIn("--index-url https://download.pytorch.org/whl/cpu torch==2.15.0 torchaudio", calls[1])
        self.assertIn("resemble-perth==1.0.1", calls[2])
        self.assertNotIn("index-url", calls[2])
        self.assertIn("tts: ok", out)
        self.assertIn("tts-watermark: ok", out)
        self.assertNotIn("prefetch", out)

    def test_failures_are_warnings_and_never_abort(self):
        rc, out, calls = self.run_block(SHIM_FAIL="vieneu")
        self.assertEqual(rc, 0, out)
        self.assertIn("tts: WARN install failed", out)
        self.assertIn("tts-watermark: ok", out)                   # the watermark step still runs
        rc, out, calls = self.run_block(SHIM_FAIL="torch")
        self.assertEqual(rc, 0, out)
        self.assertIn("tts-watermark: WARN CPU torch failed", out)
        self.assertFalse(any("resemble-perth" in c for c in calls[-2:]), calls)   # never pulls torch from PyPI
        rc, out, _ = self.run_block(SHIM_FAIL="resemble-perth")
        self.assertEqual(rc, 0, out)
        self.assertIn("tts-watermark: WARN resemble-perth failed", out)

    def test_flags(self):
        rc, out, calls = self.run_block(FILM_TTS="0")
        self.assertEqual((rc, calls), (0, []))
        self.assertIn("tts: skipped (FILM_TTS=0)", out)
        rc, out, calls = self.run_block(FILM_TTS_PREFETCH="1")
        self.assertEqual(rc, 0, out)
        self.assertIn("Vieneu(mode='v3turbo')", calls[-1])
        self.assertIn("tts model: ok", out)
        rc, out, _ = self.run_block(FILM_TTS_PREFETCH="1", SHIM_FAIL="Vieneu")
        self.assertEqual(rc, 0, out)
        self.assertIn("tts model: WARN prefetch failed", out)

    def test_every_install_is_time_boxed(self):
        for line in tts_block().splitlines():
            if "PIPQ[@]}\"" in line or "python3 -c" in line:
                self.assertRegex(line, r"timeout \d+ ", line)


if __name__ == "__main__":
    unittest.main()
