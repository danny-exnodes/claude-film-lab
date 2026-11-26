#!/usr/bin/env python3
"""One GPU job at a time on the lab PC (RTX, 16 GB VRAM): a lab-wide lock for every agent, session and git worktree.

  python tools/gpu_run.py [--label L] [--wait SEC] -- <command ...>
        run the command while holding the GPU lock: waits while another job holds it (prints who), then runs the
        command and exits with its exit code. --wait SEC: give up after SEC seconds of waiting (exit 75, the
        command never ran). Default: wait as long as it takes.
  python tools/gpu_run.py status      who holds the GPU ("<label> · pid <n> · since <time>") or "free"

In Python (in-process, e.g. tools/blender/blender.py, tools/comfy/comfy.py):

    from gpu_run import gpu_lock, GpuBusy
    with gpu_lock("blender render s21", wait=None):
        ...                                   # the GPU work

`blender.py render|still|turntable|keyframes|lookbook` and `comfy.py run` take the lock by themselves (never for
--dry-run, check or find), so `gpu_run.py` is only needed around other GPU commands (an ad-hoc Blender script, a
one-off ComfyUI client). A command run by gpu_run that takes the lock again does not deadlock: the holder exports
FILM_GPU_HELD=<its pid> to its children, and a child whose FILM_GPU_HELD names the pid in the owner file goes on
without locking (the same holds for nested gpu_lock() blocks in one process).

The lock is ONE file for all git worktrees of the lab: <main checkout>/out/_gpu/gpu.lock (the main checkout is found
with `git rev-parse --git-common-dir`; outside git: this repo). The holder writes gpu.owner next to it, JSON
{"label": str, "pid": int, "since": "<ISO-8601 UTC>"}, and deletes it when done. The label is cut to
[A-Za-z0-9 _.:/-], 60 characters: the review monitor shows it on a public page, so it never carries a command line or
a path (callers pass short job names such as "blender render s21"). The operating system frees the lock when the
holder dies (Windows msvcrt.locking, POSIX flock); a stale gpu.owner is ignored and cleaned by `status`.

Env: FILM_GPU_LOCK (another lock file; gpu.owner goes next to it), FILM_GPU_QUEUE=0 (no lock at all: gpu_run runs
the command at once, gpu_lock() does nothing), FILM_GPU_WAIT (default seconds to wait in blender.py/comfy.py),
FILM_GPU_HELD (set by the holder for its children; never set it by hand).
Exit codes: the command's own; 75 the wait ran out (nothing was run); 2 bad arguments.
"""
import contextlib
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BUSY_EXIT = 75                  # EX_TEMPFAIL: the GPU stayed busy for --wait seconds, the command never ran
POLL = 1.0                      # seconds between tries while the GPU is busy
LABEL_MAX = 60
LABEL_BAD = re.compile(r"[^A-Za-z0-9 _.:/-]+")
HELD_ENV = "FILM_GPU_HELD"

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_depth = 0                      # nested gpu_lock() blocks of this process that hold the lock


class GpuBusy(TimeoutError):
    """The GPU stayed busy for the whole wait; nothing ran."""

    def __init__(self, waited, holder):
        self.waited, self.holder = waited, holder
        super().__init__(f"the GPU is still busy after {waited:.0f} s (held by: {describe(holder)})")


# --- places ------------------------------------------------------------------------------------------------------
_main = None


def main_checkout():
    """The main checkout of this repo (shared by every git worktree), else this repo's folder."""
    global _main
    if _main is None:
        _main = REPO
        try:
            r = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                               capture_output=True, text=True, timeout=10)
            common = r.stdout.strip()
            if r.returncode == 0 and common:
                common = os.path.normpath(common if os.path.isabs(common) else os.path.join(REPO, common))
                if os.path.basename(common) == ".git":
                    _main = os.path.dirname(common)
        except (OSError, subprocess.SubprocessError):
            pass
    return _main


def lock_path():
    env = (os.environ.get("FILM_GPU_LOCK") or "").strip()
    return os.path.abspath(env) if env else os.path.join(main_checkout(), "out", "_gpu", "gpu.lock")


def owner_path(lock=None):
    return os.path.join(os.path.dirname(lock or lock_path()), "gpu.owner")


def enabled():
    return (os.environ.get("FILM_GPU_QUEUE") or "1").strip().lower() not in ("0", "off", "no", "false")


def default_wait():
    """FILM_GPU_WAIT seconds, else None (wait as long as it takes)."""
    try:
        v = float(os.environ.get("FILM_GPU_WAIT") or "")
    except ValueError:
        return None
    return v if v >= 0 else None


def clean_label(label):
    """A label safe for the public review page: [A-Za-z0-9 _.:/-], at most 60 characters, never empty."""
    s = " ".join(LABEL_BAD.sub(" ", str(label or "")).split())[:LABEL_MAX].strip()
    return s or "gpu-job"


# --- owner file --------------------------------------------------------------------------------------------------
def read_owner(lock=None):
    """The owner JSON as a dict, or None (no file, unreadable)."""
    try:
        with open(owner_path(lock), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def describe(owner):
    if not owner:
        return "unknown (no gpu.owner)"
    return f"{owner.get('label', '?')} · pid {owner.get('pid', '?')} · since {owner.get('since', '?')}"


def _write_owner(lock, label):
    path = owner_path(lock)
    data = {"label": label, "pid": os.getpid(),
            "since": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}
    tmp = f"{path}.{os.getpid()}.tmp"
    for _ in range(5):                  # Windows: a reader may have the file open for a moment
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f)
                f.write("\n")
            os.replace(tmp, path)
            return data
        except OSError:
            time.sleep(0.05)
    with contextlib.suppress(OSError):
        os.remove(tmp)
    return data                         # the owner file is advisory: the lock itself is what counts


