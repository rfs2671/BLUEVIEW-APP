"""lib/location_binder, round 2: the strict-subset rule made STRUCTURAL.

Adversarial review 1 (section C) found phrasings the per-phrase readers still
narrowed: "floors 2 3 4" -> floor 2 alone, "1st floor to roof" -> {1, ROOF},
"2nd floor and up" -> 2, "above 2nd floor" -> 2 (the wrong floor), and mixed
trades joined by "and" read as the union. The rule held here is on the RESULT,
whatever reader produced it:

    every floor the words state is in the answer, no level the words do not
    state is in it (except a declared expansion against a complete frame),
    and a sentence giving different trades different places is never placed.

The property test generates the phrasings; each one may abstain, and none may
break the rule. 588: floors 1-4, mezzanine (at floor 4), roof; no cellar.
"""

from __future__ import annotations

import inspect
import itertools
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib import location_binder as B  # noqa: E402

F = ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF"]
NO_MEZZ = ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "ROOF"]
_TAKES_COMPLETE = "frame_complete" in inspect.signature(B.bind).parameters


def bind(text, levels=F, complete=True):
    kw = {"frame_complete": complete} if _TAKES_COMPLETE else {}
    return B.bind(text, levels, None, **kw)


def fl(*ns):
    return {f"FLOOR_{n}" for n in ns}


def ordn(n):
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n, 'th') }"


ES = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto"}
EN = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def _lists():
    """(text, stated, allowed extra)."""
    out = []
    for k in (2, 3, 4):
        for sub in itertools.combinations((1, 2, 3, 4), k):
            s = fl(*sub)
            for sep in (" ", ", ", ",", "/", " / ", " & ", "&", " and ", " + "):
                nums = sep.join(str(n) for n in sub)
                ords = sep.join(ordn(n) for n in sub)
                for t in (f"floors {nums}", f"fl {nums}", f"flrs {nums}", f"floor {nums}",
                          f"{ords} floor", f"{ords} floors", f"{ords} fl", f"floors {ords}"):
                    out.append((t, s, set()))
            head = ", ".join(str(n) for n in sub[:-1])
            out.append((f"pisos {head} y {sub[-1]}", s, set()))
            out.append((" y ".join(ES[n] for n in sub) + " piso", s, set()))
            out.append((", ".join(EN[n] for n in sub[:-1]) + f" and {EN[sub[-1]]} floor", s, set()))
    return out


def _ranges():
    out = []
    for lo, hi in itertools.combinations((1, 2, 3, 4), 2):
        s = fl(*range(lo, hi + 1))
        for c in (" to ", " thru ", " through ", "-", " - ", "–", " up to ", " until "):
            for t in (f"floors {lo}{c}{hi}", f"{ordn(lo)}{c}{ordn(hi)} floor", f"{ordn(lo)} floor{c}{ordn(hi)} floor",
                      f"{ordn(lo)} floor{c}{ordn(hi)}", f"fl {lo}{c}{hi}", f"from {ordn(lo)}{c}{ordn(hi)} floor"):
                out.append((t, s, set()))
        out += [(f"pisos {lo} al {hi}", s, set()), (f"del {ES[lo]} al {ES[hi]} piso", s, set()),
                (f"del {ES[lo]} piso al {ES[hi]}", s, set()), (f"pisos {lo} a {hi}", s, set())]
    return out


def _to_named():
    """A span to the roof: every floor from the start up, the roof, and the
    mezzanine as a declared expansion (it lies between)."""
    out = []
    for lo in (1, 2, 3, 4):
        s = fl(*range(lo, 5)) | {"ROOF"}
        for t in (f"{ordn(lo)} floor to roof", f"{ordn(lo)} floor thru roof", f"{ordn(lo)} fl through the roof",
                  f"roof to {ordn(lo)} floor", f"{ordn(lo)}-roof", f"{EN[lo]} floor through roof",
                  f"del {ES[lo]} piso al techo", f"floors {lo} to roof"):
            out.append((t, s, {"MEZZANINE"}))
    return out


def _open_ended():
    """"and up" states the floor and every one above; the roof and mezzanine
    may come with it as a frame expansion. "above" never states the floor itself."""
    out = []
    for n in (1, 2, 3, 4):
        up = fl(*range(n, 5))
        for t in (f"{ordn(n)} floor and up", f"{ordn(n)} floor & above", f"{ordn(n)} floor and above",
                  f"floors {n}+", f"{ordn(n)} floor up", f"{ordn(n)} floor and higher", f"{ES[n]} piso para arriba",
                  f"{ES[n]} piso y arriba"):
            out.append((t, up, {"MEZZANINE", "ROOF"}))
        above = fl(*range(n + 1, 5))
        for t in (f"above {ordn(n)} floor", f"above the {ordn(n)} floor", f"floors above {n}", f"over {ordn(n)} floor"):
            out.append((t, above, {"MEZZANINE", "ROOF"}))
    for t in ("upper floors", "lower floors", "top floor", "all upper levels"):
        out.append((t, None, set()))      # nothing stated: only an abstention is right
    return out


