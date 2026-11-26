"""Docs lint: what CLAUDE.md, docs/, skills, agents, style packs and templates tell a session to run must exist.

Checked against the code at test time (never a frozen list), so a branch that adds a subcommand or a flag together
with its docs passes as is:
- repo paths named in code spans, code blocks and Markdown links (tools/..., docs/..., .claude/..., styles/...);
- `references/<file>` inside a skill folder;
- for a repo tool named in a command (`python3 tools/ark.py image ...`, `ark.py ledger-merge`): its subcommands
  (argparse add_parser names, nested ones too) and its `--long-options` (the literal must be in the tool's source);
- agent front matter (name = file name, description, known tools) and skill front matter (name = folder, description).
ALLOW holds drift that cannot be fixed in the docs right now, with the reason; prefer fixing the doc.
"""
import glob, re, unittest
from pathlib import Path

import helpers

REPO = helpers.REPO
try:
    import yaml
except ImportError:            # tools/ci.sh --install brings it; the front matter tests skip without it
    yaml = None

# Docs that describe the repo as it is now. Not: CHANGELOG.md, docs/BACKLOG.md and docs/releases/* (history, they
# name things that are gone on purpose), THIRD_PARTY.md (paths in other projects), tests/fixtures (test data).
DOC_GLOBS = ("CLAUDE.md", "README.md", "docs/*.md", ".claude/agents/*.md", ".claude/skills/**/*.md",
             ".claude/agent-memory/**/*.md", "styles/**/*.md", "templates/**/*.md", "lambda/*.md", "tools/**/*.md")
DOC_SKIP = ("docs/BACKLOG.md",)
PREFIXES = (".claude", "tools", "docs", "lambda", "tests", "templates", "styles", "formats")

# "<kind>:<item>" -> reason. Kinds: path, subcommand (<tool> <name>), option (<tool> <--flag>).
ALLOW = {}

KNOWN_AGENT_TOOLS = {"Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "WebSearch", "WebFetch",
                     "NotebookEdit", "TodoWrite", "Agent", "Task", "Skill"}


def doc_files():
    out = set()
    for pat in DOC_GLOBS:
        for p in glob.glob(str(REPO / pat), recursive=True):
            rel = Path(p).relative_to(REPO).as_posix()
            if rel not in DOC_SKIP and Path(p).is_file():
                out.add(rel)
    return sorted(out)


FENCE = re.compile(r"^\s*(```|~~~)")
SPAN = re.compile(r"(`+)(.+?)\1")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def segments(text):
    """(line number, code text, from a fenced block?) for every code block line and inline code span.
    Block lines ending in a backslash are joined with the next one."""
    out, fenced, carry = [], False, None
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            if carry:
                line = carry[1] + " " + line.strip()
                n = carry[0]
            if line.rstrip().endswith("\\"):
                carry = (n, line.rstrip()[:-1])
                continue
            carry = None
            out.append((n, line, True))
        else:
            for m in SPAN.finditer(line):
                out.append((n, m.group(2), False))
    return out


def links(text):
    for n, line in enumerate(text.splitlines(), 1):
        for m in LINK.finditer(line):
            yield n, m.group(1)


# --- paths -------------------------------------------------------------------------------------------------------

PATH_RE = re.compile(r"(?<![\w./~$@:-])((?:%s)/(?:\{[^}\s`]*\}|[^\s`'\"()\[\],;|{])*)"
                     % "|".join(re.escape(p) for p in PREFIXES))
PLACEHOLDER = re.compile(r"[<>$…]|\.\.\.|\bNN\b|XX|x\.y\.z", re.I)
SKILL_DIRS = sorted(p for p in (REPO / ".claude" / "skills").iterdir() if p.is_dir())
# Paths that skills write relative to the cinecode skill (its tools/, templates/, references/). Checked against the
# installed skill when there is one ($CINECODE_DIR or ~/.claude/skills/cinecode), accepted by name otherwise.
CINECODE_NAMES = {"tools/make.py", "tools/capture.mjs", "tools/formats.py", "tools/sounds.py", "tools/tts.py",
                  "templates/quick/film.html", "templates/quick/{film.html,STATE.md}", "references/sound.md",
                  "references/writing.md"}
CINECODE_INSTALLED = helpers.exists(helpers.CINECODE / "SKILL.md", "is_file")


def brace_expand(s):
    m = re.search(r"\{([^{}]*)\}", s)
    if not m:
        return [s]
    return [x for part in m.group(1).split(",") for x in brace_expand(s[:m.start()] + part + s[m.end():])]


