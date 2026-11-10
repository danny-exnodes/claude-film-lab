"""Shared helpers for the unittest suites (python3 -m unittest discover -s tests -v)."""
import contextlib, importlib.util, io, os, shutil, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
FIX = Path(__file__).resolve().parent / "fixtures"
EPISODE_FIX = FIX / "series" / "test-series" / "ep01-test-ep"
STYLE_FIX = FIX / "styles" / "test-style"

# Safety net: nothing in the tests may reach the real Ark API. ark.call is always mocked, and the
# base URL points at a closed local port in case a mock is ever missing.
os.environ["ARK_BASE"] = "http://127.0.0.1:9/never-call-the-real-api"


def load(rel, name=None):
    """Import a tool script by path (its __main__ block does not run)."""
    path = TOOLS / rel
    name = name or "film_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_main(main, argv):
    """Run a tool's main(argv); returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
            code = rc if isinstance(rc, int) else 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue(), err.getvalue()


class TmpDirCase:
    """Mixin: self.tmp is a fresh temporary directory (Path)."""

    def setUp(self):
        super().setUp()
        self._td = tempfile.mkdtemp(prefix="film-test-")
        self.tmp = Path(self._td)

    def tearDown(self):
        shutil.rmtree(self._td, ignore_errors=True)
        super().tearDown()
