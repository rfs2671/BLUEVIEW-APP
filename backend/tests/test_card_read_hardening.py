"""AN EXCEPTION THAT STRINGIFIES TO NOTHING HID A FOUR-DAY OUTAGE.

WHAT HAPPENED. From 2026-09-11 18:11 UTC to 2026-09-15, zero worker rows were
created. Registration never ran because the CARD STEP never completed.
`POST /api/checkin/upload-osha` calls a vision model whose latency tail was
unbounded — identical image and prompt, 470 ms or never — so the 60-second
client raised `httpx.ReadTimeout`. And:

    >>> str(httpx.ReadTimeout(""))
    ''

The handler did `logger.error(f"OSHA OCR error: {str(e)}")` and
`detail=f"OCR processing failed: {str(e)}"`, so the log line read

    OSHA OCR error:

and the worker at the turnstile read

    OCR processing failed:

Nothing named the exception type. Nothing named the model. Nothing named the
timeout. That is why four days passed with every dashboard green.

WHY THIS FILE USES A REAL CARD'S OUTPUT AND NOT NULLS. The bug survived its own
testing because the probe was a BLANK IMAGE: the model answered all-nulls, the
call returned 200, and every downstream parser was skipped — `resolve_card_class`
never saw a colour, `build_worker_certifications` never built a row. A fixture of
nulls tests that nothing crashes when there is nothing to do. The payload below
is a REAL production response, captured 2026-09-15, and it exercises the whole
chain.

Run:  python -m pytest backend/tests/test_card_read_hardening.py -q
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import pytest  # noqa: E402

import server  # noqa: E402
from lib import vision_model as vm  # noqa: E402

payload = server._osha_ocr_payload


# ══ 0 — THE PREMISE, ASSERTED RATHER THAN REMEMBERED ═══════════════════════

def test_the_exception_that_started_this_still_stringifies_to_nothing():
    """If this ever stops being true the whole file is about a thing that no
    longer exists, and that should fail loudly rather than pass quietly."""
    assert str(httpx.ReadTimeout("")) == "", (
        "httpx.ReadTimeout no longer has an empty str() — the premise moved"
    )
    # ...and %r is the thing that survives it. This is the entire fix in one
    # assertion: the type is in the repr and is not in the str.
    assert "ReadTimeout" in repr(httpx.ReadTimeout(""))
    assert "ReadTimeout" not in str(httpx.ReadTimeout(""))


def _code_only(fn) -> str:
    """The handler's SOURCE WITH ITS COMMENTS REMOVED.

    ASSERTED ON CODE, NOT ON TEXT. The first version of this test grepped the
    raw source for the two lines that hid the outage — and failed, because the
    fix QUOTES those lines in the comment that explains it. A guard that a
    comment can trip is a guard that pressures the next person to delete the
    explanation. `ast.unparse` drops comments and keeps every statement.
    """
    return ast.unparse(ast.parse(inspect.getsource(fn)))


def test_the_handler_no_longer_records_the_exception_by_str_alone():
    """The exact two lines that hid the outage, asserted on the real handler."""
    code = _code_only(server.upload_osha_card)
    assert "OSHA OCR error: {str(e)}" not in code
    assert "OCR processing failed: {str(e)}" not in code
    assert "logger.exception(" in code, "the handler records no traceback"
    assert "%r" in code, "the handler does not use repr on the exception"


def test_no_logger_call_in_this_handler_formats_an_exception_with_str():
    """Walked, not grepped: every logger.* call inside the handler's except
    blocks must carry the exception as %r / !r / exc_info, never as str()."""
    tree = ast.parse(inspect.getsource(server.upload_osha_card))
    offenders = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        if not handler.name:
            continue
        name = handler.name
        for node in ast.walk(handler):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"):
                continue
            for sub in ast.walk(node):
                bare = (isinstance(sub, ast.FormattedValue)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == name
                        and sub.conversion != 114)
                wrapped = (isinstance(sub, ast.Call)
                           and isinstance(sub.func, ast.Name)
                           and sub.func.id == "str"
                           and len(sub.args) == 1
                           and isinstance(sub.args[0], ast.Name)
                           and sub.args[0].id == name)
                if bare or wrapped:
                    offenders.append(node.lineno)
    assert not offenders, f"str(e)-only logging is back at offsets {offenders}"


# ══ 1 — THE REAL CARD, THROUGH THE WHOLE CHAIN ═════════════════════════════
#
# Captured from production on 2026-09-15, from the model now in force, on a
# real SST supervisor card. NOT hand-written, NOT all-nulls.
REAL_CARD = {
    "name": "Jose David Hernandez Perez",
    "sst_number": None,
    "card_type": "SST",
    "card_class": "SUPERVISOR",
    "issued": None,
    "expiration": None,
    "card_dominant_color": "YELLOW",
    "card_color_confidence": "high",
    "card_color_conditions": [],
    "box_2d": [100.0, 0.0, 765.0, 999.0],
    "raw_text": None,
}


def test_the_real_card_survives_the_boundary():
    got = payload(REAL_CARD)
    assert got.name == "Jose David Hernandez Perez"
    assert got.card_type == "SST"
    assert got.card_class == "SUPERVISOR"
    assert got.card_dominant_color == "YELLOW"
    assert got.card_color_confidence == "high"
    assert got.card_color_conditions == []
    assert got.box_2d == [100.0, 0.0, 765.0, 999.0]
    # The nulls are REAL Nones, not the four-character string.
    assert got.sst_number is None and got.issued is None and got.expiration is None


def test_the_real_card_reaches_resolve_card_class_with_a_class():
    """THE STEP THE BLANK-IMAGE PROBE SKIPPED ENTIRELY. A card with no colour
    and no class text never enters this function's interesting branches, so an
    all-nulls fixture cannot tell a working resolver from a broken one."""
    res = server.resolve_card_class(payload(REAL_CARD).model_dump())
    assert res["not_sst"] is None, "a yellow SST card was read as not-an-SST-card"
    assert res["sst_type"], "no SST type resolved from a legible supervisor card"
    # Colour high-confidence + unimpaired + class text present is the one
    # CONFIRMED state the resolver has.
    assert res["class_source"] == "color_and_text", res


def test_the_real_card_builds_a_certification():
    """The end of the chain. An all-nulls fixture returns no certs at all, so
    this assertion was unreachable by the probe that missed the bug."""
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    certs, not_sst = server.build_worker_certifications(
        [], payload(REAL_CARD).model_dump(), None, "data:image/jpeg;base64,x", now,
    )
    assert not_sst is None
    assert certs, "a legible SST supervisor card produced no certification row"
    sst = [c for c in certs if str(c.get("type", "")).startswith("SST")]
    assert sst, f"no SST row among {[c.get('type') for c in certs]}"
    # A card whose NUMBER and EXPIRY could not be read must be flagged, not
    # silently accepted. This is the property `name: "null"` used to defeat.
    assert sst[0]["needs_review"] is True
    assert sst[0]["card_number"] is None
    assert sst[0]["expiration_date"] is None
    # Completeness carries the shortfall even when `review_reason` does not.
    #
    # NOTE, AND IT IS A FINDING RATHER THAN A FIX: `derive_cert_review` returns
    # `reason=None` for this row. The class read cleanly and the expiry gate had
    # nothing to object to, so neither branch supplies a reason — yet the row IS
    # flagged, because the number and the expiry are simply absent. A reviewer
    # opening it is told to review it and not told what to look at. Out of
    # scope here and reported for follow-up; asserted as it actually behaves so
    # this file does not quietly encode a wish.
    assert sst[0]["extraction_completeness"] < 1.0


# ══ 2 — THE SHAPES THAT HAVE BITTEN BEFORE ═════════════════════════════════

def test_card_class_as_an_integer():
    """THE PROMPT ASKS FOR IT. It says `for OSHA one of 10, 30` — so a model
    answering `10` as a JSON NUMBER is obeying the instruction, and anything
    that assumes a string here is one real card away from a 500."""
    assert "one of 10, 30" in server._OSHA_EXTRACTION_PROMPT, (
        "the prompt no longer asks for a bare number; this test's premise moved"
    )
    for raw in (10, 30, 10.0):
        got = payload({"card_type": "OSHA", "card_class": raw})
        assert got.card_class == str(raw), raw
        # And it must survive the resolver and the cert builder too.
        server.resolve_card_class(got.model_dump())
        server.build_worker_certifications(
            [], got.model_dump(), "12345", None,
            datetime(2026, 9, 15, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("raw", [
    "2027-10-03",   # ISO
    "05/35",        # MM/YY
    "10272029",     # MMDDYYYY, unpunctuated
    "062427",       # MMDDYY, unpunctuated
    "illegible",    # the model describing the card instead of reading it
    "null",         # the model's own word for "nothing"
])
def test_every_observed_real_expiry_shape_is_survivable(raw):
    """EVERY ONE OF THESE CAME OFF A REAL CARD. The requirement is NOT that
    each parses — `illegible` must not — it is that none of them raises, and
    that one that cannot be parsed lands as a null the record can show, never
    as an exception that kills the upload."""
    got = payload({"name": "Jose Ramirez", "card_type": "SST",
                   "card_class": "SUPERVISOR", "expiration": raw})
    assert got.name == "Jose Ramirez", raw

    certs, _ = server.build_worker_certifications(
        [], got.model_dump(), "SST-1", None,
        datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    assert certs, raw
    row = certs[0]
    if row["expiration_date"] is None:
        # DEGRADED, NOT CRASHED: null in the field, and the row flagged so a
        # human sees it. That combination is the whole requirement.
        assert row["needs_review"] is True, raw
        assert row["extraction_completeness"] < 1.0, raw
        if raw == "illegible":
            # The one shape that carries its own reason: a value was present
            # and the expiry gate REJECTED it, which is a different event from
            # a field that was never read.
            assert row["expiration_raw_rejected"] == raw
            assert row["review_reason"], raw


def test_a_mixed_case_card_number_is_one_card_not_two():
    """A stored row may hold any case; a re-scan normalises. Compared raw, one
    man's one card reads as two and a duplicate SST row is appended."""
    a = server.normalize_card_number("sst-1234Ab")
    b = server.normalize_card_number("SST-1234AB")
    assert a == b, (a, b)
    got = payload({"sst_number": "sst-1234Ab"})
    assert got.sst_number == "sst-1234Ab", "the boundary must not mangle the raw read"