def path_ok(rel, roots=(REPO,)):
    """True when the path (glob and {a,b} allowed) exists under one of roots, or is a cinecode path."""
    if not CINECODE_INSTALLED and rel in CINECODE_NAMES:
        return True
    if CINECODE_INSTALLED:
        roots = (*roots, helpers.CINECODE)
    for p in brace_expand(rel):
        if any(c in p for c in "*?["):
            hit = any(glob.glob(str(r / p), recursive=True) for r in roots)
        else:
            hit = any(helpers.exists(r / p.rstrip("/")) for r in roots)
        if not hit:
            return False
    return True


def clean_path(raw):
    p = re.split(r"[#:](?=\w|$)", raw, maxsplit=1)[0] if not raw.startswith(".claude") else raw.split("#")[0]
    p = re.sub(r":\d.*$", "", p)                 # tools/ark.py:123
    return p.rstrip(".:,;!?")


# --- tools, subcommands, options ---------------------------------------------------------------------------------

TOOL_FILES = sorted(p.relative_to(REPO).as_posix() for d in ("tools", "lambda")
                    for p in (REPO / d).rglob("*") if p.suffix in (".py", ".sh") and "__pycache__" not in p.parts)
BY_NAME = {}
for _t in TOOL_FILES:
    BY_NAME.setdefault(Path(_t).name, []).append(_t)
ALIASES = {"/opt/byteplus/ark.py": "tools/ark.py"}        # the session hook links it to the repo's ark.py


class Tool:
    """What the docs may say about a tool, read from its source text."""
    _cache = {}

    def __init__(self, rel):
        self.rel = rel
        self.src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        self.top, self.children = self._subcommands()

    @classmethod
    def get(cls, rel):
        if rel not in cls._cache:
            cls._cache[rel] = cls(rel)
        return cls._cache[rel]

    def _subcommands(self):
        """argparse: top-level subcommand names and, for each, its nested ones."""
        if not self.rel.endswith(".py"):
            return set(), {}
        named = {}                                # parser variable -> subcommand name
        owner = {}                                # subparsers variable -> parser variable that owns it
        made = []                                 # (subparsers variable, name, new parser variable or None)
        for m in re.finditer(r"(?:(\w+)\s*=\s*)?(\w+)\.add_parser\(\s*[\"']([\w-]+)[\"']", self.src):
            made.append((m.group(2), m.group(3), m.group(1)))
            if m.group(1):
                named[m.group(1)] = m.group(3)
        for m in re.finditer(r"(\w+)\s*=\s*(\w+)\.add_subparsers\(", self.src):
            owner[m.group(1)] = m.group(2)
        top, children = set(), {}
        for sub, name, _ in made:
            parent = named.get(owner.get(sub, ""))
            if parent:
                children.setdefault(parent, set()).add(name)
            else:
                top.add(name)
        return top, children

    def has_option(self, flag):
        if self.rel.endswith(".py"):
            if flag == "--help":                  # argparse adds it
                return True
            return re.search(r"[\"']%s[\"'=]" % re.escape(flag), self.src) is not None
        return re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(flag), self.src) is not None


CMD_RE = re.compile(r"(?:^|(?<=[\s(]))((?:[\w.$~{}/-]*/)?([\w-]+\.(?:py|sh)))(?=\s|$)(.*)")
SPLIT = re.compile(r"\s(?:#|\||;|&&|\|\||→|->|>|2>|<<)\s|\s#")
STRIP = "[](){}\"'`,.:;"
OPT_RE = re.compile(r"^[\[(]*(--[a-z0-9][a-z0-9-]*)")


def resolve_tool(path, name):
    if path in ALIASES:
        return ALIASES[path]
    p = re.sub(r"^(\./|\$FILM_LAB/|\$\{FILM_LAB\}/|\$LAB/)", "", path)
    if "/" in p:
        return p if p in TOOL_FILES else None
    found = BY_NAME.get(name, [])
    return found[0] if len(found) == 1 else None


def commands(code):
    """(tool path, the words after it) for every repo tool named in a code segment."""
    out, rest = [], code
    while True:
        m = CMD_RE.search(rest)
        if not m:
            return out
        tool = resolve_tool(m.group(1), m.group(2))
        tail = m.group(3)
        cut = SPLIT.search(" " + tail)
        words = (" " + tail)[:cut.start()].split() if cut else tail.split()
        if tool:
            out.append((tool, words))
        rest = tail


