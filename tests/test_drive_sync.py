"""tools/drive_sync.py: snapshot / plan / record round trip on a temp project with fake Drive IDs (no network)."""
import json, os, re, subprocess, sys, unittest, zipfile

from helpers import TmpDirCase, load, run_main

ds = load("drive_sync.py", "film_drive_sync")

PROJECT_MD = """---
project: demo
title: Demo
style: thuy-mac
drive:
  name: Demo
  lab_root: LAB-ROOT
  root: ROOT-ID
  folders:
    00_QuanLy: F-QL
    01_TaiLieuGoc: F-TLG
    02_KinhThu: F-KT
    02_KinhThu/NhanVat: F-NV
    02_KinhThu/NhanVat/bac-thi: F-NV-BT
    02_KinhThu/BoiCanh: <id>
    03_KichBan: F-KB
    03_KichBan/ep01-bac-thi: F-KB-E1
    03_KichBan/ep01-bac-thi/prompts: F-KB-E1-P
    04_SanXuat: F-SX
    04_SanXuat/ep01-bac-thi: F-SX-E1
    05_ThanhPham: F-TP
    99_LuuTru: F-LT
  files:
    00_QuanLy/README_CauTruc: DOC-ID
    00_QuanLy/TienDo_SanXuat: SHEET-ID
---

# Demo
"""

FILES = {
    "PROJECT.md": PROJECT_MD,
    "SERIES.md": "# series\n",
    "TienDo_SanXuat.csv": "tap,khau\nep01,2\n",
    "characters/bac-thi/CHARACTER.md": "# Bac thi\n",
    "ep01-bac-thi/EPISODE.md": "---\nstage: 2\n---\n",
    "ep01-bac-thi/script.md": "[00:00] mo dau\n",
    "ep01-bac-thi/prompts/s01_L1.txt": "nui\n",
    "sources/DanhMuc.csv": "file,thu_muc,mo_ta,nguon,ngay_them\n",
    "sources/NguyenVan/shk_nam-son_01_co-son.txt": "nguyen van\n",
}


class DriveSyncCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.pd = self.tmp / "projects" / "demo"
        self.out = self.tmp / "out" / "demo"
        for rel, text in FILES.items():
            self.write(rel, text)
        (self.out / "ep01" / "plates").mkdir(parents=True)
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n")
        (self.out / "ep01" / "plates" / "ep01_s01_L1_nui_v01.png").write_bytes(b"png")
        self.cwd = os.getcwd()
        os.chdir(self.tmp)          # like the repo root: paths as `find projects/demo` prints them

    def tearDown(self):
        os.chdir(self.cwd)
        super().tearDown()

    def write(self, rel, text, append=False):
        p = self.pd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def run_tool(self, *argv):
        return run_main(ds.main, list(argv))

    def plan(self, *extra):
        code, out, err = self.run_tool("plan", "projects/demo", "--json", "--now", "20261110-1530", *extra)
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def snapshot(self, *extra):
        code, out, err = self.run_tool("snapshot", "projects/demo", *extra)
        self.assertEqual(code, 0, err)
        return out

    def action(self, plan, local):
        hits = [a for a in plan["actions"] if a["local"] == local]
        self.assertEqual(len(hits), 1, f"{local} not planned once: {[a['local'] for a in plan['actions']]}")
        return hits[0]