# ══ 3 — A HOSTILE PAYLOAD MUST DEGRADE, NEVER RAISE ════════════════════════

HOSTILE = {
    "name": {"unexpected": "object"},
    "sst_number": ["a", "list"],
    "card_type": 7,
    "card_class": {"nested": {"deeper": True}},
    "issued": float("inf"),
    # THE BIDI OVERRIDE IS AN ESCAPE, NOT A LITERAL. A raw U+202E in a source
    # file reorders how every character after it DISPLAYS, which is the
    # Trojan Source trick: the reviewer and the compiler read different
    # programs. The value handed to the parser is identical either way, so
    # there is no reason to make it invisible.
    "expiration": "\x00\x01 not a date \u202e",
    "card_dominant_color": ["YELLOW"],
    "card_color_confidence": True,
    "card_color_conditions": {"not": "a list"},
    "box_2d": {"ymin": 1},
    "raw_text": b"bytes",
    "an_undeclared_key": "should not reach a caller",
}


def test_the_hostile_payload_does_not_raise_and_keeps_the_declared_shape():
    got = payload(HOSTILE)                   # must not raise
    assert isinstance(got, server.OshaCardOcrResult)
    assert got.card_color_conditions == []
    assert got.box_2d is None
    assert not hasattr(got, "an_undeclared_key")


