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
        for p in ("tools/doctor.sh", ".claude/hooks/session-start.sh"):
            self.assertEqual(FILES.get(p), "100755", p)


class TestPins(unittest.TestCase):
    def test_requirements_pins_are_in_the_setup_script(self):
        setup = (REPO / "docs" / "setup-script.sh").read_text()
        pins = [l.strip() for l in (REPO / "requirements.txt").read_text().splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        self.assertTrue(pins)
        for pin in pins:
            self.assertIn("==", pin, "requirements.txt holds exact pins")
            self.assertIn(f'"{pin}"', setup, f"docs/setup-script.sh must install {pin}")


if __name__ == "__main__":
    unittest.main()