class TestSnapshot(DriveSyncCase):
    def test_sha256sum_format_and_pulled_at(self):
        self.write(".hidden", "x")
        self.write("__pycache__/x.pyc", "x")
        self.snapshot()
        lines = (self.pd / ".pulled.sha256").read_text().splitlines()
        self.assertEqual(len(lines), len(FILES))
        for line in lines:
            self.assertRegex(line, r"^[0-9a-f]{64}  projects/demo/[^.]")
        self.assertFalse(any("__pycache__" in l or ".hidden" in l for l in lines))
        self.assertRegex((self.pd / ".pulled.at").read_text(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\n$")

    def test_include_out_keys(self):
        self.snapshot("--include-out", "out/demo")
        text = (self.pd / ".pulled.sha256").read_text()
        self.assertIn("  out/demo/ep01/ledger.csv\n", text)

    def test_reads_shell_snapshot(self):
        """A snapshot made by the §11.6 shell command (relative paths from the repo root) is understood."""
        snap = ds.read_snapshot(str(self.pd))
        self.assertIsNone(snap)
        lines = [f"{ds.sha256(self.pd / r)}  ./projects/demo/{r}" for r in sorted(FILES)]
        (self.pd / ".pulled.sha256").write_text("\n".join(lines) + "\n")
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["counts"]["unchanged"], len(FILES))

    def test_bad_snapshot_line(self):
        (self.pd / ".pulled.sha256").write_text("not a hash line\n")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("not a sha256sum line", err)


class TestPlan(DriveSyncCase):
    def test_nothing_after_snapshot(self):
        self.snapshot()
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing to push.", out)

    def test_changed_vs_new(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)
        self.write("ep01-bac-thi/prompts/s02_L4.txt", "bac thi\n")
        code, plan = self.plan()
        self.assertEqual(code, 0)
        self.assertEqual(plan["counts"]["changed"], 1)
        self.assertEqual(plan["counts"]["new"], 1)

        ch = self.action(plan, "projects/demo/ep01-bac-thi/script.md")
        self.assertEqual(ch["status"], "changed")
        self.assertEqual(ch["folder"], {"path": "03_KichBan/ep01-bac-thi", "id": "F-KB-E1", "missing": []})
        cf = ch["create_file"]
        self.assertEqual((cf["title"], cf["parentId"], cf["contentMimeType"]), ("script.md", "F-KB-E1", "text/markdown"))
        self.assertTrue(cf["disableConversionToGoogleType"])
        self.assertEqual(cf["base64Content"], f"sha256:{ds.sha256(script)}:{script.resolve()}")
        ar = ch["archive"]
        self.assertEqual(ar["search_files"], "parentId = 'F-KB-E1' and title = 'script.md' and trashed = false")
        self.assertEqual(ar["parentId"], "F-LT")
        self.assertEqual(ar["title"], "03_KichBan__ep01-bac-thi__script_20261110-1530.md")
        self.assertNotIn("fileId", ar)            # old versions are found at archive time, never remembered
        self.assertEqual(ar["when"], "always")
        self.assertNotIn("condition", ar)

        new = self.action(plan, "projects/demo/ep01-bac-thi/prompts/s02_L4.txt")
        self.assertEqual(new["status"], "new")
        self.assertEqual(new["archive"]["search_files"],
                         "parentId = 'F-KB-E1-P' and title = 's02_L4.txt' and trashed = false")
        self.assertEqual(new["archive"]["title"], "03_KichBan__ep01-bac-thi__prompts__s02_L4_20261110-1530.txt")
        self.assertEqual(new["archive"]["when"], "if_exists")
        self.assertEqual(new["archive"]["condition"], ds.IF_EXISTS)
        self.assertEqual(new["folder"]["id"], "F-KB-E1-P")
        self.assertEqual(new["create_file"]["contentMimeType"], "text/plain")

    def test_mapping_table(self):
        cases = {
            "PROJECT.md": "00_QuanLy", "SERIES.md": "02_KinhThu", "pronunciation.csv": "02_KinhThu",
            "characters/bac-thi/CHARACTER.md": "02_KinhThu/NhanVat/bac-thi",
            "locations/co-son/LOCATION.md": "02_KinhThu/BoiCanh/co-son",
            "style/notes.md": "02_KinhThu/PhongCach",
            "ep01-bac-thi/review/qc-v1.md": "03_KichBan/ep01-bac-thi/review",
            "sources/DanhMuc.csv": "01_TaiLieuGoc",
            "sources/SachThamKhao/SHK_Quach/a.txt": "01_TaiLieuGoc/SachThamKhao/SHK_Quach",
            "notes.txt": None, "random/x.md": None, "ep01-bac-thi/pronunciation.csv": "03_KichBan/ep01-bac-thi",
            "style/pronunciation.csv": "02_KinhThu/PhongCach",
        }
        for rel, folder in cases.items():
            self.assertEqual(ds.map_project(rel), folder, rel)

    def test_project_md_last(self):
        self.write("PROJECT.md", "\n<!-- 2026-11-10 them thu muc -->\n", append=True)
        self.write("SERIES.md", "x\n", append=True)
        code, plan = self.plan()
        self.assertEqual(plan["actions"][-1]["local"], "projects/demo/PROJECT.md")
        self.assertTrue(plan["warnings"][0].startswith("no .pulled.sha256"))

    def test_missing_folder(self):
        self.snapshot()
        self.write("locations/co-son/LOCATION.md", "# Co son\n")      # 02_KinhThu/BoiCanh is a <id> placeholder
        self.write("ep02-cuu-vi/EPISODE.md", "x\n")
        code, plan = self.plan()
        self.assertEqual(code, 1)
        loc = self.action(plan, "projects/demo/locations/co-son/LOCATION.md")
        self.assertIsNone(loc["folder"]["id"])
        self.assertIsNone(loc["create_file"]["parentId"])
        self.assertEqual([c["path"] for c in loc["folder"]["missing"]],
                         ["02_KinhThu/BoiCanh", "02_KinhThu/BoiCanh/co-son"])
        self.assertEqual(loc["folder"]["missing"][0]["parent_id"], "F-KT")
        self.assertIsNone(loc["folder"]["missing"][1]["parent_id"])
        self.assertEqual([c["path"] for c in plan["create_folders"]],
                         ["02_KinhThu/BoiCanh", "03_KichBan/ep02-cuu-vi", "02_KinhThu/BoiCanh/co-son"])
        _, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("02_KinhThu/BoiCanh/co-son = MISSING – create folder 02_KinhThu/BoiCanh under F-KT first", out)
        self.assertIn("03_KichBan/ep02-cuu-vi = MISSING – create folder 03_KichBan/ep02-cuu-vi under F-KB first", out)

    def test_unmapped_file_blocks(self):
        self.snapshot()
        self.write("notes.txt", "x")
        code, plan = self.plan()
        self.assertEqual(code, 1)
        self.assertEqual([u["local"] for u in plan["unmapped"]], ["projects/demo/notes.txt"])

    def test_pronunciation_csv(self):
        """Project-level Hán Việt map (tools/tts --pron) goes next to SERIES.md, not UNMAPPED."""
        self.snapshot()
        pron = self.write("pronunciation.csv", "term,doc\nChiêu Diêu,Chiêu Diêu\n")
        code, plan = self.plan()
        self.assertEqual(code, 0)
        self.assertEqual(plan["unmapped"], [])
        x = self.action(plan, "projects/demo/pronunciation.csv")
        self.assertEqual(x["folder"], {"path": "02_KinhThu", "id": "F-KT", "missing": []})
        self.assertEqual((x["create_file"]["title"], x["create_file"]["contentMimeType"]),
                         ("pronunciation.csv", "text/csv"))
        self.assertTrue(x["create_file"]["disableConversionToGoogleType"])
        self.assertEqual(x["create_file"]["base64Content"], f"sha256:{ds.sha256(pron)}:{pron.resolve()}")
        self.assertEqual(x["archive"]["title"], "02_KinhThu__pronunciation_20261110-1530.csv")

    def test_template_pronunciation_csv(self):
        tpl = os.path.join(os.path.dirname(ds.__file__), "..", "templates", "project", "pronunciation.csv")
        with open(tpl, encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["term,doc"])

    def test_new_file_archive_if_exists(self):
        """No snapshot line (first push after a manual upload, lost snapshot): still search and archive duplicates."""
        os.remove(self.pd / "SERIES.md")
        self.snapshot()
        self.write("SERIES.md", "# series\n")
        code, plan = self.plan()
        x = self.action(plan, "projects/demo/SERIES.md")
        self.assertEqual(x["status"], "new")
        ar = x["archive"]
        self.assertEqual(ar["search_files"], "parentId = 'F-KT' and title = 'SERIES.md' and trashed = false")
        self.assertEqual((ar["parentId"], ar["title"], ar["when"]),
                         ("F-LT", "02_KinhThu__SERIES_20261110-1530.md", "if_exists"))
        _, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        block = out.split("NEW     projects/demo/SERIES.md", 1)[1]
        self.assertIn("archive      if a file with this title already exists in the folder (first push), archive it:",
                      block)
        self.assertIn("search_files parentId = 'F-KT' and title = 'SERIES.md' and trashed = false", block)
        self.assertIn("title=02_KinhThu__SERIES_20261110-1530.md", block)
        self.assertIn("Before uploading a NEW file", out)

    def test_no_snapshot_every_file_has_archive(self):
        code, plan = self.plan()
        self.assertTrue(plan["actions"])
        for x in plan["actions"]:
            self.assertEqual(x["archive"]["when"], "if_exists", x["local"])

    def test_sheet_is_apart(self):
        self.snapshot()
        self.write("TienDo_SanXuat.csv", "ep02,0\n", append=True)
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        sh = plan["sheet"]
        self.assertEqual(sh["create_file"]["title"], "TienDo_SanXuat")
        self.assertFalse(sh["create_file"]["disableConversionToGoogleType"])
        self.assertEqual(sh["archive"]["title"], "00_QuanLy__TienDo_SanXuat_20261110-1530")
        self.assertEqual(sh["archive"]["drive_files_id"], "SHEET-ID")

    def test_sources_are_read_only_except_catalog(self):
        self.snapshot()
        self.write("sources/NguyenVan/shk_nam-son_01_co-son.txt", "sua\n", append=True)
        self.write("sources/DanhMuc.csv", "a.txt,NguyenVan,x,y,2026-11-10\n", append=True)
        code, plan = self.plan()
        self.assertEqual([a["local"] for a in plan["actions"]], ["projects/demo/sources/DanhMuc.csv"])
        self.assertEqual(plan["actions"][0]["folder"]["id"], "F-TLG")
        self.assertTrue(any("never edited" in w for w in plan["warnings"]))

    def test_deleted_locally(self):
        self.snapshot()
        os.remove(self.pd / "SERIES.md")
        code, plan = self.plan()
        self.assertEqual(plan["deleted"], ["projects/demo/SERIES.md"])

    def test_include_out(self):
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n1,image\n")
        (self.out / "ep01" / "bundles").mkdir()
        (self.out / "ep01" / "bundles" / "ep01_s01_20261109.zip").write_bytes(b"zip")
        (self.out / "ep01" / "renders").mkdir()
        (self.out / "ep01" / "renders" / "ep01_draft_v01.mp4").write_bytes(b"mp4")
        (self.out / "ep01" / "renders" / "ep01_final_v01.mp4").write_bytes(b"mp4")
        (self.out / "ep01" / "plates" / "ep01_s02_L1_nui_v01.png").write_bytes(b"png")
        code, plan = self.plan("--include-out", "out/demo", "--date", "2026-11-10")
        led = self.action(plan, "out/demo/ep01/ledger.csv")
        self.assertEqual((led["status"], led["folder"]["id"]), ("changed", "F-SX-E1"))
        self.assertEqual(led["archive"]["title"], "04_SanXuat__ep01-bac-thi__ledger_20261110-1530.csv")
        self.assertEqual(self.action(plan, "out/demo/ep01/bundles/ep01_s01_20261109.zip")["folder"]["path"],
                         "04_SanXuat/ep01-bac-thi/2026-11-09")
        draft = self.action(plan, "out/demo/ep01/renders/ep01_draft_v01.mp4")
        self.assertEqual(draft["folder"]["path"], "04_SanXuat/ep01-bac-thi/2026-11-10")
        self.assertEqual(draft["create_file"]["contentMimeType"], "video/mp4")
        self.assertEqual(self.action(plan, "out/demo/ep01/renders/ep01_final_v01.mp4")["folder"],
                         {"path": "05_ThanhPham/ep01-bac-thi", "id": None,
                          "missing": [{"path": "05_ThanhPham/ep01-bac-thi", "name": "ep01-bac-thi",
                                       "parent_path": "05_ThanhPham", "parent_id": "F-TP"}]})
        self.assertEqual(plan["skipped_media"], 2)      # plates travel inside bundles
        self.assertFalse(any("plates" in a["local"] for a in plan["actions"]))

    def test_text_output(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        self.assertEqual(code, 0)
        self.assertIn("CHANGED projects/demo/ep01-bac-thi/script.md", out)
        self.assertIn("search_files parentId = 'F-KB-E1' and title = 'script.md' and trashed = false", out)
        self.assertIn("title=03_KichBan__ep01-bac-thi__script_20261110-1530.md", out)
        self.assertIn("archive      search_files parentId = 'F-KB-E1'", out)    # CHANGED: unconditional
        self.assertNotIn("first push", out)
        self.assertNotIn("Before uploading a NEW file", out)
        self.assertRegex(out, r"base64Content=sha256:[0-9a-f]{64}:/\S+/projects/demo/ep01-bac-thi/script\.md")
        self.assertIn("record projects/demo --uploaded projects/demo/ep01-bac-thi/script.md --id <new ID>", out)

    def test_bad_now(self):
        code, _, err = self.run_tool("plan", "projects/demo", "--now", "2026-11-10")
        self.assertEqual(code, 2)
        self.assertIn("YYYYMMDD-HHMM", err)


class TestArchiveName(unittest.TestCase):
    def test_format(self):
        self.assertEqual(ds.archive_name("03_KichBan/ep01-bac-thi", "script.md", "20261110-1530"),
                         "03_KichBan__ep01-bac-thi__script_20261110-1530.md")
        self.assertEqual(ds.archive_name("03_KichBan/ep01-bac-thi/prompts", "s01_L1.txt", "20260101-0000"),
                         "03_KichBan__ep01-bac-thi__prompts__s01_L1_20260101-0000.txt")
        self.assertEqual(ds.archive_name("00_QuanLy", "TienDo_SanXuat", "20261110-1530"),
                         "00_QuanLy__TienDo_SanXuat_20261110-1530")


class TestRecord(DriveSyncCase):
    def test_round_trip(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        self.write("SERIES.md", "y\n", append=True)
        code, plan = self.plan()
        self.assertEqual(plan["counts"]["changed"], 2)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects/demo/ep01-bac-thi/script.md",
                                       "--id", "NEW-SCRIPT")
        self.assertEqual(code, 0, err)
        code, plan = self.plan()
        self.assertEqual([a["local"] for a in plan["actions"]], ["projects/demo/SERIES.md"])   # declined upload stays
        self.assertEqual(plan["pushed_ids"], ["NEW-SCRIPT"])
        log = (self.pd / ".pushed.log").read_text().splitlines()
        self.assertRegex(log[0], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z projects/demo/ep01-bac-thi/script\.md NEW-SCRIPT$")
        # only that line of the snapshot changed
        self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "NEW-SERIES")
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 0)
        self.assertIn("Nothing to push.", out)
        self.assertEqual(len((self.pd / ".pushed.log").read_text().splitlines()), 2)

    def test_record_media(self):
        self.snapshot()
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n1,image\n")
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/ledger.csv", "--id", "L1")
        self.assertEqual(code, 0, err)
        self.assertIn("  out/demo/ep01/ledger.csv\n", (self.pd / ".pulled.sha256").read_text())
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["actions"], [])

    def test_record_errors(self):
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--uploaded", "PROJECT.md",
                                     "--id", "A")
        self.assertEqual(code, 2)
        self.assertIn("one --id per --uploaded", err)
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "nope.md", "--id", "A")
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "<new ID>")
        self.assertEqual(code, 2)


