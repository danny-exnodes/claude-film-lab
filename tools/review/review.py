#!/usr/bin/env python3
"""Run the Film Lab review web app (Docker) and publish files to it. Standard library only; Windows and Linux.

  python tools/review/review.py up [--no-ngrok] [--no-monitor] [--comfy-log PATH] [--dry-run]
                                    # vendor check -> docker compose up -d --build -> monitor.py (detached) -> ngrok
  python tools/review/review.py down                           # stop monitor + container (the volume stays) + our ngrok
  python tools/review/review.py monitor [--stop|--restart] [--comfy-log PATH] [--interval S]   # only monitor.py
  python tools/review/review.py url                            # the public ngrok URL of port 8790
  python tools/review/review.py status                         # builds on the server (local port 8790)
  python tools/review/review.py publish-video <mp4> --build ID --label L [--title T] [--project P] [--open]
  python tools/review/review.py publish-model <glb> --build ID [--label L] [--title T] [--project P] [--open]

The public URL shows everything that was published, to anyone who has the link (no login: the owner's choice).
Only files under out/_review/media are served. ngrok's own config and authtoken are never read or printed: the URL
comes from ngrok's local API (http://127.0.0.1:4040/api/tunnels).
Exit: 0 ok · 1 failed (Docker, ngrok, server unreachable) · 2 refused (vendor files missing, bad arguments).
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import client  # noqa: E402
import vendor_three  # noqa: E402

COMPOSE = os.path.join("tools", "review", "docker-compose.yml")
PUBLIC = "http://127.0.0.1:8790"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"
STATE = os.path.join(LAB, "out", "_review")
NGROK_PID = os.path.join(STATE, "ngrok.pid")
MONITOR_PID = os.path.join(STATE, "monitor.pid")
MONITOR_LOG = os.path.join(STATE, "monitor.log")
MONITOR = os.path.join(HERE, "monitor.py")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(msg):
    print(f"review: {msg}", flush=True)


def err(msg):
    print(f"review: {msg}", file=sys.stderr, flush=True)


def get_json(url, timeout=3):
    with _OPENER.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def compose_cmd(*args):
    return ["docker", "compose", "-f", COMPOSE] + list(args)


def show(cmd):
    return " ".join(f'"{c}"' if " " in c else c for c in cmd)


def public_url(tunnels):
    """The https public URL of a tunnel to port 8790 in ngrok's /api/tunnels answer, else None."""
    best = None
    for t in tunnels.get("tunnels") or []:
        addr = str((t.get("config") or {}).get("addr", ""))
        if not addr.rstrip("/").endswith(":8790") and addr != "8790":
            continue
        url = t.get("public_url") or ""
        if url.startswith("https://"):
            return url
        best = best or url
    return best


def ngrok_url():
    try:
        return public_url(get_json(NGROK_API, timeout=2))
    except Exception:
        return None