TRADES = ("Framers", "plumbers", "Electricians", "HVAC", "drywall crew")
PLACES = (("3rd floor", fl(3)), ("1st floor", fl(1)), ("3rd-4th floors", fl(3, 4)), ("1st & 2nd floor", fl(1, 2)),
          ("roof", {"ROOF"}), ("floors 1-4", fl(1, 2, 3, 4)))


def _mixed():
    out = []
    for (a, b) in itertools.permutations(TRADES[:3], 2):
        for (p, ps), (q, qs) in itertools.permutations(PLACES, 2):
            if ps == qs:
                continue
            for t in (f"{a} on the {p} and {b} on the {q}", f"{a} on {p} and {b} on {q}", f"{a} {p}, {b} {q}",
                      f"{a} {p} {b} {q}", f"{p} {a.lower()} and {q} {b.lower()}", f"{a} on {p}; {b} on {q}",
                      f"{a} {p} & {b} {q}", f"{a} on {p} while {b} on {q}", f"{a} {p}. {b} {q}"):
                out.append(t)
    return out


class TheRuleOnGeneratedPhrasings(unittest.TestCase):
    def _check(self, cases, levels=F, complete=True):
        bad = []
        for text, stated, extra in cases:
            r = bind(text, levels, complete)
            if r["certainty"] == B.NONE:
                continue
            got = set(r["levels"])
            if stated is None:
                bad.append((text, sorted(got), "placed with nothing stated"))
            elif got < stated or not stated <= got:
                bad.append((text, sorted(got), "strict subset / misses a stated floor"))
            elif got - stated - (extra if complete else set()):
                bad.append((text, sorted(got), "a level not stated"))
            elif got - stated and r["reason"] != getattr(B, "R_EXPANDED", "?"):
                bad.append((text, sorted(got), "an expansion not declared"))
        self.assertEqual(bad, [], f"{len(bad)} of {len(cases)}")

    def test_lists(self):
        self._check(_lists())

    def test_ranges(self):
        self._check(_ranges())

    def test_spans_to_a_named_level(self):
        self._check(_to_named())
        self._check(_to_named(), NO_MEZZ)
        self._check(_to_named(), complete=False)

    def test_open_ended(self):
        self._check(_open_ended())
        self._check(_open_ended(), NO_MEZZ)
        self._check(_open_ended(), complete=False)

    def test_mixed_trades_are_never_placed(self):
        cases = _mixed()
        placed = [(t, bind(t)["certainty"], bind(t)["levels"]) for t in cases if bind(t)["certainty"] != B.NONE]
        self.assertEqual(placed, [], f"{len(placed)} of {len(cases)}")

    def test_the_generator_is_not_trivial(self):
        """The rule allows abstaining, so a binder that abstains on everything
        passes it. Hold the plain phrasings to being answered."""
        for text, want in (("floors 2 3 4", fl(2, 3, 4)), ("floors 1, 2, 3", fl(1, 2, 3)), ("1st/2nd/3rd fl", fl(1, 2, 3)),
                           ("2nd & 4th floor", fl(2, 4)), ("floors 1 thru 3", fl(1, 2, 3)), ("3rd floor to 4th floor", fl(3, 4)),
                           ("pisos 2, 3 y 4", fl(2, 3, 4)), ("del primer al tercer piso", fl(1, 2, 3))):
            self.assertEqual(set(bind(text)["levels"]), want, text)
        lists = _lists()
        answered = sum(1 for t, s, _ in lists if set(bind(t)["levels"]) == s)
        self.assertGreater(answered, 0.8 * len(lists), f"{answered} of {len(lists)} lists answered")