class TestSnapshotGuard(DriveSyncCase):
    """A second snapshot must not mark unpushed local edits as pulled."""

    def state(self):
        return (self.pd / ".pulled.sha256").read_bytes(), (self.pd / ".pulled.at").read_bytes()

    def test_second_snapshot_refuses_pending_change(self):
        self.snapshot()
        (self.pd / ".pulled.at").write_text("2026-11-01T00:00:00Z\n")
        before = self.state()
        self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)     # local edit, not pushed
        self.write("ep01-bac-thi/research.md", "# keo sau\n")                    # the later pull
        code, out, err = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 1)
        text = out + err
        self.assertIn("2 local change(s) not yet pushed would be marked as pulled", text)
        self.assertIn("drive_sync.py pulled projects/demo <path>...", text)
        self.assertIn("projects/demo/ep01-bac-thi/script.md", text)
        self.assertIn("projects/demo/ep01-bac-thi/research.md", text)
        self.assertEqual(self.state(), before)
        code, plan = self.plan()
        self.assertEqual((plan["counts"]["changed"], plan["counts"]["new"]), (1, 1))

    def test_refusal_lists_at_most_20(self):
        self.snapshot()
        for i in range(25):
            self.write(f"ep01-bac-thi/prompts/s{i:02d}_L9.txt", "x\n")
        code, out, err = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 1)
        self.assertIn("25 local change(s)", out + err)
        self.assertEqual(len(re.findall(r"_L9\.txt", out + err)), 20)

    def test_force_overrides(self):
        self.snapshot()
        (self.pd / ".pulled.at").write_text("2026-11-01T00:00:00Z\n")
        self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)
        code, out, err = self.run_tool("snapshot", "projects/demo", "--force")
        self.assertEqual(code, 0, err)
        self.assertNotEqual((self.pd / ".pulled.at").read_text(), "2026-11-01T00:00:00Z\n")
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_first_snapshot_and_clean_resnapshot(self):
        out = self.snapshot()
        self.assertRegex(out, rf"^snapshot  projects/demo/\.pulled\.sha256: {len(FILES)} file\(s\) · pulled at ")
        first = (self.pd / ".pulled.sha256").read_bytes()
        self.snapshot()                                   # nothing pending: allowed, same content
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), first)
        os.remove(self.pd / "SERIES.md")                  # a deletion is not an unpushed change
        self.snapshot()

    def test_temp_files_and_ledger_copies_do_not_block(self):
        self.snapshot("--include-out", "out/demo")
        self.write("ep01-bac-thi/script.md.b64", "eA==\n")
        (self.out / "ep01" / "ledger.drive-1.csv").write_text("ts,kind\n")
        self.snapshot("--include-out", "out/demo")
        text = (self.pd / ".pulled.sha256").read_text()
        self.assertNotIn(".b64", text)
        self.assertNotIn("ledger.drive-1.csv", text)

    def test_pulled_updates_one_line(self):
        self.snapshot()
        at = (self.pd / ".pulled.at").read_bytes()
        self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)
        research = self.write("ep01-bac-thi/research.md", "# keo sau\n")
        code, out, err = self.run_tool("pulled", "projects/demo", "projects/demo/ep01-bac-thi/research.md")
        self.assertEqual(code, 0, err)
        self.assertIn("pulled    projects/demo/ep01-bac-thi/research.md", out)
        self.assertIn(f"{ds.sha256(research)}  projects/demo/ep01-bac-thi/research.md\n",
                      (self.pd / ".pulled.sha256").read_text())
        self.assertEqual((self.pd / ".pulled.at").read_bytes(), at)
        self.assertFalse((self.pd / ".pushed.log").exists())
        code, plan = self.plan()
        self.assertEqual([a["local"] for a in plan["actions"]], ["projects/demo/ep01-bac-thi/script.md"])
        self.assertEqual(plan["actions"][0]["status"], "changed")
        # the remaining pending change still blocks a full snapshot
        code, _, _ = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 1)

    def test_pulled_several_and_media(self):
        self.snapshot()
        self.write("ep01-bac-thi/research.md", "# keo sau\n")
        code, out, err = self.run_tool("pulled", "projects/demo", "ep01-bac-thi/research.md",
                                       "out/demo/ep01/ledger.csv")
        self.assertEqual(code, 0, err)
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["actions"], [])

    def test_pulled_outside_project(self):
        self.snapshot()
        before = (self.pd / ".pulled.sha256").read_bytes()
        other = self.tmp / "projects" / "other" / "SERIES.md"
        other.parent.mkdir(parents=True)
        other.write_text("x\n")
        for path in ("/etc/hostname", "projects/other/SERIES.md"):
            if not os.path.exists(path):
                continue
            code, _, err = self.run_tool("pulled", "projects/demo", path)
            self.assertEqual(code, 2, path)
            self.assertIn("projects/demo/", err)
        code, _, err = self.run_tool("pulled", "projects/demo", "nope.md")
        self.assertEqual(code, 2)
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), before)

    def test_pulled_needs_a_snapshot(self):
        code, _, err = self.run_tool("pulled", "projects/demo", "SERIES.md")
        self.assertEqual(code, 2)
        self.assertIn("snapshot", err)
        self.assertFalse((self.pd / ".pulled.sha256").exists())