def check_command(tool, words):
    """-> list of problems ("subcommand:<tool> <name>" / "option:<tool> <flag>")."""
    t, problems = Tool.get(tool), []
    if t.top and words:
        first = words[0].strip(STRIP)
        if first and not first.startswith("-") and not PLACEHOLDER.search(first) and words[0][0] not in "'\"":
            alts = [a for a in re.split(r"[|/]", first) if a]
            for a in alts:
                if a not in t.top:
                    problems.append(f"subcommand:{tool} {a}")
            if len(alts) == 1 and alts[0] in t.children and len(words) > 1:
                second = words[1].strip(STRIP)
                if second and not second.startswith("-") and not PLACEHOLDER.search(second):
                    for a in re.split(r"[|/]", second):
                        if a and a not in t.children[alts[0]]:
                            problems.append(f"subcommand:{tool} {alts[0]} {a}")
    for w in words:
        m = OPT_RE.match(w)
        if m and not t.has_option(m.group(1)):
            problems.append(f"option:{tool} {m.group(1)}")
    return problems


# --- the scan ----------------------------------------------------------------------------------------------------

def scan():
    """{"<kind>:<item>": ["file:line", ...]} for everything the docs name that the repo does not have."""
    found = {}

    def add(key, where):
        found.setdefault(key, []).append(where)

    for rel in doc_files():
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        skill = re.match(r"\.claude/skills/([^/]+)/", rel)
        # a skill names its own files relative to its folder (references/, templates/), sometimes another skill's
        roots = (REPO, REPO / ".claude/skills" / skill.group(1), *SKILL_DIRS) if skill else (REPO,)
        for n, code, _ in segments(text):
            for m in PATH_RE.finditer(code):
                p = clean_path(m.group(1))
                if p.count("/") and not PLACEHOLDER.search(p) and not path_ok(p, roots):
                    add(f"path:{p}", f"{rel}:{n}")
            if skill:
                for m in re.finditer(r"(?<![\w/.-])(references/[\w.-]+\.md)", code):
                    if not path_ok(m.group(1), roots[1:]):
                        add(f"path:{m.group(1)}", f"{rel}:{n}")
            for tool, words in commands(code):
                for key in check_command(tool, words):
                    add(key, f"{rel}:{n}")
        for n, target in links(text):
            if re.match(r"^(\w+:|#|mailto:)", target) or PLACEHOLDER.search(target):
                continue
            t = target.split("#")[0]
            if t and not (REPO / rel).parent.joinpath(t).resolve().exists():
                add(f"link:{t}", f"{rel}:{n}")
    return found


def front_matter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return yaml.safe_load(m.group(1)) if m else None


class TestScanner(unittest.TestCase):
    """The scanner itself, on small made-up snippets."""

    def test_segments_join_continuations_and_find_spans(self):
        segs = segments("text `tools/ark.py ping` and `x`\n```\npython3 tools/ark.py image \\\n  --size 2K\n```\n")
        self.assertEqual([s[1] for s in segs][:2], ["tools/ark.py ping", "x"])
        self.assertIn("--size 2K", segs[2][1])
        self.assertTrue(segs[2][2])

    def test_commands_and_subcommands(self):
        self.assertEqual(commands("python3 tools/ark.py image \"p\" o.png --size 2K  # comment --nope"),
                         [("tools/ark.py", ["image", '"p"', "o.png", "--size", "2K"])])
        self.assertEqual(commands("ark.py image|video|lambda-job prepare")[0][0], "tools/ark.py")
        self.assertEqual(check_command("tools/ark.py", ["image|video|lambda-job", "prepare"]), [])
        self.assertEqual(check_command("tools/ark.py", ["lambda-job", "finish"]), [])
        self.assertEqual(check_command("tools/ark.py", ["no-such-cmd"]), ["subcommand:tools/ark.py no-such-cmd"])
        self.assertEqual(check_command("tools/ark.py", ["lambda-job", "nope"]), ["subcommand:tools/ark.py lambda-job nope"])
        self.assertEqual(check_command("tools/ark.py", ["<cmd>", "--size"]), [])
        self.assertEqual(check_command("tools/ark.py", ["image", "[--no-such-flag]"]),
                         ["option:tools/ark.py --no-such-flag"])
        self.assertEqual(check_command("tools/doctor.sh", ["--quick"]), [])
        self.assertEqual(check_command("tools/doctor.sh", ["--slow"]), ["option:tools/doctor.sh --slow"])

    def test_unknown_or_foreign_tools_are_not_checked(self):
        self.assertEqual(commands("python3 ~/.claude/skills/cinecode/scripts/make.py final --whatever"), [])
        self.assertEqual(commands("/opt/byteplus/ark.py ping")[0][0], "tools/ark.py")

    def test_paths(self):
        self.assertTrue(path_ok("tools/compose/*.js"))
        self.assertTrue(path_ok("tools/{ark,status}.py"))
        self.assertFalse(path_ok("tools/{ark,nope}.py"))
        self.assertEqual(clean_path("tools/ark.py:123"), "tools/ark.py")
        self.assertEqual(clean_path("docs/CONVENTIONS.md#11."), "docs/CONVENTIONS.md")
        self.assertEqual([m.group(1) for m in PATH_RE.finditer("see out/x/tools/a.py and tools/b.py.")],
                         ["tools/b.py."])


class TestDocsMatchTheCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = scan()

    maxDiff = None

    def report(self, kinds):
        bad = {k: v for k, v in self.found.items() if k.split(":", 1)[0] in kinds and k not in ALLOW}
        return "\n".join(f"{k}  ({', '.join(v[:4])}{' ...' if len(v) > 4 else ''})" for k, v in sorted(bad.items()))

    def test_named_paths_exist(self):
        self.assertEqual(self.report({"path", "link"}), "", "fix the doc, or add a reasoned ALLOW entry")

    def test_named_subcommands_exist(self):
        self.assertEqual(self.report({"subcommand"}), "", "fix the doc, or add a reasoned ALLOW entry")

    def test_named_options_exist(self):
        self.assertEqual(self.report({"option"}), "", "fix the doc, or add a reasoned ALLOW entry")

    def test_the_scan_sees_the_tool_list(self):
        # guards the scanner: CLAUDE.md's tool block must be read as commands
        text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        tools = {t for _, code, _ in segments(text) for t, _ in commands(code)}
        self.assertTrue({"tools/ark.py", "tools/status.py", "tools/check_episode.py"} <= tools, tools)


class TestAgentsAreRegistered(unittest.TestCase):
    """Every agent of .claude/agents/ has a row in the agent table of docs/WORKFLOW.md §3 and is named in the
    film-pipeline skill (the director only hands work to agents it knows)."""

    def test_agents_listed(self):
        workflow = (REPO / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
        pipeline = (REPO / ".claude" / "skills" / "film-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        agents = sorted(p.stem for p in (REPO / ".claude" / "agents").glob("*.md"))
        self.assertIn("film-dop", agents)
        self.assertEqual([a for a in agents if f"| `{a}` |" not in workflow], [], "add a row to docs/WORKFLOW.md §3")
        self.assertEqual([a for a in agents if f"`{a}`" not in pipeline], [], "name the agent in film-pipeline")


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class TestFrontMatter(unittest.TestCase):
    def test_agents(self):
        agents = sorted((REPO / ".claude" / "agents").glob("*.md"))
        self.assertTrue(agents)
        for path in agents:
            with self.subTest(agent=path.name):
                fm = front_matter(path)
                self.assertIsInstance(fm, dict, "front matter between --- lines")
                self.assertEqual(fm.get("name"), path.stem)
                self.assertIsInstance(fm.get("description"), str)
                self.assertGreater(len(fm["description"].strip()), 20)
                tools = fm.get("tools")
                if tools is not None:
                    names = [t.strip() for t in (tools.split(",") if isinstance(tools, str) else tools)]
                    self.assertTrue(names)
                    unknown = [t for t in names if t not in KNOWN_AGENT_TOOLS and not t.startswith("mcp__")]
                    self.assertEqual(unknown, [])
                if "model" in fm:
                    self.assertIsInstance(fm["model"], str)

    def test_skills(self):
        skills = sorted((REPO / ".claude" / "skills").glob("*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                fm = front_matter(path)
                self.assertIsInstance(fm, dict, "front matter between --- lines")
                self.assertEqual(fm.get("name"), path.parent.name)
                self.assertRegex(fm["name"], r"^[a-z0-9-]{1,64}$")
                self.assertIsInstance(fm.get("description"), str)
                self.assertTrue(20 < len(fm["description"].strip()) <= 1024, len(fm["description"]))

    def test_every_skill_folder_has_a_skill_md(self):
        for d in sorted((REPO / ".claude" / "skills").iterdir()):
            if d.is_dir():
                self.assertTrue((d / "SKILL.md").is_file(), d.name)


if __name__ == "__main__":
    unittest.main()