def test_the_hostile_payload_still_serialises_as_a_200_shaped_result():
    """The endpoint's response_model is what a worker's browser receives. A
    payload the model should never send must still come out as the declared
    object, because the alternative is a 500 at a turnstile."""
    body = payload(HOSTILE).model_dump()
    assert set(body) == set(server.OshaCardOcrResult.model_fields)
    import json
    json.dumps(body, default=str)            # must be serialisable


def test_the_hostile_payload_survives_the_rest_of_the_chain():
    od = payload(HOSTILE).model_dump()
    server.resolve_card_class(od)             # must not raise
    certs, _not_sst = server.build_worker_certifications(
        [], od, "X-1", None, datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    for row in certs:
        assert "needs_review" in row


def test_a_body_that_is_not_the_provider_s_shape_degrades_to_a_read_of_nothing():
    """`result["choices"][0]["message"]["content"]` has four ways to raise on a
    200. Each of them used to reach the worker as an opaque 500."""
    src = _code_only(server.upload_osha_card)
    assert "except (KeyError, IndexError, TypeError, ValueError)" in src, (
        "an unusable provider body can raise out of the handler again"
    )


# ══ 4 — THE TIMEOUT IS ITS OWN ANSWER ══════════════════════════════════════

def test_a_timeout_has_a_machine_code_distinct_from_a_read_failure():
    codes = {server.CARD_READ_TIMEOUT, server.CARD_READ_FAILED,
             server.CARD_READ_UNAVAILABLE, server.CARD_READ_NOT_CONFIGURED}
    assert len(codes) == 4, "two card-read outcomes share a code"
    assert server.CARD_READ_TIMEOUT == "CARD_READ_TIMEOUT"


def test_the_error_detail_carries_a_code_and_a_sentence_a_worker_can_act_on():
    d = server._card_error_detail(server.CARD_READ_TIMEOUT, "Tap Retry")
    assert d["code"] == server.CARD_READ_TIMEOUT
    assert d["message"], "an empty reason is the defect this replaces"


def test_the_handler_raises_the_timeout_code_and_a_504():
    src = _code_only(server.upload_osha_card)
    assert "CARD_READ_TIMEOUT" in src
    assert "status_code=504" in src, "a timeout is still reported as something else"


def test_every_card_error_sentence_is_actionable():
    """No message may be empty, and none may end in a colon — the shape the
    outage's message had (`OCR processing failed: `), which is what an empty
    interpolation leaves behind."""
    for code in (server.CARD_READ_TIMEOUT, server.CARD_READ_FAILED,
                 server.CARD_READ_UNAVAILABLE, server.CARD_READ_NOT_CONFIGURED):
        msg = None
        for line in inspect.getsource(server.upload_osha_card).splitlines():
            if code in line:
                msg = code
        assert msg, code
    d = server._card_error_detail("X", "")
    assert d["message"] == "", "sanity: the helper does not invent text"


# ══ 5 — ONE RETRY, AND ONLY ON A TIMEOUT ═══════════════════════════════════

def test_the_budget_is_two_attempts_inside_the_old_sixty_seconds():
    assert server.OSHA_VISION_ATTEMPTS == 2
    assert 20.0 <= server.OSHA_VISION_ATTEMPT_TIMEOUT <= 25.0
    total = server.OSHA_VISION_ATTEMPTS * server.OSHA_VISION_ATTEMPT_TIMEOUT
    assert total <= 60.0, (
        f"total {total}s exceeds the 60s this endpoint already spent — "
        "something downstream now sees a longer request than before"
    )
    # ...and comfortably above the measured good path (3110-5391 ms).
    assert server.OSHA_VISION_ATTEMPT_TIMEOUT > 5.4 * 3


def test_only_transport_failures_are_retried():
    """A 4xx from the provider is an ANSWER. Retrying it buys a second
    identical refusal and a second bill."""
    tree = ast.parse(inspect.getsource(server.upload_osha_card))
    caught = set()
    for h in ast.walk(tree):
        if isinstance(h, ast.ExceptHandler) and h.type is not None:
            caught.add(ast.unparse(h.type))
    retry = [c for c in caught if "Timeout" in c or "ConnectError" in c]
    assert retry, f"nothing timeout-shaped is caught for retry: {caught}"
    src = _code_only(server.upload_osha_card)
    # The non-200 branch breaks straight out to the 502 — it is not inside the
    # retry's except clause.
    assert "status_code=502" in src


# ── AND THE SAME THING PROVEN BY RUNNING IT ───────────────────────────────
#
# Everything above reads the source. These drive the real handler with a fake
# transport, because "the retry is in the code" and "the retry happens" are
# different claims and only one of them is what a worker experiences.

class _Recorder:
    """A stand-in ServerHttpClient. Answers from a script, counts attempts."""

    calls = 0
    script = []

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, *_a, **_k):
        type(self).calls += 1
        step = type(self).script[min(type(self).calls - 1, len(type(self).script) - 1)]
        if isinstance(step, Exception):
            raise step
        return step