class TestLockedState(DriveSyncCase):
    def test_parallel_record_keeps_every_line(self):
        tool = os.path.join(os.path.dirname(os.path.abspath(ds.__file__)), "drive_sync.py")
        names = [f"ep01-bac-thi/prompts/s{i:02d}_L1.txt" for i in range(10, 22)]
        for n in names:
            self.write(n, "v1\n")
        self.snapshot()
        total = len((self.pd / ".pulled.sha256").read_text().splitlines())
        for rnd in range(3):
            for n in names:
                self.write(n, f"round {rnd}\n", append=True)
            procs = [subprocess.Popen([sys.executable, tool, "record", "projects/demo", "--uploaded",
                                       f"projects/demo/{n}", "--id", f"ID-{rnd}-{i}"],
                                      cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for i, n in enumerate(names)]
            for pr in procs:
                _, err = pr.communicate(timeout=60)
                self.assertEqual(pr.returncode, 0, err.decode())
            self.assertEqual(len((self.pd / ".pulled.sha256").read_text().splitlines()), total, f"round {rnd}")
            self.assertEqual(len((self.pd / ".pushed.log").read_text().splitlines()), 12 * (rnd + 1))
            code, out, _ = self.run_tool("plan", "projects/demo")
            self.assertEqual(code, 0, out)
            self.assertIn("Nothing to push.", out)
        self.assertEqual([f for f in os.listdir(self.pd) if f.endswith(".tmp")], [])

    def test_lock_file_is_never_planned(self):
        self.snapshot()
        self.assertTrue((self.pd / ".drive_sync.lock").exists())
        code, plan = self.plan()
        self.assertEqual((plan["actions"], plan["unmapped"]), ([], []))
        self.assertNotIn(".drive_sync.lock", (self.pd / ".pulled.sha256").read_text())


class TestRecordSafety(DriveSyncCase):
    def test_sha256_keeps_later_edit_changed(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "v2\n", append=True)
        code, plan = self.plan()
        planned = self.action(plan, "projects/demo/ep01-bac-thi/script.md")["sha256"]
        self.write("ep01-bac-thi/script.md", "v3\n", append=True)           # edit after create_file
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects/demo/ep01-bac-thi/script.md",
                                       "--sha256", planned, "--id", "NEW1")
        self.assertEqual(code, 0, err)
        self.assertIn("WARN projects/demo/ep01-bac-thi/script.md changed after the upload: still to push", out + err)
        self.assertIn(f"{planned}  projects/demo/ep01-bac-thi/script.md\n", (self.pd / ".pulled.sha256").read_text())
        code, plan = self.plan()
        x = self.action(plan, "projects/demo/ep01-bac-thi/script.md")
        self.assertEqual((x["status"], x["sha256"]), ("changed", ds.sha256(script)))
        self.assertEqual(plan["pushed_ids"], ["NEW1"])

    def test_sha256_matching_file(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "v2\n", append=True)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects/demo/ep01-bac-thi/script.md",
                                       "--sha256", ds.sha256(script).upper(), "--id", "NEW1")
        self.assertEqual(code, 0, err)
        self.assertNotIn("WARN", out + err)
        self.assertNotIn("--sha256", out + err)
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_without_sha256_reminder(self):
        self.snapshot()
        self.write("SERIES.md", "y\n", append=True)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "S1")
        self.assertEqual(code, 0, err)
        self.assertEqual(len([l for l in (out + err).splitlines() if "--sha256" in l]), 1)
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_bad_sha256(self):
        self.snapshot()
        before = (self.pd / ".pulled.sha256").read_bytes()
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--sha256", "abc123",
                                     "--id", "S1")
        self.assertEqual(code, 2)
        self.assertIn("64 hex", err)
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--uploaded", "PROJECT.md",
                                     "--sha256", "a" * 64, "--id", "S1", "--id", "S2")
        self.assertEqual(code, 2)
        self.assertIn("one --sha256 per --uploaded", err)
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), before)
        self.assertFalse((self.pd / ".pushed.log").exists())

    def test_foreign_paths_refused(self):
        self.snapshot()
        before = (self.pd / ".pulled.sha256").read_bytes()
        other = self.tmp / "projects" / "other" / "SERIES.md"
        other.parent.mkdir(parents=True)
        other.write_text("x\n")
        (self.tmp / "out" / "other").mkdir()
        (self.tmp / "out" / "other" / "ledger.csv").write_text("ts,kind\n")
        for path in ("/etc/hostname", "projects/other/SERIES.md", "out/other/ledger.csv"):
            if not os.path.exists(path):
                continue
            code, _, err = self.run_tool("record", "projects/demo", "--uploaded", path, "--id", "X")
            self.assertEqual(code, 2, path)
            self.assertIn("projects/demo/", err)
        # one bad path refuses the whole call
        code, _, _ = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "A",
                                   "--uploaded", "projects/other/SERIES.md", "--id", "B")
        self.assertEqual(code, 2)
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), before)
        self.assertFalse((self.pd / ".pushed.log").exists())

    def test_backslash_path(self):
        self.snapshot()
        self.write("SERIES.md", "y\n", append=True)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects\\demo\\SERIES.md",
                                       "--id", "S1")
        self.assertEqual(code, 0, err)
        self.assertRegex((self.pd / ".pushed.log").read_text(), r" projects/demo/SERIES\.md S1\n$")
        self.assertNotIn("\\", (self.pd / ".pulled.sha256").read_text())
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_backslash_snapshot_keys(self):
        lines = [f"{ds.sha256(self.pd / r)}  " + f"projects/demo/{r}".replace("/", "\\") for r in sorted(FILES)]
        (self.pd / ".pulled.sha256").write_text("\n".join(lines) + "\n")
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["counts"]["unchanged"], len(FILES))


