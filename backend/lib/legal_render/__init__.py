"""One legal-document engine. Fifteen schemas, not fifteen designs.

    from lib.legal_render import CONVERTED_TYPES, render

`render(log_type, records, ctx)` returns the sheet, or None when the type has
no schema yet -- which is the caller's signal to fall through to its existing
renderer. `CONVERTED_TYPES` is the switch, and removing a name from it is the
one-line rollback.
"""

from .engine import render
from .schema import CONVERTED_TYPES, SCHEMAS, SchemaError, validate

__all__ = ["render", "CONVERTED_TYPES", "SCHEMAS", "SchemaError", "validate"]
