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
SETUP_VERSION = re.search(r"^SETUP_VERSION=(\d+)", (REPO / "docs" / "setup-script.sh").read_text(), re.M).group(1)


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
                                                     "CLAUDE_PROJECT_DIR", "CLAUDE_ENV_FILE", "ARK_API_KEY",
                                                     "FILM_BLENDER", "FILM_COMFY_URL", "FILM_COMFY_HOME",
                                                     "FILM_COMFY_MODELS")}
    env.update(ARK_BASE=CLOSED, ARK_DIR=str(tmp / "ark"), FILM_SETUP_STAMP=str(tmp / "no-setup-stamp"),
               NO_PROXY="127.0.0.1,localhost",
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
        html = obj == "html"                     # a proxy or error page instead of Ark's JSON
        raw = b"<html><body>Bad gateway</body></html>" if html else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html" if html else "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        kind = self.path.split("/")[1].split("_")[0]
        row = lambda i, s="Active": {"id": i, "domain": "VideoGeneration", "task_type": ["x"], "status": s}
        rows = [row(ark.VIDEO_DEFAULT, "Shutdown" if kind == "shutdown" else "Active"),
                row(ark.IMAGE_FAST), row(ark.LAMBDA_DEFAULT), row("retired-model-000000", "Shutdown")]
        if kind in ("html", "list"):              # 200 that is not JSON / JSON that is not an object
            return self.answer(200, "html" if kind == "html" else [1, 2])
        self.answer(200, {"data": [] if kind == "empty" else rows})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        kind = self.path.split("/")[1].split("_")[1]
        if kind == "task":
            return self.answer(200, {"id": TASK_ID})
        if kind in ("html", "list"):
            return self.answer(200, "html" if kind == "html" else [TASK_ID])
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


# Stand-ins for the local engines' CLIs (packages P1/P2: tools/blender/blender.py find, tools/comfy/comfy.py ping).
# FAKE_BLENDER = ok | missing (exit 1, as `find` does when no Blender is found) | broken (exit 3: found, but
# `--version` fails) | crash (any other code); FAKE_COMFY = ok | down.
# comfy.py appends "<argv> <FILM_COMFY_URL>" to $COMFY_LOG, so a test can prove it was (not) called.
FAKE_BLENDER = """import os, sys
kind = os.environ.get("FAKE_BLENDER", "missing")
if sys.argv[1:] != ["find"]:
    sys.exit("fake blender.py: only find")
if kind == "ok":
    print("blender 5.3.0 /fake/blender")
elif kind == "missing":
    print("blender: not found (FILM_BLENDER, PATH, install folders)", file=sys.stderr); sys.exit(1)
elif kind == "broken":
    print("blender: found /fake/blender via PATH, but `--version` failed", file=sys.stderr); sys.exit(3)
else:
    print("Traceback: fake crash", file=sys.stderr); sys.exit(4)
"""
FAKE_COMFY = """import os, sys
with open(os.environ["COMFY_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + " " + os.environ.get("FILM_COMFY_URL", "-") + "\\n")
if os.environ.get("FAKE_COMFY") == "ok":
    print("ComfyUI 0.43.1 · python 3.12 · torch 2.9.0+cu130 · RTX 5070 Ti 15.1 GB free")
else:
    print("comfy: no ComfyUI at " + os.environ.get("FILM_COMFY_URL", "?") + " (connection refused)", file=sys.stderr)
    sys.exit(1)
"""


def local_engine_jobs(td):
    """Doctor scenarios for the blender and comfy lines: fakelab has the stand-ins above, barelab has neither tool."""
    for lab, with_tools in (("fakelab", True), ("barelab", False)):
        (td / lab / "tools").mkdir(parents=True, exist_ok=True)
        if with_tools:
            (td / lab / "tools" / "blender").mkdir()
            (td / lab / "tools" / "blender" / "blender.py").write_text(FAKE_BLENDER)
            (td / lab / "tools" / "comfy").mkdir()
            (td / lab / "tools" / "comfy" / "comfy.py").write_text(FAKE_COMFY)
    log = lambda name: str(td / f"comfy-{name}.log")
    base = {"DOCTOR": "fake", "FAKE_ARK": "exit"}
    return {
        "loc_none": ([None, "--quick"], dict(base, COMFY_LOG=log("none"))),
        "loc_ok": ([None, "--quick"], dict(base, FAKE_BLENDER="ok", FAKE_COMFY="ok", COMFY_LOG=log("ok"),
                                           FILM_COMFY_URL="http://127.0.0.1:8188")),
        "loc_broken": ([None, "--quick"], dict(base, FILM_BLENDER="/nowhere/blender.exe", FAKE_COMFY="down",
                                               FILM_COMFY_HOME="/nowhere/ComfyUI", COMFY_LOG=log("broken"))),
        "loc_crash": ([None, "--quick"], dict(base, FAKE_BLENDER="crash", COMFY_LOG=log("crash"))),
        "loc_found_broken": ([None, "--quick"], dict(base, FAKE_BLENDER="broken", COMFY_LOG=log("found_broken"))),
        "loc_far": ([None, "--quick"], dict(base, FILM_COMFY_URL="http://192.0.2.7:8188", FAKE_COMFY="ok",
                                            COMFY_LOG=log("far"))),
        "loc_bare": ([None, "--quick"], dict(base, DOCTOR="bare", FILM_COMFY_URL="http://127.0.0.1:8188",
                                             FILM_BLENDER="/x/blender", COMFY_LOG=log("bare"))),
    }


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

    def env(pythonpath, hf="hf_none", **extra):
        return dict({"PATH": path, "PYTHONPATH": pythonpath, "HF_HOME": str(td / hf), "HF_HUB_CACHE": ""}, **extra)
    # FILM_TTS_PYTHON (#63): a venv interpreter that sees the installed stand-ins while python3 on PATH sees none
    venv = td / "tts_venv" / "bin"
    venv.mkdir(parents=True)
    write_exec(venv / "python", f'#!/bin/bash\nPYTHONPATH="{ok}" exec "{sys.executable}" -S "$@"\n')
    return {
        "tts_venv": ([None, "--quick"], env(none, FILM_TTS_PYTHON=str(venv / "python"))),
        "tts_venv_bad": ([None, "--quick"], env(ok, FILM_TTS_PYTHON=str(td / "tts_venv" / "missing"))),
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
        # python3 that reports SHIM_PYV to the version check (everything else runs for real), a df with SHIM_DF_KB
        # free, and stand-ins for CHROME_PATH: one renders the page it is given, one crashes, one is not executable
        mach = cls.td / "machine"
        mach.mkdir()
        write_exec(mach / "python3", CI_PY_SHIM % sys.executable)
        write_exec(mach / "df", "#!/bin/bash\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
                                'echo "/dev/fake 99999999 1 ${SHIM_DF_KB} 1% /"\n')
        mach_path = str(mach) + os.pathsep + os.environ["PATH"]
        write_exec(cls.td / "chrome-good", '#!/bin/bash\nfor a in "$@"; do case "$a" in data:*) '
                                           'echo "<html><body>${a#*,}</body></html>";; esac; done\n')
        write_exec(cls.td / "chrome-bad", "#!/bin/bash\necho 'Running as root without --no-sandbox is not supported' >&2\n"
                                          "exit 1\n")
        (cls.td / "chrome-noexec").write_text("")
        (cls.td / "stamp-same").write_text(SETUP_VERSION + "\n")
        (cls.td / "stamp-old").write_text("1\n")
        cine = cls.td / "cinecode"                 # an installed cinecode that is not a git clone
        (cine / "templates" / "quick").mkdir(parents=True)
        (cine / "SKILL.md").write_text("---\nname: cinecode\n---\n")
        shutil.copy2(helpers.FIX / "cinecode" / "film.html", cine / "templates" / "quick" / "film.html")
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
            "ping_html": (["html_invalid", "--quick"], {}),
            "ping_list": (["list_invalid", "--quick"], {}),
            "probe_html": (["ok_html"], fast),
            "probe_list": (["ok_list"], fast),
            "old_python": ([None, "--quick"], {"PATH": mach_path, "SHIM_PYV": "3.8.10", "SHIM_LOG": str(cls.td / "py")}),
            "low_disk": ([None, "--quick"], {"PATH": mach_path, "SHIM_DF_KB": "1048576",
                                             "FILM_SETUP_STAMP": str(cls.td / "stamp-old")}),
            "big_disk": ([None, "--quick"], {"PATH": mach_path, "SHIM_DF_KB": "73400320",
                                             "FILM_SETUP_STAMP": str(cls.td / "stamp-same")}),
            "chrome_good": (["ok_invalid"], dict(fast, CHROME_PATH=str(cls.td / "chrome-good"))),
            "chrome_bad": (["ok_invalid"], dict(fast, CHROME_PATH=str(cls.td / "chrome-bad"))),
            "chrome_noexec": (["ok_invalid"], dict(fast, CHROME_PATH=str(cls.td / "chrome-noexec"))),
            "cine_dir": ([None, "--quick"], {"CINECODE_DIR": str(cls.td / "cinecode")}),
            "no_cine": ([None, "--quick"], {"CINECODE_DIR": str(cls.td / "nowhere")}),
            "help": ([None, "--help"], {}),
            "h": ([None, "-h"], {}),
            "bogus": ([None, "--bogus"], {}),
            "two_args": ([None, "--quick", "extra"], {}),
        }
        jobs.update(tts_jobs(cls.td))
        jobs.update(local_engine_jobs(cls.td))
        shutil.copy2(doctor, cls.td / "barelab" / "tools" / "doctor.sh")
        (cls.td / "barelab" / "tools" / "ark.py").write_text(FAKE_ARK)

        def go(item):
            name, ((scn, *args), extra) = item
            env = base_env(cls.td, ARK_BASE=fake + scn if scn else CLOSED, **extra)
            lab = {"fake": "fakelab", "bare": "barelab"}.get(extra.get("DOCTOR"))
            script = cls.td / lab / "tools" / "doctor.sh" if lab else doctor
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

    def test_non_json_models_answer_is_not_called_unreachable(self):
        l = self.line("ping_html", "ark-ping")
        self.assertRegex(l, r"FAIL .*Ark host answered, but not with JSON .*Expecting value")
        self.assertNotIn("unreachable", l)
        l = self.line("ping_list", "ark-ping")
        self.assertRegex(l, r"FAIL .*Ark host answered with JSON that is not a model list")
        self.assertNotIn("unreachable", l)
        for name in ("ping_html", "ping_list"):
            self.assertNotIn("Traceback", self.r[name][1])

    def test_probe_answer_that_is_not_an_object_may_be_a_task(self):
        for name, what in (("probe_html", r"not JSON: Expecting value"), ("probe_list", r"JSON list, not an object")):
            l = self.line(name, "video-model")
            self.assertRegex(l, r"FAIL .*not a task object \(%s\): a task may exist and be billed, check the Ark "
                                r"console" % what)
            self.assertNotIn("probe failed", l)
            self.assertNotEqual(self.r[name][0], 0)

    def test_cinecode_is_found_through_cinecode_dir(self):
        self.assertRegex(self.line("cine_dir", "skill-cinecode"), r"WARN .*present, not a git clone")
        self.assertRegex(self.line("cine_dir", "compose-kit"), r"OK .*--init ok on installed template")
        self.assertRegex(self.line("no_cine", "skill-cinecode"), r"FAIL .*nowhere/SKILL.md missing")

    def test_python_version(self):
        self.assertRegex(self.line("old_python", "python"), r"FAIL .*3\.8\.10 is too old: .*3\.10")
        self.assertRegex(self.line("closed_quick", "python"), r"OK +python +3\.\d+\.\d+")

    def test_free_disk(self):
        self.assertRegex(self.line("low_disk", "disk"), r"WARN .*only 1\.0 GB free .*5 GB")
        self.assertRegex(self.line("big_disk", "disk"), r"OK +disk +70\.0 GB free")
        rc, out, _ = self.r["low_disk"]
        self.assertEqual(len(re.findall(r"^\s+FAIL\s", out, re.M)), rc, "a low disk only warns")

    def test_setup_script_stamp(self):
        self.assertRegex(self.line("closed_quick", "setup-script"), r"WARN .*no stamp .*older than v%s" % SETUP_VERSION)
        self.assertNotRegex(self.r["closed_quick"][1] + self.r["closed_quick"][2], r"line \d+: .*No such file",
                            "a missing stamp is a WARN line, not a shell error")
        self.assertRegex(self.line("low_disk", "setup-script"),
                         r"WARN .*ran setup script v1, the repo has v%s" % SETUP_VERSION)
        self.assertRegex(self.line("big_disk", "setup-script"), r"OK +setup-script +v%s" % SETUP_VERSION)

    def test_headless_chrome_launch(self):
        self.assertRegex(self.line("chrome_good", "chrome-launch"), r"OK .*headless page rendered via .*chrome-good")
        self.assertRegex(self.line("chrome_bad", "chrome-launch"),
                         r"FAIL .*headless launch failed \(rc 1\): Running as root")
        self.assertRegex(self.line("chrome_noexec", "chrome-launch"), r"FAIL .*not an executable file")
        self.assertRegex(self.line("closed", "chrome-launch"), r"INFO .*CHROME_PATH unset")
        self.assertNotIn("chrome-launch", self.r["closed_quick"][1], "quick mode launches no browser")

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

    # --- local engines: blender, comfy (owner's PC only; never FAIL) ----------------------------------------------
    def comfy_calls(self, name):
        p = self.td / f"comfy-{name}.log"
        return p.read_text().splitlines() if p.exists() else []

    def assert_no_local_fail(self, name):
        rc, out, err = self.r[name]
        self.assertNotRegex(out, r"FAIL\s+(blender|comfy)\s", out + err)
        self.assertEqual(rc, len(re.findall(r"^\s+FAIL\s", out, re.M)), out + err)

    def test_local_engines_absent_are_quietly_not_applicable(self):
        self.assertRegex(self.line("loc_none", "blender"), r"INFO .*n/a: no Blender on this machine")
        self.assertRegex(self.line("loc_none", "comfy"), r"INFO .*n/a: FILM_COMFY_URL and FILM_COMFY_HOME unset")
        self.assertEqual(self.comfy_calls("none"), [], "unconfigured: ComfyUI is not contacted at all")
        self.assertRegex(self.line("loc_bare", "blender"), r"INFO .*n/a: tools/blender/blender.py not in this checkout")
        self.assertRegex(self.line("loc_bare", "comfy"), r"INFO .*n/a: tools/comfy/comfy.py not in this checkout")
        for name in ("loc_none", "loc_bare"):
            self.assert_no_local_fail(name)

    def test_local_engines_ok(self):
        self.assertRegex(self.line("loc_ok", "blender"), r"OK .*blender 5\.3\.0 /fake/blender")
        self.assertRegex(self.line("loc_ok", "comfy"), r"OK .*ComfyUI 0\.43\.1")
        self.assertEqual(self.comfy_calls("ok"), ["ping http://127.0.0.1:8188"])

    def test_local_engines_configured_but_broken_warn(self):
        self.assertRegex(self.line("loc_broken", "blender"),
                         r"WARN .*FILM_BLENDER=/nowhere/blender.exe is set but not usable: blender: not found")
        self.assertRegex(self.line("loc_broken", "comfy"),
                         r"WARN .*http://127\.0\.0\.1:8188: comfy: no ComfyUI .*comfy\.py start")
        self.assertEqual(self.comfy_calls("broken"), ["ping http://127.0.0.1:8188"], "FILM_COMFY_HOME alone: default URL")
        self.assertRegex(self.line("loc_crash", "blender"), r"WARN .*blender.py find failed \(rc 4\): Traceback")
        # exit 3 = a Blender was found but `--version` fails: WARN even without FILM_BLENDER (never n/a)
        self.assertRegex(self.line("loc_found_broken", "blender"),
                         r"WARN .*Blender found but broken: blender: found /fake/blender via PATH")
        for name in ("loc_broken", "loc_crash", "loc_found_broken"):
            self.assert_no_local_fail(name)

    def test_comfy_url_off_this_machine_is_never_contacted(self):
        self.assertRegex(self.line("loc_far", "comfy"), r"WARN .*FILM_COMFY_URL=http://192\.0\.2\.7:8188 is not this "
                                                        r"machine: not contacted")
        self.assertEqual(self.comfy_calls("far"), [])
        self.assert_no_local_fail("loc_far")

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

    def test_tts_python_venv(self):
        self.assertRegex(self.line("tts_venv", "tts"), r"OK .*vieneu 3\.8\.3 in FILM_TTS_PYTHON, v3 Turbo model")
        self.assertRegex(self.line("tts_venv", "tts-watermark"), r"OK .*resemble-perth 1\.0\.1 .* in FILM_TTS_PYTHON")
        self.assertRegex(self.line("tts_venv_bad", "tts"),
                         r"WARN .*FILM_TTS_PYTHON=.*missing is not an executable interpreter")
        self.assertRegex(self.line("tts_venv_bad", "tts-watermark"), r"WARN .*FILM_TTS_PYTHON")

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


class TestSetupStamp(unittest.TestCase):
    def test_setup_script_version_matches_its_header_and_is_stamped_where_doctor_reads(self):
        sh = (REPO / "docs" / "setup-script.sh").read_text()
        self.assertRegex(sh.splitlines()[1], r"^# Setup script v%s\b" % SETUP_VERSION)
        self.assertIn('echo "$SETUP_VERSION" > /opt/film-lab/setup-script.version', sh)
        self.assertIn("${FILM_SETUP_STAMP:-/opt/film-lab/setup-script.version}",
                      (REPO / "tools" / "doctor.sh").read_text())


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
    doctor_bad = L.doctor(wt)
    # work in progress on requirements.txt in the worktree: no pip run, the main checkout's stamp stays as it is
    stamp_before = (L.tmp / "stamp").read_text()
    with open(wt / "requirements.txt", "a") as f:
        f.write("example-wip-package==1.0\n")
    wip = L.hook(lab=wt)
    return dict(before=before, hook=hook, after=after, doctor_ok=doctor_ok, doctor_bad=doctor_bad, wip=wip,
                pip_calls=len(L.calls("pip")), stamp_same=(L.tmp / "stamp").read_text() == stamp_before)


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

    def test_worktree_never_runs_pip_nor_rewrites_the_stamp(self):
        r = self.r["worktree"]
        self.assertNotIn("pip install skipped", r["hook"][1], "same files as the stamp: nothing to say")
        rc, out, err = r["wip"]
        self.assertEqual(rc, 0, out + err)
        self.assertIn("film-lab: linked git worktree - pip install skipped and stamp kept", out)
        self.assertIn("AI Film Lab doctor (quick)", out)
        self.assertEqual(r["pip_calls"], 1, "only the main checkout's first start ran pip")
        self.assertTrue(r["stamp_same"])


CI_PY_SHIM = """#!/bin/bash
# python3 shim for the tools/ci.sh tests: pip never runs for real; SHIM_PYV fakes the version check.
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
  echo "$*" >> "$SHIM_LOG.pip"
  exit "${SHIM_PIP_RC:-0}"
fi
if [ -n "${SHIM_PYV:-}" ]; then
  for a in "$@"; do case "$a" in *version_info*) echo "$SHIM_PYV"; exit 0;; esac; done
fi
exec %s "$@"
"""


@unittest.skipUnless(BASH, "needs bash")
class TestCiScript(unittest.TestCase):
    """tools/ci.sh: usage, the python check, --install, and each failing step ending in exit 1. The real repo
    runs only one small test module; a fake lab (not a git checkout) holds a broken shell script."""

    @classmethod
    def setUpClass(cls):
        cls.td = Path(os.path.realpath(tempfile.mkdtemp(prefix="film-ci-")))
        shims = cls.td / "shims"
        shims.mkdir()
        write_exec(shims / "python3", CI_PY_SHIM % sys.executable)
        fake = cls.td / "fakelab"
        (fake / "tools" / "compose").mkdir(parents=True)
        (fake / "tests").mkdir()
        shutil.copy2(REPO / "tools" / "ci.sh", fake / "tools" / "ci.sh")
        (fake / "tools" / "compose" / "inline.py").write_text("print('compose kit v0.0.0: 1 files, lint ok')\n")
        (fake / "tests" / "test_x.py").write_text("import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n")
        (fake / "broken.sh").write_text("#!/bin/bash\nif then fi\n")
        ci, fci = REPO / "tools" / "ci.sh", fake / "tools" / "ci.sh"
        env = base_env(cls.td, PATH=str(shims) + os.pathsep + os.environ["PATH"], SHIM_LOG=str(cls.td / "shim"))
        jobs = {
            "help": ([ci, "--help"], {}),
            "bogus": ([ci, "--bogus"], {}),
            "one": ([ci, "--", "test_episode_id"], {}),
            "install": ([ci, "--install", "--", "test_episode_id"], {"SHIM_LOG": str(cls.td / "install")}),
            "pip_fails": ([ci, "--install"], {"SHIM_LOG": str(cls.td / "pipfail"), "SHIM_PIP_RC": "1"}),
            "old_python": ([ci], {"SHIM_PYV": "3.8.10"}),
            "missing_test": ([ci, "--", "test_this_module_does_not_exist"], {}),
            "broken_sh": ([fci], {}),
        }

        def go(item):
            name, ((script, *args), extra) = item
            return name, run([BASH, script, *args], dict(env, **extra))

        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            cls.r = dict(pool.map(go, jobs.items()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def calls(self, log):
        f = self.td / f"{log}.pip"
        return f.read_text().splitlines() if f.exists() else []

    def test_help_and_usage_errors(self):
        rc, out, err = self.r["help"]
        self.assertEqual(rc, 0, err)
        self.assertIn("--install", out)
        self.assertNotIn("ci: python", out)
        rc, out, err = self.r["bogus"]
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("--install", err)

    def test_selected_tests_pass_through_every_step(self):
        rc, out, err = self.r["one"]
        self.assertEqual(rc, 0, out + err)
        for want in ("ci: python 3.", "ci: bash -n ok", "ci: compose kit v", "lint ok", "ci: all steps passed"):
            self.assertIn(want, out)
        self.assertRegex(err, r"Ran \d+ tests")
        self.assertEqual(self.calls("shim"), [], "pip runs only with --install")

    def test_install_uses_requirements_ci(self):
        rc, out, err = self.r["install"]
        self.assertEqual(rc, 0, out + err)
        (pip,) = self.calls("install")
        self.assertIn("-r requirements-ci.txt", pip)
        self.assertIn("installed requirements-ci.txt", out)

    def test_each_failing_step_exits_1(self):
        cases = {"pip_fails": "pip install -r requirements-ci.txt", "old_python": "python 3.8.10 is too old",
                 "missing_test": "unit tests", "broken_sh": "bash -n: broken.sh"}
        for name, why in cases.items():
            rc, out, err = self.r[name]
            self.assertEqual(rc, 1, f"{name}: {out}{err}")
            self.assertIn(f"ci: FAILED: {why}", err, name)
            self.assertNotIn("all steps passed", out, name)


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