class TestLedgerPlan(DriveSyncCase):
    def setUp(self):
        super().setUp()
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n1,image\n")

    def test_ledger_action(self):
        (self.out / "ep01" / "renders").mkdir()
        (self.out / "ep01" / "renders" / "ep01_draft_v01.mp4").write_bytes(b"mp4")
        code, plan = self.plan("--include-out", "out/demo")
        led = self.action(plan, "out/demo/ep01/ledger.csv")
        self.assertEqual(led["notes"], ["ledger: push after every stage that generated; no approval gate"])
        self.assertEqual(led["pre"], {"ledger_merge": {
            "into": "out/demo/ep01/ledger.csv", "copies_glob": "out/demo/ep01/ledger.drive-*.csv",
            "search_files": "parentId = 'F-SX-E1' and title = 'ledger.csv' and trashed = false",
            "excludeContentSnippets": True}})
        draft = self.action(plan, "out/demo/ep01/renders/ep01_draft_v01.mp4")
        self.assertEqual(draft["notes"], ["media: push only after the user approved it (§9)"])
        self.assertNotIn("pre", draft)

    def test_text_merge_before_upload(self):
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo", "--now", "20261110-1530")
        self.assertEqual(code, 0)
        block = out.split("CHANGED out/demo/ep01/ledger.csv", 1)[1]
        self.assertLess(block.index("ledger-merge"), block.index("create_file"))
        self.assertIn("1) search_files parentId = 'F-SX-E1' and title = 'ledger.csv' and trashed = false"
                      "  excludeContentSnippets=true", block)
        self.assertIn("2) download EVERY result to out/demo/ep01/ledger.drive-<n>.csv", block)
        self.assertIn("3) python3 tools/ark.py ledger-merge out/demo/ep01/ledger.csv out/demo/ep01/ledger.drive-*.csv "
                      "-o out/demo/ep01/ledger.csv", block)
        self.assertIn("4) run plan again", block)
        self.assertIn("note         ledger: push after every stage that generated; no approval gate", block)
        self.assertNotIn("only after the user approved", block)

    def test_drive_copies_never_planned(self):
        (self.out / "ep01" / "ledger.drive-1.csv").write_text("ts,kind\n9,image\n")
        (self.out / "ledger.drive-2.csv").write_text("ts,kind\n")
        self.write("ep01-bac-thi/ledger.drive-1.csv", "ts,kind\n")
        self.write("ledger.drive-3.csv", "ts,kind\n")
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertEqual([a["local"] for a in plan["actions"]], ["out/demo/ep01/ledger.csv"])
        self.assertEqual(plan["unmapped"], [])
        self.assertEqual(plan["skipped_media"], 1)          # the plate only
        self.assertEqual(plan["ignored_temp"], [])


