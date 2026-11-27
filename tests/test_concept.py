"""tools/concept.py: options parsing, gen/edit plans and comfy.py argument lists (subprocess mocked: no ComfyUI, no
GPU), resume and no-overwrite, the contact sheet, and approve read back by check_episode.py / status.py."""
import contextlib, io, json, sys, unittest
from pathlib import Path
from unittest import mock

import helpers

concept = helpers.load("concept.py", "film_concept_t")
try:
    from PIL import Image
except ImportError:              # Pillow is in requirements-ci.txt; the image tests skip without it
    Image = None

OPTIONS = """# Design options

<!-- ### z
Prompt EN: commented out, never read -->

### a – Hướng thời Lý
- **Prompt EN:** a slender mythic bird, long neck,
  five flat tail ribbons
- **Edit EN:** remove the second horn, keep everything else exactly

### Hướng b: tổng hợp
Prompt EN:
```text
line one
line two
```
Negative EN: blurry

### c
```
an unlabelled block
```

### d
nothing here yet

## 5. Gợi ý cho concept
| Hướng | Dựa trên | Prompt |
|---|---|---|
| e | x | a table prompt |
| f | | |
"""


def png(path, size=(64, 36), color=(90, 60, 30)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if Image is not None:
        Image.new("RGB", size, color).save(path)
    else:
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


def arg(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


class FakeComfy:
    """Stands in for `python tools/comfy/comfy.py run ...`: records the argv, writes --out (+ sidecar)."""

    def __init__(self, fail_at=None, code=1):
        self.calls, self.fail_at, self.code = [], fail_at, code

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            return self.code
        out = arg(argv, "--out")
        png(out)
        Path(out + ".json").write_text(json.dumps({"prompt": arg(argv, "--prompt"), "seed": arg(argv, "--seed")}))
        return 0


class Case(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.opts = self.tmp / "DESIGN-OPTIONS.md"
        self.opts.write_text(OPTIONS, encoding="utf-8")
        self.out = self.tmp / "concept"
        self.ledger = str(self.tmp / "ledger.csv")

    def cli(self, *argv, fake=None):
        fake = fake or FakeComfy()
        with mock.patch.object(concept, "run_cmd", fake):
            code, out, err = helpers.run_main(concept.main, [str(x) for x in argv])
        return code, out, err, fake


class TestOptions(Case):
    def test_markdown_formats(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = {x["id"]: x for x in concept.load_options(str(self.opts))["directions"]}
        self.assertEqual(sorted(d), ["a", "b", "c", "e"])          # z commented out, d and f have no prompt
        self.assertIn("direction 'd' has no prompt", err.getvalue())
        self.assertEqual(d["a"]["prompt"], "a slender mythic bird, long neck, five flat tail ribbons")
        self.assertEqual(d["a"]["edit"], "remove the second horn, keep everything else exactly")
        self.assertEqual(d["b"]["prompt"], "line one\nline two")
        self.assertEqual(d["b"]["negative"], "blurry")
        self.assertEqual(d["c"]["prompt"], "an unlabelled block")
        self.assertEqual(d["e"]["prompt"], "a table prompt")

    def test_the_template_and_its_labels_are_read(self):
        # templates/research/DESIGN-OPTIONS.md as copied: `### a – ...` with `Prompt EN:` / `Edit EN:` + fenced blocks
        tpl = helpers.REPO / "templates" / "research" / "DESIGN-OPTIONS.md"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = {x["id"]: x for x in concept.load_options(str(tpl))["directions"]}
        self.assertEqual(sorted(d), ["a"])                        # b, c have no prompt yet
        self.assertIn("A photorealistic", d["a"]["prompt"])
        self.assertIn("keep everything else unchanged", d["a"]["edit"])
        # the older bold labels with a parenthetical and a note before the colon
        old = ('### a "Han" – x\n\n**Prompt (EN)** (qwen-t2i):\n\n```text\nA bird A\n```\n\n'
               '**Edit (EN)** (qwen-edit) – nền `out/p/x.png`:\n\n```text\nremove horns\n```\n\n'
               '- **Negative (EN):** blurry\n')
        f = self.tmp / "old.md"
        f.write_text(old, encoding="utf-8")
        a = concept.load_options(str(f))["directions"][0]
        self.assertEqual((a["id"], a["prompt"], a["edit"], a["negative"]), ("a", "A bird A", "remove horns", "blurry"))
        # `## A. "..."` directions are not read, but say why
        f.write_text(old.replace("### a", "## A."), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(concept.load_options(str(f))["directions"], [])
        self.assertIn("level-3 heading", err.getvalue())

    def test_json_jobs_and_refusals(self):
        j = self.tmp / "jobs.json"
        j.write_text(json.dumps({"slug": "con-a", "seeds": [7, 9], "directions": [{"id": "x", "prompt": "p"}]}))
        data = concept.load_options(str(j))
        self.assertEqual(data["slug"], "con-a")
        self.assertEqual(data["directions"][0]["prompt"], "p")
        j.write_text(json.dumps([{"id": "Bad Id", "prompt": "p"}]))
        with self.assertRaises(concept.Refused):
            concept.load_options(str(j))
        j.write_text(json.dumps([{"id": "x", "prompt": "p"}, {"id": "x", "prompt": "q"}]))
        with self.assertRaises(concept.Refused):
            concept.load_options(str(j))


class TestGen(Case):
    def test_dry_run_prints_the_plan_and_calls_nothing(self):
        code, out, _, fake = self.cli("gen", self.opts, "--slug", "phuong-hoang", "--out-dir", self.out,
                                      "--ledger", self.ledger, "--only", "a,b", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn("4 image(s) to make", out)
        self.assertIn("phuong-hoang_a_s1001_v01.png", out)
        self.assertIn("phuong-hoang_b_s1002_v01.png", out)
        self.assertIn("dry-run: nothing called", out)
        self.assertFalse(self.out.exists())

    def test_argument_lists_keep_models_and_resume(self):
        code, _, _, fake = self.cli("gen", self.opts, "--slug", "phuong-hoang", "--out-dir", self.out,
                                    "--ledger", self.ledger, "--only", "a,b", "--n", "2", "--seed-start", "7",
                                    "--size", "1328x1328", "--review", "q01t03-concept-phuong-hoang")
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.calls), 4)
        first = fake.calls[0]
        self.assertEqual(first[:4], [sys.executable, concept.COMFY, "run", "qwen-t2i"])
        self.assertEqual(arg(first, "--prompt"), "a slender mythic bird, long neck, five flat tail ribbons")
        self.assertEqual(arg(first, "--seed"), "7")
        self.assertEqual(arg(first, "--size"), "1328x1328")
        self.assertEqual(arg(first, "--ledger"), self.ledger)
        self.assertEqual(arg(first, "--review"), "q01t03-concept-phuong-hoang")
        self.assertEqual(Path(arg(first, "--out")).name, "phuong-hoang_a_s7_v01.png")
        self.assertEqual(arg(fake.calls[2], "--negative"), "blurry")
        self.assertEqual([("--keep-models" in c) for c in fake.calls], [True, True, True, False])
        names = sorted(p.name for p in self.out.glob("*.png"))
        self.assertEqual(names, ["phuong-hoang_a_s7_v01.png", "phuong-hoang_a_s8_v01.png",
                                 "phuong-hoang_b_s7_v01.png", "phuong-hoang_b_s8_v01.png"])
        # resume: everything exists -> nothing is called again; a new round is --version 2
        code, out, _, fake2 = self.cli("gen", self.opts, "--slug", "phuong-hoang", "--out-dir", self.out,
                                       "--ledger", self.ledger, "--only", "a,b", "--seed-start", "7")
        self.assertEqual((code, fake2.calls), (0, []))
        self.assertIn("skip (exists)", out)
        code, _, _, fake3 = self.cli("gen", self.opts, "--slug", "phuong-hoang", "--out-dir", self.out,
                                     "--ledger", self.ledger, "--only", "a", "--n", "1", "--seed-start", "7",
                                     "--version", "2")
        self.assertEqual(Path(arg(fake3.calls[0], "--out")).name, "phuong-hoang_a_s7_v02.png")
        self.assertNotIn("--keep-models", fake3.calls[-1])

    def test_a_failure_stops_the_batch_without_retry(self):
        code, _, err, fake = self.cli("gen", self.opts, "--slug", "phuong-hoang", "--out-dir", self.out,
                                      "--ledger", self.ledger, fake=FakeComfy(fail_at=2))
        self.assertEqual(code, 1)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("not retried", err)

    def test_refusals(self):
        code, _, err, fake = self.cli("gen", self.opts, "--slug", "phuong-hoang", "--out-dir", self.out)
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("--ledger", err)
        code, _, err, _ = self.cli("gen", self.opts, "--slug", "Bad Slug", "--out-dir", self.out, "--ledger", "l")
        self.assertEqual(code, 2)
        code, _, err, _ = self.cli("gen", self.opts, "--slug", "x", "--out-dir", self.out, "--ledger", "l",
                                   "--only", "zz")
        self.assertEqual(code, 2)
        self.assertIn("zz", err)

    def test_json_seeds(self):
        j = self.tmp / "jobs.json"
        j.write_text(json.dumps({"slug": "con-a", "seeds": [7, 9, 11], "directions": [{"id": "x", "prompt": "p"}]}))
        code, _, _, fake = self.cli("gen", j, "--out-dir", self.out, "--ledger", self.ledger)
        self.assertEqual([arg(c, "--seed") for c in fake.calls], ["7", "9", "11"])
        self.assertEqual(Path(arg(fake.calls[0], "--out")).name, "con-a_x_s7_v01.png")


class TestEdit(Case):
    def setUp(self):
        super().setUp()
        self.src = png(self.out / "phuong-hoang_a_s7_v01.png")

    def test_instruction_argv_record_resume_redo(self):
        code, _, _, fake = self.cli("edit", self.src, "--instruction", "remove the second horn", "--ledger",
                                    self.ledger, "--review", "b1")
        self.assertEqual(code, 0)
        (c,) = fake.calls
        self.assertEqual(c[:4], [sys.executable, concept.COMFY, "run", "qwen-edit"])
        self.assertEqual(arg(c, "--image"), str(self.src))
        self.assertEqual(arg(c, "--prompt"), "remove the second horn")
        self.assertEqual((arg(c, "--lightning"), arg(c, "--denoise"), arg(c, "--seed")), ("4", "1", "7"))
        self.assertEqual(Path(arg(c, "--out")).name, "phuong-hoang_a_s7_v01_e01.png")
        self.assertEqual(arg(c, "--review"), "b1")
        self.assertNotIn("--keep-models", c)
        rec = json.loads((self.out / concept.EDITS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(rec[0]["out"], "phuong-hoang_a_s7_v01_e01.png")
        self.assertEqual(rec[0]["instruction"], "remove the second horn")
        # the same edit again: skipped; --redo: a new version, never an overwrite
        code, out, _, fake = self.cli("edit", self.src, "--instruction", "remove the second horn", "--ledger",
                                      self.ledger)
        self.assertEqual((code, fake.calls), (0, []))
        self.assertIn("skip (done)", out)
        code, _, _, fake = self.cli("edit", self.src, "--instruction", "remove the second horn", "--ledger",
                                    self.ledger, "--redo", "--seed", "8", "--seed", "9", "--lightning", "8")
        self.assertEqual([Path(arg(c, "--out")).name for c in fake.calls],
                         ["phuong-hoang_a_s7_v01_e02.png", "phuong-hoang_a_s7_v01_e03.png"])
        self.assertEqual([("--keep-models" in c) for c in fake.calls], [True, False])
        self.assertEqual(arg(fake.calls[0], "--lightning"), "8")

    def test_edit_from_options_and_refusals(self):
        code, _, _, fake = self.cli("edit", self.src, "--options", self.opts, "--ledger", self.ledger)
        self.assertEqual(code, 0)
        self.assertEqual(arg(fake.calls[0], "--prompt"), "remove the second horn, keep everything else exactly")
        other = png(self.out / "phuong-hoang_b_s7_v01.png")
        code, _, err, fake = self.cli("edit", other, "--options", self.opts, "--ledger", self.ledger)
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("Edit EN", err)
        odd = png(self.out / "random.png")
        code, _, err, _ = self.cli("edit", odd, "--instruction", "x", "--ledger", self.ledger)
        self.assertEqual(code, 2)
        code, _, err, _ = self.cli("edit", self.src, "--instruction", "x")
        self.assertEqual(code, 2)


@unittest.skipIf(Image is None, "Pillow missing")
class TestSheet(Case):
    def test_grid_and_before_after(self):
        for d in ("a", "b"):
            for s in (7, 8):
                png(self.out / f"phuong-hoang_{d}_s{s}_v01.png", (160, 90))
        png(self.out / "phuong-hoang_a_s7_v01_e01.png", (160, 90), (10, 120, 10))
        (self.out / concept.EDITS_FILE).write_text(json.dumps(
            [{"src": "phuong-hoang_a_s7_v01.png", "out": "phuong-hoang_a_s7_v01_e01.png", "seed": 7,
              "instruction": "remove the second horn"}]), encoding="utf-8")
        code, out, err, _ = self.cli("sheet", self.out, "--cell", "200", "--cols", "3")
        self.assertEqual(code, 0, err)
        sheet = self.out / "phuong-hoang_sheet_v01.png"
        self.assertTrue(sheet.is_file(), out)
        with Image.open(sheet) as im:
            # row 1: before/after (2 cells), then 3 plain images in rows of 3 -> 2 rows; 3 columns wide
            self.assertEqual(im.size[0], 3 * 200)
            band = max(18, 200 // 18)
            self.assertEqual(im.size[1], 8 + band + 2 * (round(200 * 9 / 16) + 2 * band))
        code, _, _, _ = self.cli("sheet", self.out, "--cell", "200")
        self.assertTrue((self.out / "phuong-hoang_sheet_v02.png").is_file())   # next version, v01 untouched
        code, _, err, _ = self.cli("sheet", self.out, "--out", sheet)
        self.assertEqual(code, 2)
        self.assertIn("exists", err)


EPISODE = """---
series: test-series
book: null
episode: 1
slug: test-ep
stage: 3
method: blender
---
# Tập 1

## Sinh vật của tập

<!-- Concept: chờ | duyệt <ngày> <file>
     | chờ. a pipe line inside the comment -->

| slug | Tên | Chính | Ảnh sách | Concept |
|---|---|---|---|---|
| phuong-hoang | Phượng hoàng | có | có | chờ |
| `A-ho-giao` | Hổ giao | có | không | chờ |
| ca-ba-chan | Cá ba chân | không | chờ |  |

## Nhật ký

- 2026-11-26 | 3a | concept | chưa
"""


class TestApprove(Case):
    def setUp(self):
        super().setUp()
        self.project = self.tmp / "projects" / "test-series"
        self.ep = self.project / "ep01-test-ep"
        self.ep.mkdir(parents=True)
        (self.ep / "EPISODE.md").write_text(EPISODE, encoding="utf-8")
        self.img = png(self.tmp / "out" / "test-series" / "characters" / "ho-giao" / "concept" /
                       "ho-giao_a_s7_v01_e01.png")
        self.ce = helpers.load("check_episode.py", "film_check_episode_t")

    def creatures(self):
        _, body = self.ce.split_front_matter(self.ce.read_text(str(self.ep / "EPISODE.md")))
        return {r["slug"]: r for r in self.ce.read_creatures(body)["rows"]}

    def test_approve_writes_what_check_episode_reads(self):
        before = (self.ep / "EPISODE.md").read_text(encoding="utf-8").splitlines()
        code, out, err, _ = self.cli("approve", "ho-giao", self.img, "--episode", self.ep, "--date", "2026-11-26",
                                     "--quote", "lấy con này")
        self.assertEqual(code, 0, err)
        after = (self.ep / "EPISODE.md").read_text(encoding="utf-8").splitlines()
        changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changed), 1)
        self.assertIn("`A-ho-giao`", after[changed[0]])
        self.assertIn("duyệt 2026-11-26", after[changed[0]])
        rows = self.creatures()
        self.assertEqual(rows["ho-giao"]["concept"], "approved")
        self.assertEqual(rows["phuong-hoang"]["concept"], "pending")
        char = self.project / "characters" / "ho-giao" / "CHARACTER.md"
        text = char.read_text(encoding="utf-8")
        self.assertIn("## Concept đã duyệt", text)
        self.assertIn("ho-giao_a_s7_v01_e01.png", text)
        self.assertIn("lấy con này", text)
        self.assertEqual(self.ce.concept_record(str(self.ep), "ho-giao"), "characters/ho-giao/CHARACTER.md")
        gaps = dict(self.ce.concept_gaps(str(self.ep), list(rows.values())))
        self.assertNotIn("ho-giao", gaps)
        self.assertIn("phuong-hoang", gaps)
        # status.py reads the same table (CREATURES section, gate G2)
        status = helpers.load("status.py", "film_status_concept_t")
        _, body = self.ce.split_front_matter(self.ce.read_text(str(self.ep / "EPISODE.md")))
        sec = status.creatures_section(str(self.ep), body, "blender", None, [])
        self.assertEqual([g["slug"] for g in sec["concept_gaps"]], ["phuong-hoang"])
        # idempotent: the same file again changes nothing
        snap = ((self.ep / "EPISODE.md").read_bytes(), char.read_bytes())
        code, out, _, _ = self.cli("approve", "ho-giao", self.img, "--episode", self.ep, "--date", "2026-12-01")
        self.assertEqual(code, 0)
        self.assertEqual(((self.ep / "EPISODE.md").read_bytes(), char.read_bytes()), snap)
        self.assertIn("unchanged", out)

    def test_another_file_replaces_and_a_missing_row_is_added(self):
        self.cli("approve", "ho-giao", self.img, "--episode", self.ep, "--date", "2026-11-26")
        other = png(self.img.parent / "ho-giao_b_s9_v01.png")
        code, _, err, _ = self.cli("approve", "ho-giao", other, "--episode", self.ep, "--date", "2026-11-27")
        self.assertEqual(code, 0, err)
        text = (self.project / "characters" / "ho-giao" / "CHARACTER.md").read_text(encoding="utf-8")
        self.assertIn("ho-giao_b_s9_v01.png", text)
        self.assertIn("Thay cho:", text)
        self.assertEqual(text.count("## Concept đã duyệt"), 1)
        self.assertIn("ho-giao_b_s9_v01.png", self.creatures()["ho-giao"]["concept_text"])
        new = png(self.tmp / "con-moi_a_s1_v01.png")
        code, out, err, _ = self.cli("approve", "con-moi", new, "--episode", self.ep, "--name", "Con mới")
        self.assertEqual(code, 0, err)
        rows = self.creatures()
        self.assertEqual((rows["con-moi"]["concept"], rows["con-moi"]["book"], rows["con-moi"]["main"]),
                         ("approved", "pending", True))
        self.assertEqual(rows["ca-ba-chan"]["concept_text"], "")
        body = (self.ep / "EPISODE.md").read_text(encoding="utf-8")
        self.assertLess(body.index("con-moi"), body.index("## Nhật ký"))

    def test_an_existing_character_md_keeps_its_other_sections(self):
        char = self.project / "characters" / "ho-giao" / "CHARACTER.md"
        char.parent.mkdir(parents=True)
        char.write_text("# Hổ giao\n\n## Giải phẫu\n\n| phần | nguồn |\n\n## Concept đã duyệt\n\n- File: `old.png`\n"
                        "- Ngày duyệt: 2026-11-01\n\n## Prompt khóa\n\nkeep me\n", encoding="utf-8")
        code, _, err, _ = self.cli("approve", "ho-giao", self.img, "--episode", self.ep, "--date", "2026-11-26")
        self.assertEqual(code, 0, err)
        text = char.read_text(encoding="utf-8")
        self.assertIn("## Giải phẫu\n\n| phần | nguồn |\n", text)
        self.assertIn("## Prompt khóa\n\nkeep me\n", text)
        self.assertIn("- Thay cho: `old.png` (2026-11-01)", text)

    def test_refusals_and_dry_run(self):
        snap = (self.ep / "EPISODE.md").read_bytes()
        code, out, _, _ = self.cli("approve", "ho-giao", self.img, "--episode", self.ep, "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual((self.ep / "EPISODE.md").read_bytes(), snap)
        self.assertFalse((self.project / "characters").exists())
        code, _, _, _ = self.cli("approve", "ho-giao", self.tmp / "nope.png", "--episode", self.ep)
        self.assertEqual(code, 2)
        (self.ep / "EPISODE.md").write_text("---\nstage: 3\n---\n# x\n", encoding="utf-8")
        code, _, err, _ = self.cli("approve", "ho-giao", self.img, "--episode", self.ep)
        self.assertEqual(code, 2)
        self.assertIn("Sinh vật của tập", err)


if __name__ == "__main__":
    unittest.main()
