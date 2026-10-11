"""Unpadded dates on every platform.

`strftime("%-d")` / `"%-I"` are glibc extensions: on Windows they raise
ValueError ("Invalid format string"), so a dry run on a laptop crashed
where Railway (Linux) did not. `strftime(dt, "%b %-d, %-I:%M %p")` reads
the same format and writes "Oct 9, 3:12 PM" anywhere: each "%-X" is the
padded "%X" with its zeros taken off, before strftime ever sees it.
"""

from __future__ import annotations

import re
from typing import Any

#: The codes "%-" works with: day, month, hour (24 / 12), minute, second,
#: day of year, 2-digit year.
_UNPADDED = re.compile(r"(?<!%)%-([dmHIMSjy])")


def strftime(dt: Any, fmt: str) -> str:
    """dt.strftime(fmt), with "%-d" / "%-I" / … done here, not by the C library."""
    return dt.strftime(_UNPADDED.sub(lambda m: str(int(dt.strftime("%" + m.group(1)))), fmt))