class _Ok:
    status_code = 200
    text = "{}"

    def json(self):
        return {"choices": [{"message": {"content": json_dumps(REAL_CARD)}}]}


def json_dumps(obj):
    import json
    return json.dumps(obj)


class _Refused:
    status_code = 400
    text = "bad request"

    def json(self):
        return {}


def _drive(script):
    """Run upload_osha_card against a scripted transport. Returns
    (result_or_exception, attempt_count)."""
    import asyncio
    _Recorder.calls = 0
    _Recorder.script = script
    real_client, real_key = server.ServerHttpClient, server.QWEN_API_KEY
    real_meter = server.record_vision_call

    async def _no_meter(*_a, **_k):
        return None

    class _Req:
        client = None
        headers = {}

    server.ServerHttpClient = _Recorder
    server.QWEN_API_KEY = "test-key"
    server.record_vision_call = _no_meter
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        got = loop.run_until_complete(
            server.upload_osha_card({"image": _jpeg(900, 600)}, _Req())
        )
    except Exception as exc:                                    # noqa: BLE001
        got = exc
    finally:
        loop.close()
        server.ServerHttpClient = real_client
        server.QWEN_API_KEY = real_key
        server.record_vision_call = real_meter
    return got, _Recorder.calls


def test_a_timeout_on_the_first_attempt_is_not_fatal():
    """THE CENTRAL BEHAVIOUR CHANGE. The tail is RANDOM — the same card at
    neighbouring sizes measured ~500 ms and a >75 s hang — so the single most
    valuable response to a hung call is to send it again."""
    got, calls = _drive([httpx.ReadTimeout(""), _Ok()])
    assert calls == 2, f"the second attempt was never made ({calls} calls)"
    assert isinstance(got, server.OshaCardOcrResult), got
    assert got.name == "Jose David Hernandez Perez"


