"""Send INFO/DEBUG log lines to stdout and WARNING+ to stderr.

Railway marks every line that arrives on stderr as severity "error".
Python's logging.basicConfig and uvicorn's "default" handler both write
to stderr, so every INFO line showed up as an error. install() swaps the
console handler on a logger for a pair split on WARNING, and keeps the
formatter the replaced handler had.
"""

import logging
import sys

_MARK = "_bv_stream_split"


class _BelowWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


def _is_console(h: logging.Handler) -> bool:
    return (type(h) is logging.StreamHandler
            and getattr(h, "stream", None) in (sys.stdout, sys.stderr,
                                               sys.__stdout__, sys.__stderr__))


def install(logger: logging.Logger, fmt: logging.Formatter | None = None,
            out=None, err=None) -> None:
    """Replace the console handlers on `logger` with an stdout/stderr pair.

    Idempotent. Non-console handlers (files, test capture) are left alone.
    The formatter is `fmt`, else the replaced handler's, else the default.
    """
    if any(getattr(h, _MARK, False) for h in logger.handlers):
        return
    for h in list(logger.handlers):
        if _is_console(h):
            fmt = fmt or h.formatter
            logger.removeHandler(h)
    low = logging.StreamHandler(out or sys.stdout)
    low.addFilter(_BelowWarning())
    high = logging.StreamHandler(err or sys.stderr)
    high.setLevel(logging.WARNING)
    for h in (low, high):
        if fmt is not None:
            h.setFormatter(fmt)
        setattr(h, _MARK, True)
        logger.addHandler(h)