class TestPlanHygiene(DriveSyncCase):
    def test_search_lines_exclude_snippets(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        self.write("ep01-bac-thi/prompts/s02_L4.txt", "bac thi\n")
        self.write("TienDo_SanXuat.csv", "ep02,0\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        searches = [l for l in out.splitlines() if re.search(r"\bsearch_files parentId", l)]
        self.assertEqual(len(searches), 3)
        for line in searches:
            self.assertTrue(line.endswith("and trashed = false  excludeContentSnippets=true"), line)
        code, plan = self.plan()
        for x in plan["actions"] + [plan["sheet"]]:
            self.assertIs(x["archive"]["excludeContentSnippets"], True)

    def test_apostrophe_and_backslash_title(self):
        self.assertEqual(ds.search_query("F1", "02_KinhThu", "quach-phac's_note.txt"),
                         "parentId = 'F1' and title = 'quach-phac\\'s_note.txt' and trashed = false")
        self.assertEqual(ds.search_query("F1", "02_KinhThu", "a\\b.txt"),
                         "parentId = 'F1' and title = 'a\\\\b.txt' and trashed = false")
        self.snapshot()
        self.write("ep01-bac-thi/quach-phac's_note.txt", "x\n")
        code, plan = self.plan()
        x = self.action(plan, "projects/demo/ep01-bac-thi/quach-phac's_note.txt")
        self.assertIn("title = 'quach-phac\\'s_note.txt'", x["archive"]["search_files"])
        self.assertEqual(x["create_file"]["title"], "quach-phac's_note.txt")

    def test_temp_files_ignored(self):
        self.snapshot("--include-out", "out/demo")
        for name in ("research.md.b64", "script.md.orig", "script.md.bak", "x.tmp", "shots.csv~"):
            self.write(f"ep01-bac-thi/{name}", "x\n")
        self.write("notes.part", "x\n")                                  # would be UNMAPPED
        (self.out / "ep01" / "bundles").mkdir()
        (self.out / "ep01" / "bundles" / "ep01_s01_20261110.zip.part").write_bytes(b"x")
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertEqual((plan["actions"], plan["unmapped"]), ([], []))
        self.assertEqual(len(plan["ignored_temp"]), 7)
        self.assertIn("projects/demo/ep01-bac-thi/research.md.b64", plan["ignored_temp"])
        self.assertEqual(plan["skipped_media"], 1)
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertEqual(out.count("ignored temp files"), 1)
        self.assertIn("script.md.orig", out)
        self.assertNotIn("NEW", out)
        self.assertNotIn("UNMAPPED", out)

    def test_changed_paragraph_only_with_a_changed_file(self):
        self.snapshot()
        self.write("ep01-bac-thi/prompts/s02_L4.txt", "bac thi\n")
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("Before uploading a NEW file", out)
        self.assertNotIn("Before uploading a CHANGED file", out)
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("Before uploading a CHANGED file", out)

    def test_record_line_carries_sha256(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("record projects/demo --uploaded projects/demo/ep01-bac-thi/script.md --id <new ID> "
                      f"--sha256 {ds.sha256(script)}", out)

    def test_unbundled_media_message(self):
        self.snapshot("--include-out", "out/demo")
        ep = self.out / "ep01"
        (ep / "clips").mkdir()
        (ep / "clips" / "ep01_s01_seedance_v01.mp4").write_bytes(b"mp4")
        (ep / "plates" / "notes.txt").write_text("no shot tag")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertIn("Nothing to push (text). 2 plate/clip file(s) are in no bundle: "
                      "they exist only in this container", out)
        self.assertNotIn("Nothing to push.", out)
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["unbundled_media"], 2)

        (ep / "bundles").mkdir()
        zp = ep / "bundles" / "ep01_s01_20261110.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("plates/ep01_s01_L1_nui_v01.png", b"png")
        self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/bundles/ep01_s01_20261110.zip",
                      "--id", "Z1")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertIn("Nothing to push (text). 1 plate/clip file(s) are in no bundle", out)

        with zipfile.ZipFile(zp, "a") as z:
            z.writestr("clips/ep01_s01_seedance_v01.mp4", b"mp4")
        self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/bundles/ep01_s01_20261110.zip",
                      "--id", "Z2")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertIn("Nothing to push.", out)
        self.assertNotIn("in no bundle", out)

    def test_unreadable_bundle_counts_as_empty(self):
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "bundles").mkdir()
        (self.out / "ep01" / "bundles" / "ep01_s01_20261110.zip").write_bytes(b"not a zip")
        self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/bundles/ep01_s01_20261110.zip",
                      "--id", "Z1")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertIn("1 plate/clip file(s) are in no bundle", out)


