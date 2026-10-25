"""The one lock around every pypdfium2 call in this process.

libpdfium is NOT thread-safe: two threads calling into it at once give "Data
format error" at best and a segfault at worst, and a segfault takes the whole API
with it. Anything in the API process that opens, reads or renders a PDF through
pypdfium2 (plan_page, sheet_tiles) takes this lock for the duration of each
pdfium call; it is re-entrant so a call may nest.

The sheet-tile compile does not rely on it in production: it renders in a child
process (lib.sheet_tiles CLI), where pdfium has the process to itself. The lock
covers the in-process users, and the CLI, tests and backfill that call the
library directly.
"""
import threading

PDFIUM_LOCK = threading.RLock()
