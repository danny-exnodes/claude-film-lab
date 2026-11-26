"""tools/review/ code-review fixes: tags only from paths inside the lab (no user/folder names on the public page), the
cloudflared URL of the running tunnel only, every started tunnel stopped by `down` (one kind at a time), pid files kept
when a process cannot be inspected, a malformed <media>/_tags.json never stops a publisher, published files are copies
(no hard link to a working file, no overwrite), group names that are JavaScript object keys refused everywhere, exact
seeds above 2**53, and the watcher's tree killed on stop. No Docker, no tunnel binary, no Blender is ever run."""
import io, json, os, shutil, subprocess, sys, unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import helpers
from helpers import REPO, TmpDirCase, run_main
from test_review import ServerCase, FakeIngest, server, client, review

NODE = shutil.which("node")
WEB = REPO / "tools" / "review" / "web"


# ------------------------------------------------------------------ 1. path_tags: only inside the lab
class TestPathTags(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.lab = self.tmp / "wt" / "lab-worktree"
        self.main = self.tmp / "home" / "danny" / "projects" / "danny" / "claude-film-lab"
        for p in (self.lab, self.main):
            p.mkdir(parents=True)
        for p in (mock.patch.object(client, "LAB", str(self.lab)),
                  mock.patch.object(client, "main_checkout", lambda path=None: str(self.main))):
            p.start()
            self.addCleanup(p.stop)

    def test_lab_paths_give_tags(self):
        self.assertEqual(client.path_tags(str(self.lab / "out" / "shk" / "ep01" / "ledger.csv")),
                         {"project": "shk", "episode": "ep01"})
        self.assertEqual(client.path_tags(str(self.main / "out" / "shk" / "q01t03" / "clips" / "x_s21_h3_v01.mp4")),
                         {"project": "shk", "episode": "q01t03", "shot": "s21"}, "the main checkout counts too")
        self.assertEqual(client.path_tags("projects/shk/q01-t03-phuong/shots3d/s07.json"),
                         {"project": "shk", "episode": "q01t03", "shot": "s07"}, "relative = relative to the lab")

    def test_names_outside_the_lab_never_become_chips(self):
        leaks = [
            str(self.main / "out" / "_lookdev" / "x.png"),                       # _-prefixed: no project
            str(self.tmp / "home" / "danny" / "projects" / "danny" / "x.png"),  # above the lab: 'danny' is a name
            str(self.tmp / "Desktop" / "projects" / "secret" / "ep01" / "s21.png"),
            str(self.tmp / "out" / "secret" / "q01t03" / "s05.mp4"),            # an out/ that is not the lab's
            r"C:\Users\x\Desktop\projects\secret\x.png",
            r"D:\Projects\Danny\claude-film-lab\out\_lookdev\x",
            "../outside/out/secret/ep02/s09.png",                                 # '..' never leaves the lab
            "out/../../secret/ep02/x.png",
            str(self.lab / "projects"),                                          # no project folder
        ]
        for p in leaks:
            self.assertEqual(client.path_tags(p), {}, p)
        tags = client.path_tags(str(self.tmp / "Desktop" / "projects" / "secret" / "x.png"),
                                str(self.lab / "out" / "shk" / "x.png"))
        self.assertEqual(tags, {"project": "shk"}, "a later lab path still counts")
        self.assertEqual(client.path_tags(None, 5, ""), {})


# ------------------------------------------------------------------ 2.-4. tunnels and pid files
class ReviewState(TmpDirCase, unittest.TestCase):
    """review.py with its state folder, pid files and process table in tmp."""

    def setUp(self):
        super().setUp()
        self.table = {}                 # pid -> process info; None: alive but the query failed
        self.killed = []
        self.runs = []
        st = self.tmp
        for p in (mock.patch.object(review, "STATE", str(st)),
                  mock.patch.object(review, "MONITOR_PID", str(st / "monitor.pid")),
                  mock.patch.object(review, "MONITOR_LOG", str(st / "monitor.log")),
                  mock.patch.object(review, "NGROK_PID", str(st / "ngrok.pid")),
                  mock.patch.object(review, "CLOUDFLARED_PID", str(st / "cloudflared.pid")),
                  mock.patch.object(review, "CLOUDFLARED_LOG", str(st / "cloudflared.log")),
                  mock.patch.object(review, "TUNNEL_STATE", str(st / "tunnel.json")),
                  mock.patch.object(review, "pid_alive", lambda pid: int(pid) in self.table),
                  mock.patch.object(review, "process_info", lambda pid: self.table.get(int(pid))),
                  mock.patch.object(review, "kill", lambda pid, tree=False: self.killed.append((pid, tree)))):
            p.start()
            self.addCleanup(p.stop)

    CF = {"name": "cloudflared.exe", "cmdline": "cloudflared tunnel --url http://127.0.0.1:8790"}
    NGROK = {"name": "ngrok.exe", "cmdline": "ngrok http 127.0.0.1:8790"}
    MON = {"name": "python.exe", "cmdline": "python D:\\lab\\tools\\review\\monitor.py"}
    WATCH = {"name": "python3", "cmdline": "python3 /lab/tools/review/watch.py shk"}

    def fake_run(self, cmd, **kw):
        self.runs.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")


class TestCloudflaredUrl(ReviewState):
    def test_the_log_only_counts_while_our_cloudflared_runs(self):
        Path(review.CLOUDFLARED_LOG).write_text("INF https://dead-old-1111.trycloudflare.com\n", encoding="utf-8")
        with mock.patch.object(review, "get_json", side_effect=OSError("no metrics")):
            self.assertIsNone(review.cloudflared_url(), "no cloudflared runs: the old URL is dead")
            self.table[300] = self.CF
            Path(review.CLOUDFLARED_PID).write_text("300")
            self.assertEqual(review.cloudflared_url(), "https://dead-old-1111.trycloudflare.com")
            del self.table[300]
            with mock.patch("sys.stdout"):
                self.assertIsNone(review.cloudflared_url())

    def test_a_new_start_truncates_the_log(self):
        log = Path(review.CLOUDFLARED_LOG)
        log.write_text("INF https://dead-old-1111.trycloudflare.com\n", encoding="utf-8")

        class P:
            pid = 301

            def poll(self):
                return None

        def popen(cmd, stdout=None, **kw):
            stdout.write(b"INF |  https://fresh-new-2222.trycloudflare.com  |\n")
            stdout.flush()
            return P()

        with mock.patch.object(review.subprocess, "Popen", popen), mock.patch.object(review.time, "sleep"), \
                mock.patch.object(review, "get_json", side_effect=OSError("no metrics")), mock.patch("sys.stdout"):
            url, why = review.start_tunnel("cloudflared", "cloudflared")
        self.assertEqual((url, why), ("https://fresh-new-2222.trycloudflare.com", None))
        self.assertNotIn("dead-old", log.read_text(encoding="utf-8"))
        self.assertEqual(Path(review.CLOUDFLARED_PID).read_text(), "301")


class TestTunnelState(ReviewState):
    def up(self, *args):
        with mock.patch.object(review.vendor_three, "verify", lambda *a, **k: []), \
                mock.patch.object(review.shutil, "which", lambda x: "/usr/bin/" + x), \
                mock.patch.object(review, "ngrok_url", lambda: None), \
                mock.patch.object(review, "tailscale_status", lambda exe: ("Running", "lab.tail1.ts.net")), \
                mock.patch.object(review.subprocess, "run", self.fake_run), \
                mock.patch.object(review, "wait_health", lambda: True), \
                mock.patch.object(review, "start_monitor", lambda a: 0), \
                mock.patch.object(review, "start_tunnel", lambda kind, exe: (f"https://{kind}.example", None)), \
                mock.patch.dict(os.environ, {"FILM_REVIEW_MEDIA": str(self.tmp / "media")}):
            return run_main(review.main, ["up"] + list(args))

    def test_old_single_kind_file_is_read(self):
        Path(review.TUNNEL_STATE).write_text(json.dumps({"kind": "tailscale", "url": "https://x/", "since": "s"}))
        self.assertEqual(review.tunnel_state(), {"tailscale": {"url": "https://x/", "since": "s"}})
        Path(review.TUNNEL_STATE).write_text("[1, 2]")
        self.assertEqual(review.tunnel_state(), {})

    def test_switching_kind_stops_the_funnel_and_down_stops_everything(self):
        code, out, err = self.up("--tunnel", "tailscale")
        self.assertEqual(code, 0, err)
        self.assertEqual(set(review.tunnel_state()), {"tailscale"})
        self.runs.clear()
        code, out, err = self.up("--tunnel", "ngrok")
        self.assertEqual(code, 0, err)
        self.assertIn(["/usr/bin/tailscale", "funnel", "--https=443", "off"], self.runs, "the funnel is not left on")
        self.assertIn("switching to ngrok", out)
        self.assertEqual(set(review.tunnel_state()), {"ngrok"})
        # a recorded funnel that cannot be turned off: up refuses, nothing new is started
        review.save_tunnel("tailscale", "https://lab.tail1.ts.net/")
        with mock.patch.object(review.subprocess, "run",
                               lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "nope")):
            with mock.patch.object(review.vendor_three, "verify", lambda *a, **k: []), \
                    mock.patch.object(review.shutil, "which", lambda x: "/usr/bin/" + x), \
                    mock.patch.object(review, "ngrok_url", lambda: None), \
                    mock.patch.object(review, "start_tunnel", side_effect=AssertionError("must not start")):
                code, out, err = run_main(review.main, ["up", "--tunnel", "cloudflared"])
        self.assertEqual(code, 1)
        self.assertIn("could not be stopped", err)
        self.assertEqual(set(review.tunnel_state()), {"tailscale"}, "kept: down tries again (ngrok was not ours)")
        # down stops every recorded tunnel (ngrok: ours by pid file, with its tree)
        self.table[200] = self.NGROK
        Path(review.NGROK_PID).write_text("200")
        self.runs.clear()
        with mock.patch.object(review.shutil, "which", lambda x: None if x == "docker" else "/usr/bin/" + x), \
                mock.patch.object(review.subprocess, "run", self.fake_run):
            code, out, err = run_main(review.main, ["down"])
        self.assertIn((200, True), self.killed)
        self.assertIn(["/usr/bin/tailscale", "funnel", "--https=443", "off"], self.runs)
        self.assertFalse(Path(review.TUNNEL_STATE).exists())
        self.assertFalse(Path(review.NGROK_PID).exists())

    def test_no_ngrok_warns_while_a_tunnel_is_public(self):
        review.save_tunnel("tailscale", "https://lab.tail1.ts.net/")
        code, out, err = self.up("--no-ngrok")
        self.assertEqual(code, 0, err)
        self.assertIn("WARNING a public tunnel", out)
        self.assertIn("tailscale", out)
        self.assertEqual(set(review.tunnel_state()), {"tailscale"}, "--no-ngrok does not touch it")
        Path(review.TUNNEL_STATE).unlink()
        code, out, err = self.up("--no-ngrok")
        self.assertIn("no tunnel: local only", out)


