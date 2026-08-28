"""QR check-in — the invariants that hold the QR and the NFC tag together.

A worker whose phone has no NFC radio checks in by scanning a code the CP
holds up. It is the SAME gate as the tag on the post: same nfc_tags row, same
project, same check-in record. That equivalence is the whole design, and every
assertion here is one of the ways it silently stops being true.

WHY STATIC ASSERTIONS. Two of the three files are not Python — checkin.html's
inline script and the CP's JSX — and the third, register_and_checkin, is a
1000-line endpoint that needs a live Mongo to call. The executable half of
this (the URL builder itself) is tested where it lives, under bare node:
frontend/src/utils/nfcHelper.buildCheckinUrl.test.cjs. What is pinned here is
the wiring between the three, which nothing else can see at once.

Run:  pytest tests/test_qr_checkin.py
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from tests.source_text import code_of  # noqa: E402

SERVER = code_of("server.py")
GATE = code_of("checkin.html")
NFC_HELPER = code_of("frontend/src/utils/nfcHelper.js")
QR_MODAL = code_of("frontend/src/components/CheckinQrModal.jsx")
CP_HOME = code_of("frontend/app/logbooks/index.jsx")
CP_NAV = code_of("frontend/src/components/CpNav.js")
VERCEL = code_of("frontend/vercel.json")


class TestTheQrRegistersNothing(unittest.TestCase):
    """SHOWING a code creates nothing, and needs no network.

    NARROWED, NOT WEAKENED. This class used to assert the modal made no API
    call of any kind. That stopped being true when the CP gained the power to
    MINT a gate on a project that has none — an explicit action behind its own
    button, on the one screen where the alternative is a shift with no 3301.11
    record at all.

    What must not come back is the "virtual tag" design: a write on the path of
    simply displaying a code. That would need a round-trip on a site with no
    signal, to show a QR for a gate that already exists — and it would put a
    call the CP's role cannot make (POST /nfc-tags is Depends(get_admin_user))
    on the critical path of a man standing at a gate.

    So the rule is now about WHICH call and WHERE, and the assertions say so.
    """

    def test_the_modal_never_calls_the_admin_tag_endpoint(self):
        # The "virtual tag" design, by name. The CP's role cannot call it.
        self.assertNotIn("addNfcTag(", QR_MODAL)
        self.assertNotIn("/nfc-tags", QR_MODAL)

    def test_the_only_write_is_the_explicit_bootstrap(self):
        calls = set(re.findall(r"projectsAPI\.(\w+)", QR_MODAL))
        self.assertEqual(
            calls, {"bootstrapCheckinPoint"},
            f"the QR screen may make exactly one API call, the one behind the "
            f"create button; found {sorted(calls)}",
        )

    def test_rendering_a_code_does_not_touch_the_network(self):
        # NARROWED. This used to ban useEffect outright, which was a proxy for
        # "nothing fires on open". The modal now HAS an effect — it resolves
        # its own project when opened from the nav — so the proxy is wrong and
        # the real rule has to be stated: the effect may read the CACHE, and
        # only the create button may reach the network. A QR for an existing
        # gate still has to draw with no signal.
        self.assertIn("const createPoint = async () =>", QR_MODAL)
        effect = QR_MODAL[QR_MODAL.index("useEffect("):]
        effect = effect[:effect.index("}, [visible, project, user]);")]
        self.assertIn("readCachedProjectList()", effect)
        self.assertNotIn(
            "projectsAPI.", effect,
            "the open effect may read the cache, never the network",
        )

    def test_the_caller_never_supplies_an_id(self):
        # The server mints it. A screen that SENT one could collide with a
        # hardware UID or with another project's tag. Reading tag_id back off
        # the response is the opposite of that and is required — the minted
        # gate has to render immediately, before any refetch.
        self.assertIn("bootstrapCheckinPoint(projectId, {})", QR_MODAL,
                      "the request body must be empty")
        self.assertIn("res.tag_id", QR_MODAL,
                      "the id must come back FROM the server")

    def test_the_tag_creation_endpoint_is_still_admin_only(self):
        # If this ever loosens, the "registers nothing" design above stops
        # being forced by the auth model and becomes a convention someone can
        # quietly walk back.
        self.assertRegex(
            SERVER,
            r'@api_router\.post\("/projects/\{project_id\}/nfc-tags".*?\n'
            r"async def add_nfc_tag_to_project\(.*?admin = Depends\(get_admin_user\)",
            "add_nfc_tag_to_project must stay admin-gated",
        )

    def test_the_modal_reads_the_tags_off_the_project(self):
        # nfc_tags rides on ProjectResponse and is cached to AsyncStorage by
        # projectCache.js, which is what lets the code render with no signal.
        # Read off the RESOLVED project (a passed one, or the one this modal
        # picked from the cache), not off the prop.
        self.assertIn("activeProject?.nfc_tags", QR_MODAL)
        self.assertIn("nfc_tags: List[Dict] = []", SERVER)

    def test_the_modal_resolves_its_own_project(self):
        # It opens from CpNav, which is on every CP screen. /settings has no
        # project state at all and /documents filters its list to
        # Dropbox-enabled projects, so a host-supplied project would be absent
        # on one screen and wrong on another.
        self.assertIn("readCachedProjectList", QR_MODAL)
        self.assertIn("assigned_projects", QR_MODAL,
                      "a CP must not be shown a code for a site they are not on")
        self.assertIn("const activeProject = project || pickedProject;", QR_MODAL,
                      "a host may still pass a project; it just is not required")


class TestOneHost(unittest.TestCase):
    """The tag host and the QR host cannot be allowed to drift apart.

    They are different hosts serving the SAME gate — vercel.json rewrites
    /checkin/* and /api/* from levelog.com to api.levelog.com — so a QR built
    on the wrong one still works, still returns 200 and still logs nothing.
    Only the localStorage origin differs, and the cost lands on a worker
    re-doing his orientation at a turnstile.
    """

    def test_the_gate_host_is_declared_once(self):
        self.assertIn("export const CHECKIN_BASE_URL = 'https://levelog.com';", NFC_HELPER)
        literals = re.findall(r"'https://(?:www\.)?levelog\.com'", NFC_HELPER)
        self.assertEqual(
            len(literals), 1,
            f"the gate host must appear as a literal exactly once, found {len(literals)}",
        )

    def test_the_qr_resolves_the_host_through_the_shared_builder(self):
        self.assertIn("buildCheckinUrl", QR_MODAL)
        # Both literals are anchored on purpose: a bare "levelog" would also be
        # satisfied by a longer identifier that merely contains it, which is
        # the failure mode test_absence_literals_are_specific.py exists to stop.
        self.assertNotIn("levelog.com", QR_MODAL, "the QR must not name a host of its own")
        self.assertNotIn(
            "process.env.EXPO_PUBLIC_API_URL", QR_MODAL,
            "the QR must never be built from the API base — that is the drift",
        )

    def test_the_nfc_writers_use_the_same_builder(self):
        # Two writers plus the QR, one path shape. The /checkin/{p}/{t} literal
        # belongs in buildCheckinUrl and nowhere else in this file.
        shapes = re.findall(r"/checkin/\$\{projectId\}/\$\{tagId\}", NFC_HELPER)
        self.assertEqual(len(shapes), 1, f"expected one URL shape, found {len(shapes)}")
        calls = re.findall(r"=\s*buildCheckinUrl\(projectId, tagId", NFC_HELPER)
        self.assertEqual(
            len(calls), 2,
            f"writeNfcTag and registerNfcTag must both go through the builder, found {len(calls)}",
        )

    def test_the_rewrite_that_makes_both_hosts_work_is_still_there(self):
        # This is the reason the drift is silent rather than loud. If it ever
        # goes away the failure mode changes completely, and the comments on
        # CHECKIN_BASE_URL stop describing reality.
        self.assertIn('"source": "/checkin/:path*"', VERCEL)
        self.assertIn('"destination": "https://api.levelog.com/checkin/:path*"', VERCEL)


class TestTheMethodMarker(unittest.TestCase):
    """?m=qr, and the one rule that keeps it honest: absent means tapped.

    Every tag already programmed into the field sends no marker, and an NDEF
    write cannot be taken back. So the default is not a style choice — it is
    the only value that leaves the tags on the posts today reading correctly.
    """

    def test_the_gate_parses_the_marker(self):
        self.assertIn("checkinMethod = _m === 'qr' ? 'qr' : 'nfc';", GATE)
        self.assertIn("let checkinMethod = 'nfc';", GATE)

    def test_the_gate_forwards_it_on_both_register_paths(self):
        # New worker AND returning worker. Missing the second would make every
        # returning QR user silently read as a tap.
        self.assertEqual(
            GATE.count("checkin_method: checkinMethod,"), 2,
            "both register-and-checkin calls must forward the method",
        )

    def test_the_server_closes_the_field_to_two_values(self):
        self.assertIn(
            'checkin_method = "qr" if str(data.get("checkin_method") or "")'
            '.strip().lower() == "qr" else "nfc"',
            SERVER,
        )

    def test_the_server_freezes_it_onto_the_checkin_row(self):
        # Frozen like sst_status and the OCR telemetry beside it: nfc_tags rows
        # are mutable and soft-deletable, a check-in is the durable artifact.
        self.assertIn('"checkin_method": checkin_method,', SERVER)

    def test_the_marker_cannot_reach_the_gates_path_parser(self):
        # checkin.html slices path segments after "checkin" into
        # [project_id, tag_id]. A marker in the path would be read as a tag id.
        self.assertIn("?m=qr", NFC_HELPER)
        self.assertNotIn("/m=qr", NFC_HELPER)
        self.assertIn("method === 'qr' ? `${url}?m=qr` : url", NFC_HELPER)


class TestTheMarkerIsEvidenceAndNotAGate(unittest.TestCase):
    """A QR check-in is never refused for being a QR check-in.

    A code can be photographed and used off-site where a tap cannot. That is a
    real exposure and the marker is what makes it queryable after the fact —
    but this codebase has twice refused to let a control stop a man working
    (the removed per-IP rate limit; needs_trade_assignment admitting and
    flagging), and this must not become the exception.
    """

    def test_no_branch_raises_on_the_method(self):
        window = SERVER[SERVER.index("checkin_method = "):]
        window = window[:window.index('"checkin_method": checkin_method,')]
        for line in window.splitlines():
            if "checkin_method" in line and ("raise " in line or "HTTPException" in line):
                self.fail(f"checkin_method must never gate a check-in: {line.strip()}")


class TestTheCpCanReachIt(unittest.TestCase):
    """The entry point is the NAV, and only the nav.

    It lived on the CP's home screen as a card in the log-book list, which put
    a tool he reaches for AT A GATE inside a screen he reads at a desk. CpNav
    is the one surface present on every CP screen, so that is where it belongs.
    """

    def test_the_entry_point_is_in_the_nav(self):
        self.assertIn("CheckinQrModal", CP_NAV)
        self.assertIn("setShowCheckinQr(true)", CP_NAV)

    def test_it_is_not_also_on_the_home_screen(self):
        # TWO ENTRY POINTS TO ONE SHEET IS HOW THEY DRIFT. The home screen may
        # still mention the move in a comment, so this reads code only.
        # Anchored: a bare identifier would be satisfied or broken by anything
        # containing it, which is what test_absence_literals_are_specific bans.
        self.assertNotIn("components/CheckinQrModal", CP_HOME, "no import")
        self.assertNotIn("<CheckinQrModal", CP_HOME, "no render")
        self.assertNotIn("setShowCheckinQr(", CP_HOME, "no opener")

    def test_it_is_unconditional(self):
        # The CP finds out the phone will not tap while the man is already at
        # the gate. A control that appears only once something is wrong is not
        # available at the moment it is needed — so the nav item carries no
        # condition at all.
        items = CP_NAV[CP_NAV.index("const CP_NAV_ITEMS = ["):]
        items = items[:items.index("];")]
        self.assertIn("CHECKIN_QR_ACTION", items)
        self.assertNotIn("&&", items, "the nav item must not be conditional")

    def test_it_opens_in_place_rather_than_navigating(self):
        # A tool used for fifteen seconds at a gate must not take the CP off
        # whatever he was doing and make him find his way back.
        self.assertIn("const CHECKIN_QR_ACTION = '#checkin-qr';", CP_NAV)
        self.assertIn("item.path === CHECKIN_QR_ACTION", CP_NAV)


class TestTheNavHeightStaysDecoupled(unittest.TestCase):
    """`numberOfLines={1}` on the nav label is load-bearing, not tidiness.

    CpNav is `width: '100%'` with `navItem: flex: 1`, so items SHARE the width
    and every added item leaves each label less room. Without numberOfLines a
    squeezed label wraps, the item grows taller and the pill grows with it —
    and three CP screens clear this nav with a HARDCODED paddingBottom (120 on
    /logbooks and /documents, 140 on /settings) sized by hand against the pill
    as it was. A taller pill eats that clearance and covers the last row.

    Measured on the real component at three items:

        375pt, "Check-In QR"                    pill 58
        320pt, "Check-In QR"                    pill 70   <- wrapped
        320pt, "Check-In QR" + numberOfLines    pill 58   <- ellipsis

    The short label is not what makes it safe: at 320pt "Dashboard" — already
    there before this change — has ONE POINT of headroom, so the nav is a
    single font-scale step from growing whatever the new item is called.
    """

    def test_the_nav_label_is_single_line(self):
        self.assertIn("numberOfLines={1}", CP_NAV,
                      "removing this recouples the pill height to label length, "
                      "and every CP screen's bottom clearance moves with it")

    def test_the_reason_is_written_down(self):
        # The DECISION alone reads as noise to whoever adds a fourth item.
        raw = code_of("frontend/src/components/CpNav.js", raw=True)
        self.assertIn("DECOUPLED FROM ITEM COUNT ON PURPOSE", raw)
        self.assertIn("pill 70", raw, "the measurement, not just the claim")


if __name__ == "__main__":
    unittest.main()