def _remove_owner(lock):
    for _ in range(5):
        try:
            os.remove(owner_path(lock))
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.05)


# --- the lock itself -----------------------------------------------------------------------------------------------
def _try_lock(f):
    """True when this open file now holds the exclusive lock (non-blocking)."""
    try:
        if os.name == "nt":
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f):
    with contextlib.suppress(OSError):
        if os.name == "nt":
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _open(lock):
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    return open(lock, "a+b")


def held_by_parent(lock=None):
    """True when FILM_GPU_HELD names the pid that the owner file says holds the lock (we run inside its job)."""
    held = (os.environ.get(HELD_ENV) or "").strip()
    if not held:
        return False
    owner = read_owner(lock)
    return bool(owner) and str(owner.get("pid")) == held


def status(lock=None):
    """(holder dict or None, free?) — checks the lock itself, so a stale owner file left by a killed job reads free."""
    lock = lock or lock_path()
    if not os.path.exists(lock):
        return None, True
    with _open(lock) as f:
        if _try_lock(f):
            _remove_owner(lock)         # nobody holds it: an owner file here is stale
            _unlock(f)
            return None, True
    return read_owner(lock), False


@contextlib.contextmanager
def gpu_lock(label="gpu-job", wait=None, *, on_wait=None, quiet=False):
    """Hold the lab's GPU lock for the block. wait: seconds before GpuBusy is raised (None = no limit).
    on_wait(owner dict or None): called when the wait starts and when the holder changes (for a progress line).
    Yields the owner dict written for this job, or None when no lock was taken (FILM_GPU_QUEUE=0, or the lock is
    already held by this process or by the parent job that started us)."""
    global _depth
    lock = lock_path()
    if not enabled() or _depth > 0 or held_by_parent(lock):
        _depth += 1
        try:
            yield None
        finally:
            _depth -= 1
        return
    label = clean_label(label)
    f = _open(lock)
    t0, last = time.monotonic(), ()
    try:
        while not _try_lock(f):
            owner = read_owner(lock)
            key = (owner or {}).get("pid"), (owner or {}).get("label")
            if key != last:
                last = key
                if not quiet:
                    print(f"gpu: waiting for the GPU (held by: {describe(owner)})", file=sys.stderr, flush=True)
                if on_wait:
                    with contextlib.suppress(Exception):
                        on_wait(owner)
            waited = time.monotonic() - t0
            if wait is not None and waited >= wait:
                raise GpuBusy(waited, owner)
            time.sleep(POLL if wait is None else max(0.0, min(POLL, wait - waited)))
        if last and not quiet:
            print(f"gpu: got the GPU after {time.monotonic() - t0:.0f} s ({label})", file=sys.stderr, flush=True)
        owner = _write_owner(lock, label)
        prev = os.environ.get(HELD_ENV)
        os.environ[HELD_ENV] = str(os.getpid())         # children (Blender, a nested tool) inherit it
        _depth += 1
        try:
            yield owner
        finally:
            _depth -= 1
            if prev is None:
                os.environ.pop(HELD_ENV, None)
            else:
                os.environ[HELD_ENV] = prev
            _remove_owner(lock)
            _unlock(f)
    finally:
        f.close()


# --- CLI -----------------------------------------------------------------------------------------------------------
USAGE = "usage: gpu_run.py [--label L] [--wait SEC] -- <command ...>  |  gpu_run.py status"


def _parse(argv):
    label = os.environ.get("FILM_AGENT") or "gpu-job"
    wait = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return label, wait, argv[i + 1:]
        if a in ("--label", "--wait") and i + 1 < len(argv):
            if a == "--label":
                label = argv[i + 1]
            else:
                try:
                    wait = float(argv[i + 1])
                except ValueError:
                    raise SystemExit(f"gpu_run: --wait must be seconds, not {argv[i + 1]!r}\n{USAGE}") from None
                if wait < 0:
                    raise SystemExit(f"gpu_run: --wait must be >= 0\n{USAGE}")
            i += 2
            continue
        if a.startswith("--label="):
            label = a.split("=", 1)[1]
        elif a.startswith("--wait="):
            return _parse(argv[:i] + ["--wait", a.split("=", 1)[1]] + argv[i + 1:])
        elif a.startswith("-"):
            raise SystemExit(f"gpu_run: unknown option {a}\n{USAGE}")
        else:
            return label, wait, argv[i:]          # the command starts here (no `--`)
        i += 1
    return label, wait, []


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if argv == ["status"]:
        if not enabled():
            print("free (FILM_GPU_QUEUE=0: the GPU queue is off)")
            return 0
        owner, free = status()
        print("free" if free else describe(owner))
        return 0
    try:
        label, wait, cmd = _parse(argv)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    if not cmd:
        print(USAGE, file=sys.stderr)
        return 2
    if not enabled():
        print("gpu: FILM_GPU_QUEUE=0: running without the GPU lock", file=sys.stderr, flush=True)
        return subprocess.call(cmd)
    try:
        with gpu_lock(label, wait):
            try:
                proc = subprocess.Popen(cmd)
            except OSError as e:
                print(f"gpu_run: cannot run {cmd[0]}: {e}", file=sys.stderr)
                return 127
            while True:
                try:
                    return proc.wait()
                except KeyboardInterrupt:     # the child got the Ctrl+C too: wait for it, then free the GPU
                    continue
    except GpuBusy as e:
        print(f"gpu_run: {e}; the command was not run", file=sys.stderr)
        return BUSY_EXIT


if __name__ == "__main__":
    sys.exit(main())