class TestPidStates(ReviewState):
    def test_an_unverifiable_pid_is_kept_and_nothing_is_started(self):
        mp = Path(review.MONITOR_PID)
        mp.write_text("100")
        self.table[100] = None                       # alive, but PowerShell timed out
        with mock.patch.object(review.subprocess, "Popen", side_effect=AssertionError("no second monitor")):
            code, out, err = run_main(review.main, ["monitor"])
        self.assertEqual(code, 1)
        self.assertTrue(mp.exists(), "the pid file is kept")
        self.assertIn("cannot verify pid 100", out)
        code, out, err = run_main(review.main, ["monitor", "--stop"])
        self.assertEqual(code, 1)
        self.assertTrue(mp.exists())
        self.assertEqual(self.killed, [])
        self.assertEqual(review.pid_check(str(mp), review.is_monitor, "monitor"), (review.UNKNOWN, 100))
        del self.table[100]                          # dead now: stale
        with mock.patch("sys.stdout"):
            self.assertEqual(review.pid_check(str(mp), review.is_monitor, "monitor"), (review.GONE, 100))
        self.assertFalse(mp.exists())

    def test_stop_watch_kills_the_tree(self):
        wp = Path(review.watch_files("shk")[0])
        wp.write_text("400")
        self.table[400] = self.WATCH
        with mock.patch("sys.stdout"):
            self.assertTrue(review.stop_watch("shk"))
        self.assertEqual(self.killed, [(400, True)], "a running Blender GLB export goes with the watcher")
        self.assertFalse(wp.exists())
        wp.write_text("401")
        self.table[401] = None
        with mock.patch("sys.stdout"):
            self.assertFalse(review.stop_watch("shk"))
        self.assertTrue(wp.exists())

    def test_watch_dir_must_stay_inside(self):
        for d in ("/etc", "C:\\Users", "..", "characters/../../x", "\\\\srv\\share"):
            code, _, err = run_main(review.main, ["watch", "shk", "--dir", d, "--dry-run"])
            self.assertEqual(code, 2, d)
            self.assertIn("refused: --dir", err)
        self.assertEqual(run_main(review.main, ["watch", "shk", "--dir", "characters/a", "--dry-run"])[0], 0)


