# Fixture: cinecode Quick template

`film.html` and `quick-STATE.md` are unmodified copies of `templates/quick/film.html` and `templates/quick/STATE.md`
from https://github.com/sarpstar/cinecode at the commit pinned in `tools/compose/cinecode.ref`
(MIT, see `LICENSE` here). `tests/test_compose.py` runs `tools/compose/inline.py --init` on a copy of them.

The state file is stored as `quick-STATE.md` on purpose: a file named `STATE.md` belongs to cinecode
(docs/CONVENTIONS.md §5) and must not sit in the repo.

When the pin moves: copy both files again from the new commit, run `python3 -m unittest discover -s tests -p test_compose.py`,
and fix `inline.py` if its markers no longer match (docs/RUNBOOK.md, "cinecode đổi template").
