"""Does WeasyPrint render HERE? For tests whose subject is a rendered PDF.

WeasyPrint imports its native libraries (GTK: gobject, pango, cairo) at import
time. Without them -- a Windows laptop with no GTK runtime -- `import
weasyprint` raises OSError, not ImportError, so `pytest.importorskip` and an
`except ImportError` both let it through as an error.

THE SKIP IS GUARDED, as in test_report_cover_is_not_blank.py: off CI a missing
GTK skips with the reason; under CI it does NOT skip, because production
renders every report with WeasyPrint and the image installs GTK, so a CI
runner without it is a broken runner, not an excuse.
"""

from __future__ import annotations

import os

try:
    import weasyprint as _weasyprint  # noqa: F401
    WEASYPRINT_ERROR = None
except Exception as exc:  # OSError when GTK is missing; ImportError when not installed
    WEASYPRINT_ERROR = f"{type(exc).__name__}: {exc}"[:200]

#: True only off CI, and only when WeasyPrint cannot load.
SKIP = WEASYPRINT_ERROR is not None and not os.environ.get("CI")
REASON = f"WeasyPrint native libraries unavailable here ({WEASYPRINT_ERROR})"