def wait_health(seconds=40):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if get_json(PUBLIC + "/api/health", timeout=2).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def start_ngrok(exe):
    os.makedirs(STATE, exist_ok=True)
    cmd = [exe, "http", "127.0.0.1:8790", "--log", "stdout"]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    with open(NGROK_PID, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    return proc


# ------------------------------------------------------------------ monitor.py (detached)
def monitor_cmd(a):
    cmd = [sys.executable, MONITOR]
    if getattr(a, "interval", None):
        cmd += ["--interval", f"{a.interval:g}"]
    if getattr(a, "comfy_log", None):
        cmd += ["--comfy-log", a.comfy_log]
    return cmd


def process_name(pid):
    """The image name of a live process ('python.exe'), else None."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if os.name == "nt":
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                               timeout=10, creationflags=0x08000000)
        except (OSError, subprocess.SubprocessError):
            return None
        line = r.stdout.decode("utf-8", "replace").strip()
        return line.split('","')[0].strip('"') if line.startswith('"') else None
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def monitor_pid():
    """PID of our running monitor (from monitor.pid, checked to be a live python), else None."""
    try:
        with open(MONITOR_PID, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    name = (process_name(pid) or "").lower()
    return pid if name.startswith("python") else None


def start_monitor(a):
    pid = monitor_pid()
    if pid:
        say(f"monitor already runs (pid {pid})")
        return 0
    os.makedirs(STATE, exist_ok=True)
    try:
        if os.path.getsize(MONITOR_LOG) > 1 << 20:
            os.remove(MONITOR_LOG)
    except OSError:
        pass
    kw = {"stdin": subprocess.DEVNULL, "cwd": LAB}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with open(MONITOR_LOG, "ab") as log:
        proc = subprocess.Popen(monitor_cmd(a), stdout=log, stderr=subprocess.STDOUT, env=env, **kw)
    with open(MONITOR_PID, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    say(f"monitor started (pid {proc.pid}; log {MONITOR_LOG})")
    return 0


def stop_monitor():
    pid = monitor_pid()
    if pid:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        say(f"stopped monitor (pid {pid})")
    try:
        os.remove(MONITOR_PID)
    except OSError:
        pass


def cmd_monitor(a):
    if a.dry_run:
        if a.stop:
            say("dry-run: would stop the monitor of " + MONITOR_PID)
        else:
            print(show(monitor_cmd(a)) + "   # detached; pid in " + MONITOR_PID)
        return 0
    if a.stop or a.restart:
        stop_monitor()
    if a.stop:
        return 0
    return start_monitor(a)


# ------------------------------------------------------------------ commands
def cmd_up(a):
    problems = vendor_three.verify()
    if problems:
        msg = "three.js is not vendored: " + "; ".join(problems[:3]) + (" ..." if len(problems) > 3 else "")
        fix = "python tools/review/vendor_three.py --from <three package dir> (e.g. node_modules/three, 0.186.1)"
        if not a.dry_run:
            err(f"refused: {msg}\nreview: run {fix}")
            return 2
        say(f"WARNING {msg} (up would refuse; {fix})")
    media = os.path.join(LAB, "out", "_review", "media")
    up = compose_cmd("up", "-d", "--build")
    if a.dry_run:
        say(f"mkdir {media}")
        print(show(up))
        if not a.no_monitor:
            print(show(monitor_cmd(a)) + "   # detached; pid in " + MONITOR_PID)
        if not a.no_ngrok:
            print(show(["ngrok", "http", "127.0.0.1:8790", "--log", "stdout"]) + "   # detached; URL from " + NGROK_API)
        say("dry-run: nothing started")
        return 0
    os.makedirs(media, exist_ok=True)
    if not shutil.which("docker"):
        err("docker not found on PATH (start Docker Desktop)")
        return 1
    say(show(up))
    r = subprocess.run(up, cwd=LAB)
    if r.returncode:
        err(f"docker compose failed (exit {r.returncode})")
        return 1
    if wait_health():
        say(f"server ok: {PUBLIC} (local)")
    else:
        err(f"the container started but {PUBLIC}/api/health does not answer yet "
            f"(docker compose -f {COMPOSE} logs film-lab-review)")
        return 1
    if not a.no_monitor:
        start_monitor(a)
    if a.no_ngrok:
        say("--no-ngrok: local only")
        return 0
    url = ngrok_url()
    if not url:
        exe = shutil.which("ngrok")
        if not exe:
            err("ngrok not found on PATH (the server runs locally; install/sign in to ngrok, then: review.py up)")
            return 1
        start_ngrok(exe)
        for _ in range(30):
            time.sleep(0.5)
            url = ngrok_url()
            if url:
                break
    if not url:
        err(f"ngrok started but no tunnel to 8790 is listed at {NGROK_API}")
        return 1
    say("public URL (anyone with the link sees every published build, no login):")
    print(url)
    return 0


def cmd_down(a):
    cmd = compose_cmd("down")
    if a.dry_run:
        print(show(cmd))
        return 0
    stop_monitor()
    rc = 0
    if shutil.which("docker"):
        say(show(cmd))
        rc = subprocess.run(cmd, cwd=LAB).returncode
    else:
        err("docker not found on PATH")
        rc = 1
    if os.path.isfile(NGROK_PID):
        try:
            with open(NGROK_PID, encoding="utf-8") as f:
                pid = int(f.read().strip())
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, 15)
            say(f"stopped ngrok (pid {pid})")
        except (OSError, ValueError):
            pass
        try:
            os.remove(NGROK_PID)
        except OSError:
            pass
    return 1 if rc else 0


def cmd_url(a):
    url = ngrok_url()
    if not url:
        err(f"no ngrok tunnel to 8790 ({NGROK_API}); start one with: python tools/review/review.py up")
        return 1
    print(url)
    return 0


def cmd_status(a):
    try:
        builds = get_json(PUBLIC + "/api/builds").get("builds", [])
    except Exception as e:
        err(f"the review server does not answer at {PUBLIC} ({e}); start it: python tools/review/review.py up")
        return 1
    if not builds:
        say("no builds yet")
    for b in builds:
        job = b.get("job") or {}
        jtxt = f" · {job.get('tool')} {job.get('status')}" if job else ""
        print(f"{b['id']:24} {b['status']:9} {round(100 * (b.get('progress') or 0)):3d}%  {b.get('steps', 0):3d} steps "
              f"{b.get('renders', 0):2d} renders  {b.get('title', '')}{jtxt}")
    pid = monitor_pid()
    say(f"monitor: running (pid {pid})" if pid else "monitor: not running (python tools/review/review.py monitor)")
    try:
        say_machine(get_json(PUBLIC + "/api/metrics?window=10m"), get_json(PUBLIC + "/api/comfy"))
    except Exception:
        pass
    url = ngrok_url()
    say(f"public URL: {url}" if url else "no ngrok tunnel (local only)")
    return 0


def say_machine(m, c):
    s = m.get("latest") or {}
    if s:
        g = (s.get("gpus") or [{}])[0]

        def gb(b):
            return f"{b / 2 ** 30:.1f}" if b is not None else "?"
        disks = " ".join(f"{d['name']} {gb(d['free'])} GB free" for d in s.get("disks") or [])
        jobs = ", ".join(p["name"] + (f" x{p['count']}" if p["count"] > 1 else "") for p in s.get("procs") or [])
        say(f"machine ({'live' if m.get('online') else 'stale'}, {m.get('age')} s ago): CPU {s.get('cpu')}% · "
            f"RAM {gb(s.get('ram_used'))}/{gb(s.get('ram_total'))} GB · GPU {g.get('util')}% · VRAM "
            f"{gb(g.get('mem_used'))}/{gb(g.get('mem_total'))} GB · {g.get('temp')} C · {g.get('power')} W · "
            f"{disks}{' · jobs: ' + jobs if jobs else ''}")
    cs = c.get("comfy") or {}
    if cs:
        cur = cs.get("current") or {}
        say(f"ComfyUI: {'up' if cs.get('up') else 'down'} · running {cs.get('running')} · pending {cs.get('pending')}"
            + (f" · step {cur['step']}/{cur['total']} ({cur.get('s_per_step')} s/step)" if cur else ""))


def mp4_duration(path):
    """Seconds from the mp4's mvhd box (None when it cannot be read)."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 << 20)
    except OSError:
        return None

    def boxes(buf, start, end):
        i = start
        while i + 8 <= end:
            size, typ = struct.unpack(">I4s", buf[i:i + 8])
            hdr = 8
            if size == 1:
                size = struct.unpack(">Q", buf[i + 8:i + 16])[0]
                hdr = 16
            elif size == 0:
                size = end - i
            if size < hdr:
                return
            yield typ, i + hdr, min(i + size, end)
            i += size

    for typ, s, e in boxes(data, 0, len(data)):
        if typ == b"moov":
            for t2, s2, e2 in boxes(data, s, e):
                if t2 == b"mvhd":
                    ver = data[s2]
                    if ver == 1:
                        scale, dur = struct.unpack(">IQ", data[s2 + 20:s2 + 32])
                    else:
                        scale, dur = struct.unpack(">II", data[s2 + 12:s2 + 20])
                    return round(dur / scale, 3) if scale else None
    return None


def glb_stats(path):
    """{'verts', 'tris', 'meshes', 'materials', 'animations'} from a .glb's JSON chunk (None when unreadable)."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
            magic, _, _, clen, ctype = struct.unpack("<4sIII4s", head)
            if magic != b"glTF" or ctype != b"JSON":
                return None
            gltf = json.loads(f.read(clen).decode("utf-8"))
    except (OSError, ValueError, struct.error):
        return None
    acc = gltf.get("accessors") or []
    verts = tris = 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            pos = (prim.get("attributes") or {}).get("POSITION")
            if pos is not None and pos < len(acc):
                verts += acc[pos].get("count", 0)
            idx = prim.get("indices")
            n = acc[idx].get("count", 0) if idx is not None and idx < len(acc) else (
                acc[pos].get("count", 0) if pos is not None and pos < len(acc) else 0)
            if prim.get("mode", 4) == 4:
                tris += n // 3
    return {"verts": verts, "tris": tris, "meshes": len(gltf.get("meshes") or []),
            "materials": len(gltf.get("materials") or []), "animations": len(gltf.get("animations") or [])}


def build_exists(bid):
    try:
        get_json(f"{PUBLIC}/api/builds/{bid}", timeout=2)
        return True
    except Exception:
        return False


def _review(a, kind):
    """An existing build keeps its title and kind unless --title is given; a new one is named after the label."""
    if a.title or not build_exists(a.build):
        return client.Review(a.build, a.title or a.label or a.build, kind, project=a.project)
    return client.Review(a.build, None, None, project=a.project)


def cmd_publish_video(a):
    if not os.path.isfile(a.mp4):
        err(f"refused: no such file {a.mp4}")
        return 2
    rv = _review(a, "clip")
    dur = mp4_duration(a.mp4)
    ok = rv.render(a.label, video=a.mp4, duration=dur, fps=a.fps, frames=round(dur * a.fps) if dur and a.fps else None,
                   engine=a.engine)
    if ok and not a.open:
        ok = rv.done()
    if not ok:
        err(f"not delivered ({rv.last_error}); is the server up? python tools/review/review.py up --no-ngrok")
        return 1
    say(f"published {a.mp4} -> build {a.build} ({a.label}{f', {dur:g} s' if dur else ''})")
    return 0


def cmd_publish_model(a):
    if not os.path.isfile(a.glb):
        err(f"refused: no such file {a.glb}")
        return 2
    rv = _review(a, "model")
    stats = glb_stats(a.glb) or {}
    ok = rv.step(a.label or os.path.splitext(os.path.basename(a.glb))[0], glb=a.glb, stats=stats)
    if ok and not a.open:
        ok = rv.done()
    if not ok:
        err(f"not delivered ({rv.last_error}); is the server up? python tools/review/review.py up --no-ngrok")
        return 1
    say(f"published {a.glb} -> build {a.build} ({stats.get('verts', '?')} verts)")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="review.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    q = sp.add_parser("up", help="verify vendor files, docker compose up -d --build, then ngrok (unless --no-ngrok)")
    q.add_argument("--no-ngrok", action="store_true", help="local only (http://127.0.0.1:8790)")
    q.add_argument("--no-monitor", action="store_true", help="do not start monitor.py (machine metrics, ComfyUI)")
    q.add_argument("--dry-run", action="store_true", help="print the commands, start nothing")
    q.add_argument("--comfy-log", default=None, help="ComfyUI log for monitor.py (default: comfy.py start's log)")
    q.add_argument("--interval", type=float, default=None, help="monitor.py interval (default 2 s)")
    q = sp.add_parser("monitor", help="start (or --stop) only monitor.py, detached; pid in out/_review/monitor.pid")
    q.add_argument("--stop", action="store_true")
    q.add_argument("--restart", action="store_true", help="stop the running monitor first (new options)")
    q.add_argument("--comfy-log", default=None)
    q.add_argument("--interval", type=float, default=None)
    q.add_argument("--dry-run", action="store_true")
    q = sp.add_parser("down", help="docker compose down (keeps the database volume) and stop our ngrok")
    q.add_argument("--dry-run", action="store_true")
    sp.add_parser("url", help="the public ngrok URL (from ngrok's local API)")
    sp.add_parser("status", help="builds on the local server")
    pv = sp.add_parser("publish-video", help="publish a .mp4 to a build (marks the build done unless --open)")
    pm = sp.add_parser("publish-model", help="publish a .glb to a build (marks the build done unless --open)")
    for q, arg in ((pv, "mp4"), (pm, "glb")):
        q.add_argument(arg)
        q.add_argument("--build", required=True, help="build id ([A-Za-z0-9][A-Za-z0-9._-]{0,63})")
        q.add_argument("--label", required=(arg == "mp4"), default=None)
        q.add_argument("--title", default=None, help="build title (default: the label)")
        q.add_argument("--project", default=None)
        q.add_argument("--open", action="store_true", help="leave the build open (do not mark it done)")
        if arg == "mp4":
            q.add_argument("--fps", type=float, default=24.0)
            q.add_argument("--engine", default=None, help="e.g. blender, comfy:h3-i2v")
    a = p.parse_args(argv)
    if getattr(a, "build", None) and not client.BUILD_ID.match(a.build):
        err("refused: --build must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        return 2
    fn = {"up": cmd_up, "down": cmd_down, "monitor": cmd_monitor, "url": cmd_url, "status": cmd_status, "publish-video": cmd_publish_video,
          "publish-model": cmd_publish_model}[a.cmd]
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