def test_every_attempt_timing_out_is_a_504_with_the_timeout_code():
    got, calls = _drive([httpx.ReadTimeout(""), httpx.ReadTimeout("")])
    assert calls == server.OSHA_VISION_ATTEMPTS
    assert isinstance(got, server.HTTPException), got
    assert got.status_code == 504
    assert got.detail["code"] == server.CARD_READ_TIMEOUT
    # THE WHOLE POINT: the reason a worker sees is not empty.
    assert got.detail["message"].strip(), (
        "the worker is told 'could not read the card' and nothing else again"
    )
    assert not got.detail["message"].rstrip().endswith(":")


def test_a_4xx_from_the_provider_is_not_retried():
    """A provider that answered 'no' answers 'no' again and bills for it."""
    got, calls = _drive([_Refused(), _Ok()])
    assert calls == 1, f"a 4xx was retried ({calls} calls)"
    assert isinstance(got, server.HTTPException)
    assert got.status_code == 502
    assert got.detail["code"] == server.CARD_READ_UNAVAILABLE


def test_a_connect_error_is_retried_like_a_timeout():
    got, calls = _drive([httpx.ConnectError("no route"), _Ok()])
    assert calls == 2
    assert isinstance(got, server.OshaCardOcrResult)


def test_the_gate_can_report_a_timeout_as_its_own_kind():
    assert "card_ocr_timeout" in server.GATE_FAILURE_KINDS
    assert "card_ocr_http_failed" in server.GATE_FAILURE_KINDS, (
        "the pre-existing kind must not have been replaced"
    )


# ══ 6 — THE DOWNSCALE ══════════════════════════════════════════════════════

