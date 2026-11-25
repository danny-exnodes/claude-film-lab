"""What may be tracked in the repo: no project data, no media, no big files; scripts stay executable;
the pip pins of the environment setup script equal requirements.txt."""
import re, shutil, subprocess, unittest

import helpers

REPO = helpers.REPO
GIT = shutil.which("git")
MEDIA = re.compile(r"\.(png|jpe?g|webp|mp4|mov|wav|mp3|zip|onnx)$", re.I)
# Media files that are tracked on purpose. None today: fixtures are text, test images are drawn at run time.
MEDIA_ALLOWED = set()
MAX_BYTES = 500 * 1024


def tracked():
    if not GIT:
        return None
    r = subprocess.run([GIT, "-C", str(REPO), "ls-files", "-s", "-z"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout:
        return None
    out = {}
    for entry in r.stdout.split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            out[path] = meta.split()[0]
    return out


FILES = tracked()


@unittest.skipUnless(FILES, "not a git checkout")
class TestRepoHygiene(unittest.TestCase):
    def test_no_project_data_folders(self):
        bad = [p for p in FILES if p.startswith(("projects/", "series/", "out/")) and p != "out/.gitkeep"]
        self.assertEqual(bad, [], "project data lives on Drive, never in the repo")

    def test_no_media(self):
        bad = [p for p in FILES if MEDIA.search(p) and p not in MEDIA_ALLOWED]
        self.assertEqual(bad, [], "media is never committed (add to MEDIA_ALLOWED only on purpose)")

    def test_no_big_files(self):
        bad = [p for p in FILES if (REPO / p).is_file() and (REPO / p).stat().st_size > MAX_BYTES]
        self.assertEqual(bad, [], "tracked file over 500 KB")

    def test_scripts_are_executable(self):
        for p in ("tools/doctor.sh", ".claude/hooks/session-start.sh", "tools/ci.sh"):
            self.assertEqual(FILES.get(p), "100755", p)

    def test_ci_files_are_tracked(self):
        # The workflow is a template the owner copies by hand to .github/workflows/ (cloud sessions cannot push it).
        for p in ("docs/ci/tests.yml", "requirements-ci.txt", "tools/ci.sh"):
            self.assertIn(p, FILES)


class TestPins(unittest.TestCase):
    def test_requirements_pins_are_in_the_setup_script(self):
        setup = (REPO / "docs" / "setup-script.sh").read_text()
        pins = [l.strip() for l in (REPO / "requirements.txt").read_text().splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        self.assertTrue(pins)
        for pin in pins:
            self.assertIn("==", pin, "requirements.txt holds exact pins")
            self.assertIn(f'"{pin}"', setup, f"docs/setup-script.sh must install {pin}")


def pins(path):
    return {l.split("==")[0].strip().lower(): l.strip() for l in (REPO / path).read_text().splitlines()
            if l.strip() and not l.lstrip().startswith("#")}


class TestCi(unittest.TestCase):
    """tools/ci.sh, requirements-ci.txt and the workflow template docs/ci/tests.yml (tools/ci.sh itself runs in
    tests/test_env_scripts.py)."""

    def test_ci_requirements_are_exact_pins_without_heavy_packages(self):
        ci = pins("requirements-ci.txt")
        self.assertEqual(set(ci), {"numpy", "scipy", "pillow", "pyyaml"})
        for line in ci.values():
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==\d[\w.]*$")
        for heavy in ("rembg", "onnxruntime", "torch", "vieneu"):
            self.assertFalse([k for k in ci if heavy in k], heavy)

    def test_pyyaml_pin_equals_requirements_txt(self):
        self.assertEqual(pins("requirements-ci.txt")["pyyaml"], pins("requirements.txt")["pyyaml"])

    def test_workflow_template_parses_and_runs_ci_sh(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        text = (REPO / "docs" / "ci" / "tests.yml").read_text(encoding="utf-8")
        wf = yaml.safe_load(text)
        on = wf.get("on", wf.get(True))                     # YAML 1.1 reads a bare `on` key as True
        self.assertIn("pull_request", on)
        self.assertIn("push", on)
        self.assertEqual(wf["permissions"], {"contents": "read"})
        (job,) = wf["jobs"].values()
        runs = [s.get("run", "") for s in job["steps"]]
        self.assertIn("bash tools/ci.sh --install", runs)
        py = [s["with"]["python-version"] for s in job["steps"] if "setup-python" in s.get("uses", "")]
        self.assertEqual(len(py), 1)
        self.assertGreaterEqual(tuple(map(int, str(py[0]).split("."))), (3, 10))
        self.assertNotIn("secrets.", text, "the test workflow needs no secret")
        for step in job["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^actions/[\w-]+@v\d+$")

    def test_ci_script_names_its_requirements_file(self):
        self.assertIn("-r requirements-ci.txt", (REPO / "tools" / "ci.sh").read_text())


class TestTestHelpers(unittest.TestCase):
    """tests/helpers.py: paths outside the repo never break an import (the suite also runs as a non-root user)."""

    def test_exists_answers_false_on_permission_error(self):
        from unittest import mock
        with mock.patch("pathlib.Path.exists", side_effect=PermissionError(13, "Permission denied")):
            self.assertFalse(helpers.exists("/no-access/cinecode/.git"))
        with mock.patch("pathlib.Path.is_file", side_effect=PermissionError(13, "Permission denied")):
            self.assertFalse(helpers.exists("/no-access/x", "is_file"))
        self.assertTrue(helpers.exists(REPO / "tests" / "helpers.py", "is_file"))
        self.assertFalse(helpers.exists(REPO / "tests", "is_file"))

    def test_cinecode_dir_follows_the_environment(self):
        from pathlib import Path
        from unittest import mock
        with mock.patch.dict("os.environ", {"CINECODE_DIR": "/opt/elsewhere/cinecode"}):
            self.assertEqual(helpers.cinecode_dir(), Path("/opt/elsewhere/cinecode"))
        with mock.patch.dict("os.environ", {"CINECODE_DIR": ""}):
            self.assertEqual(helpers.cinecode_dir(), Path.home() / ".claude" / "skills" / "cinecode")

    def test_no_test_hardcodes_the_root_home(self):
        # /root/... raises PermissionError for other users: use helpers.CINECODE / helpers.exists instead
        bad = []
        for path in sorted((REPO / "tests").glob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if path.name != "helpers.py" and re.search(r"""["']/root(/|["'])""", code):
                    bad.append(f"{path.name}:{n}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