class TestCli(unittest.TestCase):
    def test_help_lists_commands(self):
        code, out, _ = run_main(ds.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"\{snapshot,pulled,plan,record\}")


class TestManifestErrors(DriveSyncCase):
    def test_missing_project_md(self):
        os.remove(self.pd / "PROJECT.md")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("PROJECT.md not found", err)
        self.assertIn("pull 00_QuanLy/PROJECT.md", err)

    def test_missing_project_dir(self):
        code, _, err = self.run_tool("plan", "projects/nope")
        self.assertEqual(code, 2)
        self.assertIn("project working copy not found", err)

    def test_no_folders(self):
        self.write("PROJECT.md", "---\nproject: demo\ndrive:\n  name: Demo\n---\n")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("drive.folders", err)

    def test_no_front_matter(self):
        self.write("PROJECT.md", "# Demo\n")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("no YAML front matter", err)

    def test_template_manifest(self):
        """The repo template parses; its <id> placeholders count as unknown folders."""
        tpl = ds.load_manifest(os.path.join(os.path.dirname(ds.__file__), "..", "templates", "project"))
        self.assertIn("99_LuuTru", tpl["folders"])
        self.assertIsNone(ds.folder_id(tpl, "99_LuuTru"))


if __name__ == "__main__":
    unittest.main()