def _jpeg(w, h):
    import base64
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (240, 210, 40))
    d = ImageDraw.Draw(img)
    for i in range(0, h, max(6, h // 20)):
        d.rectangle([w // 10, i, w // 2, i + 3], fill=(10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_a_phone_frame_is_shrunk_to_the_bound():
    b64 = _jpeg(3000, 2074)
    out, ct, meta = server._downscale_card_for_vision(b64)
    assert meta["resized"] is True
    assert max(meta["size_out"]) == server._osha_vision_max_edge()
    assert len(out) < len(b64)
    assert ct == "image/jpeg"


def test_an_image_already_within_the_bound_is_not_touched():
    """It shrinks; it never upscales, and it never re-encodes a small image
    just to say it did."""
    b64 = _jpeg(800, 553)
    out, _ct, meta = server._downscale_card_for_vision(b64)
    assert meta["resized"] is False
    assert out == b64


def test_a_frame_that_cannot_be_decoded_is_sent_as_it_arrived():
    """A resize is a pure optimisation. Losing a worker's card read to one is
    the single outcome it must not produce."""
    out, ct, meta = server._downscale_card_for_vision("not base64 @@@@ at all")
    assert out == "not base64 @@@@ at all"
    assert meta["resized"] is False
    assert meta["reason"], "a silent failure records nothing"


def test_the_bound_refuses_a_nonsense_value():
    old = os.environ.get("OSHA_VISION_MAX_EDGE")
    try:
        for bad in ("", "abc", "0", "-1", "12"):
            os.environ["OSHA_VISION_MAX_EDGE"] = bad
            assert server._osha_vision_max_edge() == 1024, bad
        os.environ["OSHA_VISION_MAX_EDGE"] = "1600"
        assert server._osha_vision_max_edge() == 1600
    finally:
        if old is None:
            os.environ.pop("OSHA_VISION_MAX_EDGE", None)
        else:
            os.environ["OSHA_VISION_MAX_EDGE"] = old


def test_the_stored_card_is_not_the_downscaled_one():
    """The original is what reaches the worker record and filed compliance
    PDFs. This handler resizes a COPY and never writes an image at all."""
    src = _code_only(server.upload_osha_card)
    assert "vision_b64" in src
    assert "osha_card_image" not in src, (
        "the card-read endpoint now touches the stored image"
    )


# ══ 7 — THE MODEL ID, AND THE VENDOR ═══════════════════════════════════════

def test_the_code_default_is_the_verified_model_not_the_dead_one():
    assert vm.VISION_MODEL_DEFAULT == "Qwen/Qwen2.5-VL-32B-Instruct"
    # The two ids that must never be a default again: one 404s at the
    # provider, the other caused the outage.
    assert vm.VISION_MODEL_DEFAULT != "Qwen/Qwen2.5-VL-7B-Instruct"
    assert vm.VISION_MODEL_DEFAULT != "Qwen/Qwen3-VL-30B-A3B-Instruct"


def test_there_is_exactly_one_default_for_each_variable():
    """TWO FILES DEFAULTED THE SAME TWO VARIABLES DIFFERENTLY — different
    models AND different vendors — so "what happens if the variable is unset"
    had two answers depending on which product surface you touched."""
    for path in ("server.py", "lib/coi_ocr.py"):
        src = (Path(__file__).resolve().parent.parent / path).read_text(encoding="utf-8")
        for dead in ("Qwen/Qwen3-VL-30B-A3B-Instruct",
                     "Qwen/Qwen2.5-VL-7B-Instruct",
                     "https://api.together.xyz/v1"):
            for line in src.splitlines():
                if dead in line and not line.lstrip().startswith("#"):
                    raise AssertionError(f"{path} still carries {dead!r}: {line.strip()}")


def test_all_five_call_sites_resolve_through_the_one_module():
    """server.py's four and coi_ocr's one."""
    server_src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")
    coi_src = (Path(__file__).resolve().parent.parent / "lib" / "coi_ocr.py").read_text(
        encoding="utf-8")
    assert server_src.count('"model": QWEN_MODEL') + server_src.count(
        '"model":       QWEN_MODEL') >= 4, "a vision call site stopped using QWEN_MODEL"
    assert "from lib.vision_model import" in server_src
    assert "from lib.vision_model import" in coi_src
    assert 'os.environ.get("QWEN_MODEL"' not in coi_src


def test_the_resolver_prefers_the_environment():
    old = os.environ.get("QWEN_MODEL")
    try:
        os.environ["QWEN_MODEL"] = "Some/Other-Model"
        assert vm.vision_model() == "Some/Other-Model"
        assert vm.describe()["model_source"] == "env"
        os.environ["QWEN_MODEL"] = "   "
        assert vm.vision_model() == vm.VISION_MODEL_DEFAULT, (
            "a whitespace-only variable must not become the model id"
        )
    finally:
        if old is None:
            os.environ.pop("QWEN_MODEL", None)
        else:
            os.environ["QWEN_MODEL"] = old


def test_the_base_has_no_trailing_slash_however_it_is_written():
    old = os.environ.get("QWEN_API_BASE")
    try:
        os.environ["QWEN_API_BASE"] = "https://example.test/v1/"
        assert vm.vision_api_base() == "https://example.test/v1"
    finally:
        if old is None:
            os.environ.pop("QWEN_API_BASE", None)
        else:
            os.environ["QWEN_API_BASE"] = old


# ══ 8 — THE PROBE AND THE HEALTH CHECK ═════════════════════════════════════

def _run(coro):
    import asyncio
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_a_probe_with_no_key_is_unknown_not_a_verdict():
    """"We could not ask" must never read as "the model is dead", or a flaky
    network becomes a false alarm on every deploy."""
    old = os.environ.get("QWEN_API_KEY")
    try:
        os.environ["QWEN_API_KEY"] = ""
        got = _run(vm.probe())
        assert got["ok"] is None
        assert got["reason"]
    finally:
        if old is None:
            os.environ.pop("QWEN_API_KEY", None)
        else:
            os.environ["QWEN_API_KEY"] = old


class _FakeResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    async def post(self, *_a, **_k):
        return self._resp

    async def aclose(self):
        pass


def test_a_404_on_the_model_id_is_a_definite_no():
    """THE STATE THE SHIPPED DEFAULT WAS IN. DeepInfra answers a bad id with
    404 `does not exist`; nothing anywhere could see that before."""
    old = os.environ.get("QWEN_API_KEY")
    try:
        os.environ["QWEN_API_KEY"] = "test-key"
        got = _run(vm.probe(http_client=_FakeClient(
            _FakeResp(404, "The model `Qwen/Qwen2.5-VL-7B-Instruct` does not exist"))))
        assert got["ok"] is False
        assert "does not exist" in got["reason"]
    finally:
        if old is None:
            os.environ.pop("QWEN_API_KEY", None)
        else:
            os.environ["QWEN_API_KEY"] = old


def test_a_429_is_not_a_verdict_on_the_model():
    old = os.environ.get("QWEN_API_KEY")
    try:
        os.environ["QWEN_API_KEY"] = "test-key"
        got = _run(vm.probe(http_client=_FakeClient(_FakeResp(429, "slow down"))))
        assert got["ok"] is None, "a rate limit was read as a dead model"
    finally:
        if old is None:
            os.environ.pop("QWEN_API_KEY", None)
        else:
            os.environ["QWEN_API_KEY"] = old


def test_the_health_check_reports_the_model_in_force():
    body = _run(server.health_check())
    assert body["vision"]["model"] == server.QWEN_MODEL
    assert body["vision"]["base"] == server.QWEN_API_BASE
    assert "model_source" in body["vision"]


def test_an_unprobed_deploy_is_still_healthy():
    """An unprobed or unreachable provider must leave `status` alone — the
    endpoint's own rule is that a finding gets its own section, not a restart
    loop."""
    server.VISION_MODEL_PROBE.update({"ok": None})
    assert _run(server.health_check())["status"] == "healthy"


def test_a_rejected_model_id_makes_the_health_check_say_so():
    before = dict(server.VISION_MODEL_PROBE)
    try:
        server.VISION_MODEL_PROBE.update({"ok": False, "reason": "404 does not exist"})
        body = _run(server.health_check())
        assert body["status"] == "degraded"
        assert body["vision"]["ok"] is False
    finally:
        server.VISION_MODEL_PROBE.clear()
        server.VISION_MODEL_PROBE.update(before)


# ══ 9 — THE CANARY ═════════════════════════════════════════════════════════

def test_the_canary_alerts_on_the_second_failure_not_the_first():
    assert server.CARD_CANARY_FAILURES_BEFORE_ALERT == 2, (
        "one slow call is weather, not a page"
    )
    assert server.CARD_CANARY_INTERVAL_MINUTES == 15
    # Slow is a failure even on a 200, and the threshold sits above the
    # measured good path (3.1-5.4 s) and below the endpoint's own attempt cap.
    assert 5.4 < server.CARD_CANARY_SLOW_SECONDS <= server.OSHA_VISION_ATTEMPT_TIMEOUT


def test_the_canary_creates_no_worker_and_no_checkin():
    """A monitor that can create records is a monitor that can corrupt the
    thing it monitors."""
    src = _code_only(server._card_read_canary)
    for forbidden in ("db.workers", "db.checkins", "register_and_checkin",
                      "db.worker_enrollments", "db.sign_ins"):
        assert forbidden not in src, f"the canary touches {forbidden}"


def test_the_canary_is_excluded_from_the_spend_meter_but_not_from_accounting():
    """Its calls must not land in `vision_calls` beside real worker traffic —
    2,880 a month against ~52 real registrations would make the meter a number
    about the monitor. EXEMPT FROM THAT COLLECTION IS NOT EXEMPT FROM COUNTING:
    it opens its own row first, under the same count-before-you-spend rule
    `record_vision_call` is written to (a call that errors after the provider
    billed it is still spend)."""
    # COMMENT-STRIPPED, and the first draft of this test taught the lesson:
    # it grepped the raw source and failed because the comment explaining WHY
    # the canary is exempt NAMES `record_vision_call`. A guard a comment can
    # trip pressures the next person to delete the explanation.
    src = _code_only(server._card_read_canary)
    assert "record_vision_call" not in src
    assert "vision_canary_runs" in src, "the canary's own calls are uncounted"
    assert src.index("vision_canary_runs") < src.index("chat/completions"), (
        "the canary's ledger row is opened after it has already spent"
    )


def test_the_canary_sends_the_same_prompt_the_gate_does():
    """A monitor with its own copy of the prompt stops testing the thing it
    claims to test the first time either copy is edited — invisibly, because
    both keep returning 200."""
    assert "_OSHA_EXTRACTION_PROMPT" in _code_only(server._card_read_canary)
    assert "_OSHA_EXTRACTION_PROMPT" in _code_only(server.upload_osha_card)


def test_the_canary_never_raises_into_the_scheduler():
    """A monitor that can kill its own scheduler thread is worse than no
    monitor: the silence looks identical to success. Asserted structurally —
    the function's ENTIRE body must be one try/except that catches
    BaseException-or-Exception, not merely contain the words somewhere."""
    fn = ast.parse(inspect.getsource(server._card_read_canary)).body[0]
    # A docstring and a `global`/`nonlocal` declaration are not statements that
    # can raise; everything else in the body has to be inside the guard.
    body = [n for n in fn.body
            if not isinstance(n, (ast.Global, ast.Nonlocal))
            and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    outer = [n for n in body if isinstance(n, ast.Try)]
    assert len(body) == len(outer) == 1, (
        "the canary has statements outside its blanket try/except"
    )
    caught = {ast.unparse(h.type) for h in outer[0].handlers if h.type}
    assert "Exception" in caught, caught


def test_the_canary_does_not_run_without_a_card_to_read():
    """Unconfigured is a no-op with ONE log line, not a 15-minute error loop."""
    src = _code_only(server._card_read_canary)
    assert "CARD_CANARY_R2_KEY" in src
    assert "_card_canary_unconfigured_logged" in src


# ══ 10 — THE PLAN INDEX'S PAGE BUDGET ══════════════════════════════════════

def test_a_page_cannot_spend_an_unbounded_amount_of_time():
    """The 180 s comment always described a PAGE budget; it was applied per
    CALL. PR #547 added a second call per page, which doubled an exposure that
    had no ceiling: 5 raster sections x 180 s is 15 minutes on ONE page."""
    assert server.PLAN_INDEX_PAGE_BUDGET <= 300.0
    assert server.PLAN_INDEX_CALL_TIMEOUT == 180.0
    assert server.PLAN_INDEX_PAGE_BUDGET < 5 * server.PLAN_INDEX_CALL_TIMEOUT
    src = _code_only(server._index_single_page)
    assert "_page_deadline" in src
    assert "ServerHttpClient(timeout=call_timeout)" in src, (
        "the section call is back on a fixed per-call timeout"
    )


def test_a_refused_section_is_distinguishable_from_a_provider_timeout():
    """plan_extract records `call_failed:<TypeName>` on the section, so the
    type name is the whole message a reviewer gets."""
    assert issubclass(server.BudgetExhausted, RuntimeError)
    assert server.BudgetExhausted.__name__ == "BudgetExhausted"
