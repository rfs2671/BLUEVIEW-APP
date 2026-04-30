"""Handler modules for the dob_worker queue dispatcher.

Each handler exposes:
    async def handle(payload: dict, context: HandlerContext) -> HandlerResult

dob_worker.py routes incoming queue jobs to handlers via job_type.

LAZY IMPORTS: bis_scrape pulls in heavy deps (Playwright, BeautifulSoup,
APScheduler, Motor). Importing those at handler-package load time
breaks any test environment that doesn't have them installed and
forces every consumer of the package to pay the heavy import cost.
HANDLERS is a name → import-path mapping; the actual handle()
function is resolved on first lookup via get_handler().
"""

import importlib
from typing import Any, Callable, Dict, Optional


HANDLERS: Dict[str, str] = {
    "bis_scrape": "handlers.bis_scrape:handle",
    "dob_now_filing": "handlers.dob_now_filing:handle",
}


def get_handler(job_type: str) -> Optional[Callable[..., Any]]:
    """Resolve a handler reference to its callable. Returns None if
    the job_type is not registered."""
    target = HANDLERS.get(job_type)
    if not target:
        return None
    module_path, _, attr = target.partition(":")
    mod = importlib.import_module(module_path)
    return getattr(mod, attr)