class TheReviewStrings(unittest.TestCase):
    """adversarial_review_1.md C2, M10 and minor 9, verbatim."""

    def test_space_separated_numbers(self):
        for text, want in (("floors 2 3 4", fl(2, 3, 4)), ("floors 1 2 3", fl(1, 2, 3)), ("fl 2 3", fl(2, 3)),
                           ("floor 1 2", fl(1, 2)), ("pisos 2 3 4", fl(2, 3, 4))):
            r = bind(text)
            self.assertIn(set(r["levels"]) if r["certainty"] != B.NONE else None, (want, None), text)
            self.assertNotEqual(r["certainty"], B.EXACT, text)

    def test_spans_to_the_roof(self):
        for text in ("1st floor to roof", "1st floor thru roof", "roof to 1st floor", "fourth floor through roof",
                     "del segundo piso al techo", "3rd fl stair to roof", "1st-roof", "4th floor to mezzanine",
                     "4th thru mezz"):
            r = bind(text, complete=False)
            self.assertEqual(r["certainty"], B.NONE, text)

    def test_a_span_to_the_roof_on_a_complete_frame_is_declared(self):
        r = bind("1st floor to roof")
        self.assertEqual((r["levels"], r["reason"]), (F, B.R_EXPANDED))
        r = bind("2nd floor to roof", NO_MEZZ)
        self.assertEqual((r["levels"], r["reason"]), (["FLOOR_2", "FLOOR_3", "FLOOR_4", "ROOF"], B.R_EXPANDED))
        # Where 588's mezzanine sits is not in the frame: from the 2nd floor up it may or may not be included.
        self.assertEqual(bind("2nd floor to roof")["certainty"], B.NONE)
        # A span ending at the mezzanine: its place in the order is not known.
        self.assertEqual(bind("4th floor to mezzanine")["certainty"], B.NONE)

    def test_open_ended(self):
        for text in ("2nd floor and up", "2nd floor & above", "floors 2+", "above 2nd floor", "2nd floor up",
                     "upper floors", "top floor", "2nd to top floor"):
            self.assertEqual(bind(text, complete=False)["certainty"], B.NONE, text)
            self.assertNotIn("FLOOR_2", bind(text)["levels"] if text.startswith("above") else [], text)
        r = bind("2nd floor and up", NO_MEZZ)
        self.assertEqual((r["levels"], r["reason"]), (["FLOOR_2", "FLOOR_3", "FLOOR_4"], B.R_EXPANDED))
        r = bind("above 2nd floor", NO_MEZZ)
        self.assertEqual((r["levels"], r["reason"]), (["FLOOR_3", "FLOOR_4"], B.R_EXPANDED))
        self.assertEqual(bind("2nd floor and up")["certainty"], B.NONE)      # 588's mezzanine: not placed

    def test_mixed_trades_joined_by_and_or_juxtaposed(self):
        for text in ("Framers on 3rd floor and plumbers on 1st floor", "framing 3rd floor and plumbing 1st floor",
                     "Arkon 3rd floor and Quality 1st floor", "3rd floor framing and 1st floor plumbing",
                     "Framers 3rd floor plumbers 1st floor", "Electric on 2 and plumbing on 4"):
            r = bind(text)
            self.assertEqual((r["certainty"], r["levels"]), (B.NONE, []), text)

    def test_clauses_joined_by_and(self):
        got = [(c["levels"], c["certainty"]) for c in
               B.bind_clauses("Framers on 3rd floor and plumbers on 1st floor", {"levels": F})]
        self.assertEqual(got, [(["FLOOR_3"], B.EXACT), (["FLOOR_1"], B.EXACT)])
        # Juxtaposed with no joining word: which floor goes with which trade is not said.
        self.assertTrue(all(c["certainty"] == B.NONE
                            for c in B.bind_clauses("Framers 3rd floor plumbers 1st floor", {"levels": F})))

    def test_negation_and_relative_places(self):
        for text in ("floors 2-4 not 3", "floors 1 to 4 except roof", "under 2nd floor slab",
                     "underside of 3rd floor deck", "between 2nd and 3rd floor", "below 3rd floor",
                     "all floors except 2nd", "pisos 1 al 4 menos el 3"):
            self.assertEqual(bind(text)["certainty"], B.NONE, text)

    def test_and_between_two_floors_is_a_list_not_a_span(self):
        # progress_report.floors_in read "&" / "and" as a span: "floors 1 & 3"
        # was floors 1-3, a level the words do not state (found by the generator).
        from lib import progress_report as P
        self.assertEqual(P.floors_in("floors 1 & 3"), [1, 3])
        self.assertEqual(P.floors_in("floors 1 and 4"), [1, 4])
        self.assertEqual(P.floors_in("floors 1-4"), [1, 2, 3, 4])
        self.assertEqual(bind("floors 2 and 4")["levels"], ["FLOOR_2", "FLOOR_4"])

    def test_a_code_citation_is_not_a_floor(self):
        # 588 inspection line (label L0338): "BC 3301.13.13" is a section number.
        self.assertEqual(bind("2. General progress of work BC 3301.13.13 2 Floor in progress")["levels"], ["FLOOR_2"])

    def test_plain_ones_still_answer(self):
        for text, want in (("floors 1-4", F[:4]), ("3rd Floor, 4th Floor", ["FLOOR_3", "FLOOR_4"]), ("Roof", ["ROOF"]),
                           ("1 floor", ["FLOOR_1"]), ("floors 3-4 & roof", ["FLOOR_3", "FLOOR_4", "ROOF"]),
                           ("4th fl, mezz and roof", ["FLOOR_4", "MEZZANINE", "ROOF"]), ("2nd fl. bathroom", ["FLOOR_2"])):
            self.assertEqual(bind(text)["levels"], want, text)


if __name__ == "__main__":
    unittest.main()