@unittest.skipIf(os.name == "nt", "process groups: POSIX")
class TestKillTree(unittest.TestCase):
    def test_posix_tree_kills_the_group(self):
        with mock.patch.object(review.os, "getpgid", lambda pid: pid), \
                mock.patch.object(review.os, "killpg") as killpg, mock.patch.object(review.os, "kill") as kill:
            review.kill(4321, tree=True)
            review.kill(4322)
        killpg.assert_called_once_with(4321, 15)
        kill.assert_called_once_with(4322, 15)


# ------------------------------------------------------------------ 5. a malformed _tags.json
class TestMalformedRegistry(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.media = self.tmp / "media"
        self.media.mkdir()
        client._TAG_WARNED.clear()
        self.fake = FakeIngest()
        self.addCleanup(self.fake.stop)

    def test_bad_types_and_patterns_are_skipped(self):
        for doc in ({"groups": ["subject"]}, {"groups": {"subject": ["a"]}}, ["x"], "text", 5,
                    {"groups": {"subject": {"values": ["phuong-hoang"]}}},
                    {"groups": {"subject": {"values": {"a": 1, "b": "B"}, "pattern": 7}}},
                    {"groups": {"episode": {"pattern": "(unclosed"}, "constructor": {"values": {"x": "X"}}}}):
            (self.media / "_tags.json").write_text(json.dumps(doc), encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                reg = client.load_registry(str(self.media))
                rv = client.Review("m1", "T", "model", url=self.fake.url, media=str(self.media),
                                   tags={"episode": "ep01", "subject": "b"})
            self.assertTrue(rv.enabled, doc)
            self.assertNotIn("constructor", reg)
            for g in reg.values():
                self.assertTrue(all(isinstance(k, str) and isinstance(v, str) for k, v in g["values"].items()), doc)
        self.assertIn("bad pattern dropped", err.getvalue())
        self.assertNotIn("pattern", reg["episode"], "the shipped pattern is replaced, then dropped")
        self.assertEqual(self.fake.of("build")[-1]["tags"]["episode"], ["ep01"])

    def test_the_watcher_starts_and_keeps_first_until_saved(self):
        from test_review_watch import watch
        (self.media / "_tags.json").write_text('{"groups": {"subject": {"values": ["x"]}, "e": {"pattern": "["}}}',
                                               encoding="utf-8")
        out = self.tmp / "out" / "shk"
        (out / "characters" / "huy").mkdir(parents=True)
        (out / "characters" / "huy" / "a.png").write_bytes(b"x")
        boom = {"n": 0}

        def make_review(*a):
            boom["n"] += 1
            raise RuntimeError("boom")

        with mock.patch.dict(os.environ, {"FILM_REVIEW_MEDIA": str(self.media), "FILM_REVIEW_URL": self.fake.url}), \
                redirect_stderr(io.StringIO()):
            w = watch.Watcher("shk", out_root=str(out), state_file=str(self.tmp / "s.json"), glb=False,
                              make_review=make_review)
            w.prev = {"characters/huy/a.png": (1, os.stat(out / "characters/huy/a.png").st_mtime)}   # seen once
            with mock.patch.object(watch, "SETTLE", -1e9):
                with self.assertRaises(RuntimeError):
                    w.scan()
        self.assertTrue(w.state.get("first"), "a failed scan does not end the first run")
        w.make_review = lambda bid, title, kind, tags: mock.MagicMock()
        w.scan()
        self.assertNotIn("first", w.state)


# ------------------------------------------------------------------ 6. published files are copies
class TestPublishFile(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.media = self.tmp / "media"
        self.rv = client.Review("p1", "T", "model", url="off", media=str(self.media))
        self.src = self.tmp / "work" / "wip.png"
        self.src.parent.mkdir()

    def test_a_rewrite_in_place_does_not_change_a_published_step(self):
        self.src.write_bytes(b"version one")
        rel = self.rv.publish_file(self.src)
        self.assertEqual(rel, "p1/wip.png")
        dest = self.media / rel
        self.assertFalse(os.path.samefile(dest, self.src), "a copy, not a hard link")
        with open(self.src, "r+b") as f:                       # rewritten in place (same inode)
            f.write(b"VERSION TWO")
        self.assertEqual(dest.read_bytes(), b"version one")
        self.assertEqual(self.rv.publish_file(self.src), "p1/wip-2.png")
        self.assertEqual(self.rv.publish_file(self.src), "p1/wip-2.png", "the same bytes: the same name")
        self.assertEqual(sorted(p.name for p in (self.media / "p1").iterdir()), ["wip-2.png", "wip.png"],
                         "no temp file is left")

    def test_an_old_hard_link_is_not_taken_as_published(self):
        self.src.write_bytes(b"linked")
        (self.media / "p1").mkdir(parents=True, exist_ok=True)
        os.link(self.src, self.media / "p1" / "wip.png")      # what the old client did
        self.assertEqual(self.rv.publish_file(self.src), "p1/wip-2.png")
        self.assertEqual(self.rv.publish_file(self.src, link=True), "p1/wip.png", "an opt-in link may reuse it")
        linked = client.Review("p2", "T", url="off", media=str(self.media), link=True)
        rel = linked.publish_file(self.src)
        self.assertTrue(os.path.samefile(self.media / rel, self.src))

    def test_a_name_taken_meanwhile_goes_to_the_next_one(self):
        self.src.write_bytes(b"mine")
        real_link = os.link
        calls = []

        def racing_link(a, b, **kw):
            calls.append(b)
            if len(calls) == 1:                                # another publisher wins wip.png
                Path(b).write_bytes(b"theirs")
                raise FileExistsError(b)
            return real_link(a, b, **kw)

        with mock.patch.object(client.os, "link", racing_link):
            rel = self.rv.publish_file(self.src)
        self.assertEqual(rel, "p1/wip-2.png")
        self.assertEqual((self.media / "p1" / "wip.png").read_bytes(), b"theirs", "never overwritten")
        self.assertEqual((self.media / "p1" / "wip-2.png").read_bytes(), b"mine")
        self.assertEqual([p.name for p in (self.media / "p1").iterdir() if p.name.endswith(".part")], [])

    def test_without_hard_links_the_final_step_never_clobbers(self):
        self.src.write_bytes(b"mine")
        (self.media / "p1").mkdir(parents=True)
        with mock.patch.object(client.os, "link", side_effect=OSError("no hard links here")):
            self.assertEqual(self.rv.publish_file(self.src), "p1/wip.png")
            other = self.tmp / "work" / "b" / "wip.png"
            other.parent.mkdir()
            other.write_bytes(b"other")
            self.assertEqual(self.rv.publish_file(other), "p1/wip-2.png")
        self.assertEqual((self.media / "p1" / "wip.png").read_bytes(), b"mine")
        if os.name != "nt":
            self.assertEqual(os.stat(self.media / "p1" / "wip.png").st_mode & 0o444, 0o444, "readable")


# ------------------------------------------------------------------ 9. reserved group names
class TestReservedGroups(ServerCase):
    def test_server_and_client_refuse_object_keys(self):
        self.assertEqual(client.RESERVED_GROUPS, server.RESERVED_GROUPS)
        for g in ("constructor", "prototype", "tostring", "valueof"):
            code, body = self.post({"type": "build", "build": "rg", "tags": {g: ["x"]}})
            self.assertEqual(code, 400, (g, body))
        client._TAG_WARNED.clear()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(client.normalize_tags({"constructor": "x", "kind": "model"}), {"kind": ["model"]})
        (self.media / "_tags.json").write_text(json.dumps({"groups": {"constructor": {"label": "x"}}}),
                                               encoding="utf-8")
        self.assertNotIn("constructor", self.get_json("/api/tags")["groups"])


JS_TEST = r"""
import { setRegistry, tagLabel, groupLabel, matches, facets, groupBuilds, parseState, stateQuery, tagPairs,
         validGroup } from '%s';
import { seedText, exportMeta, metaRows } from '%s';
setRegistry({ groups: { kind: { label: 'Loại', color: '#5ef2ff', values: { model: 'Model' } } } });
const b = [{ id: 'a', tags: JSON.parse('{"constructor": ["x"], "kind": ["model"]}') }, { id: 'b', tags: {} }];
const out = {};
for (const q of ['t=constructor:x', 't=__proto__:x,tostring:y,kind:model&g=constructor', 'g=valueof']) {
  const st = parseState(q);
  out[q] = { sel: Object.keys(st.sel), group: st.group, query: stateQuery(st),
             pick: b.filter((x) => matches(x, st.sel)).map((x) => x.id) };
}
out.labels = [tagLabel('constructor', 'x'), groupLabel('constructor'), tagLabel('kind', 'constructor')];
out.byCtor = groupBuilds(b, 'constructor').map(([v, xs]) => [v, xs.map((x) => x.id)]);
out.pairs = tagPairs({ toString: 'nope', kind: ['model'] });
out.facets = facets([{ tags: { kind: 'model', engine: ['blender'] } }]).map(([g]) => g);
out.valid = ['constructor', 'kind', '__proto__'].map(validGroup);
const big = { seed: 18446744073709551615, seed_str: '18446744073709551615', model: 'm' };
out.seed = [seedText(big), seedText({ seed: 42 }), seedText({}), seedText({ seed: 1, seed_str: '1e9' })];
out.meta = exportMeta(big);
out.rows = metaRows({ meta: big }).find(([k]) => k === 'Seed');
console.log(JSON.stringify(out));
"""


@unittest.skipIf(NODE is None, "node is missing")
class TestTagsJsReserved(unittest.TestCase):
    def test_object_keys_never_break_the_dashboard(self):
        src = JS_TEST % ((WEB / "tags.js").resolve().as_uri(), (WEB / "gallery.js").resolve().as_uri())
        r = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["t=constructor:x"], {"sel": [], "group": "", "query": "", "pick": ["a", "b"]})
        q = out["t=__proto__:x,tostring:y,kind:model&g=constructor"]
        self.assertEqual((q["sel"], q["group"], q["pick"]), (["kind"], "", ["a"]))
        self.assertEqual(out["g=valueof"]["group"], "")
        self.assertEqual(out["labels"], ["X", "constructor", "Constructor"])
        self.assertEqual(out["byCtor"], [["x", ["a"]], [None, ["b"]]])
        self.assertEqual(out["pairs"], [["kind", "model"]])
        self.assertEqual(out["facets"], ["engine"], "a value that is not a list is skipped")
        self.assertEqual(out["valid"], [False, True, False])
        self.assertEqual(out["seed"], ["18446744073709551615", "42", None, "1"])
        self.assertEqual(out["meta"], {"seed": "18446744073709551615", "model": "m"})
        self.assertEqual(out["rows"], ["Seed", "18446744073709551615"])


# ------------------------------------------------------------------ 10. seeds above 2**53
class TestBigSeeds(ServerCase):
    def test_exact_seed_from_client_to_api(self):
        fake = FakeIngest()
        self.addCleanup(fake.stop)
        big = 2 ** 64 - 1
        client._TAG_WARNED.clear()
        with redirect_stderr(io.StringIO()) as err:
            rv = client.Review("s1", "T", "image", url=fake.url, media=str(self.tmp / "m"))
            rv.step("a", meta={"seed": big, "sampler_steps": 30.0, "width": "1024"})
            rv.step("b", meta={"seed": 2 ** 64, "items": 2.5})
        steps = fake.of("step")
        self.assertEqual((steps[0]["seed"], steps[0]["sampler_steps"], steps[0]["width"]), (big, 30, 1024))
        self.assertNotIn("seed", steps[1])
        self.assertNotIn("items", steps[1])
        self.assertIn("out of range", err.getvalue())
        self.ok({"type": "step", "build": "s2", "label": "x", "seed": big})
        self.ok({"type": "step", "build": "s2", "label": "y", "seed": 7})
        got = self.get_json("/api/builds/s2/steps")["steps"]
        self.assertEqual([(s["meta"]["seed"], s["meta"]["seed_str"]) for s in got],
                         [(big, str(big)), (7, "7")])
        code, _ = self.post({"type": "step", "build": "s2", "label": "z", "seed": 2 ** 64})
        self.assertEqual(code, 400, "the server keeps 0..2**64-1")


if __name__ == "__main__":
    unittest.main()
