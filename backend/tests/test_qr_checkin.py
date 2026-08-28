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
VERCEL = code_of("frontend/vercel.json")


class TestTheQrRegistersNothing(unittest.TestCase):
    """The CP creates no tag, and could not if it tried.

    POST /api/projects/{id}/nfc-tags is Depends(get_admin_user) — admin or
    owner. A "virtual tag" design would put a call the CP's role cannot make
    on the critical path of a man standing at a gate, and would need a network
    round-trip on a site that usually has none. The QR encodes the row the
    physical tag already has instead.
    """

    def test_the_modal_writes_nothing(self):
        for forbidden in ("addNfcTag", "POST", "apiClient", "projectsAPI"):
            self.assertNotIn(
                forbidden, QR_MODAL,
                f"CheckinQrModal must not call the API ({forbidden}): it renders "
                "a URL from the already-cached project and registers nothing.",
            )

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
        self.assertIn("project?.nfc_tags", QR_MODAL)
        self.assertIn("nfc_tags: List[Dict] = []", SERVER)


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
    """_layout.jsx routes role 'cp' to /logbooks, and the NFC tag section on
    the admin project screen is behind `isAdmin`. So the CP's entry point has
    to be on their own home screen or it does not exist for them at all.
    """

    def test_the_entry_point_is_on_the_cp_home_screen(self):
        self.assertIn("CheckinQrModal", CP_HOME)
        self.assertIn("setShowCheckinQr(true)", CP_HOME)

    def test_it_is_not_gated_on_a_count(self):
        # The CP finds out the phone will not tap while the man is already at
        # the gate. A control that appears only once something is wrong is not
        # available at the moment it is needed.
        self.assertIn("{selectedProject && (", CP_HOME)
        self.assertNotIn("flagged.count > 0 && showCheckinQr", CP_HOME)


if __name__ == "__main__":
    unittest.main()
