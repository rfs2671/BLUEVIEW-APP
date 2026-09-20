"""Flag a bare `assertNotIn` literal BEFORE the commit, not at gate time.

    python backend/scripts/check_absence_literals.py [FILE ...]

With no arguments it scans the whole backend suite, which is what the gate
does. `.githooks/pre-commit` passes the STAGED blobs instead.

WHY IT EXISTS. `assertNotIn("Pass", html)` bans four characters, not a result
cell — `in` on a string is substring containment, so the assertion says one
thing and checks another. The suite has enforced the anchored-literal rule for
a while and it WORKS; what it does not do is run early. It caught the same
reflex four separate times in one week, each time after a push, and each catch
cost a round trip that a hook would have spent locally in under a second.

The detection is not reimplemented here. It is imported from
`tests/absence_literals.py`, which the gate imports too, so the hook and the
gate cannot disagree about what counts as anchored or about which bare
literals are justified.

READS THE FILES IT IS GIVEN. The hook hands it staged blobs written to a temp
directory under their own basenames, because a partially staged file's working
copy is not what is being committed — and the allowlist keys on basename, so
the blobs are scanned against exactly the same entries.

Exit 0 clean, 1 on an offender, 2 on a usage error. Stdlib only: it must run
from a git hook with no virtualenv active.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from tests.absence_literals import ADVICE, offenders, scan  # noqa: E402


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    paths: list[Path] | None = None
    if args:
        paths = [Path(a) for a in args]
        missing = [p for p in paths if not p.is_file()]
        if missing:
            print(f"check_absence_literals: not a file: {missing}",
                  file=sys.stderr)
            return 2
        if not paths:
            return 0

    found = offenders(paths)
    if not found:
        # The count is printed so a run that scanned NOTHING is visible.
        # Silence would look identical to success, which is the vacuous pass
        # this rule exists to refuse everywhere else.
        _bare, anchored, _unclassified, total = scan(paths)
        where = f"{len(paths)} staged file(s)" if paths else "the backend suite"
        print(f"[absence-literals] ok - {total} assertNotIn in {where}, "
              f"{anchored} anchored, 0 unjustified bare")
        return 0

    print()
    print("[absence-literals] a bare literal bans a WORD, not a construct:")
    print()
    for f in found:
        print(f"    {f.file}:{f.line}   assertNotIn({f.literal!r}, <string>)")
    print()
    for line in ADVICE.splitlines():
        print(f"  {line}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
