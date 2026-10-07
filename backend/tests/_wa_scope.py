"""Test helper: stand in for server._bot_project_scope.

Every WhatsApp read is now gated on proof that the project belongs to the
group's company (server._bot_project_scope). Tests written before the gate
built a fake `db` with only the collections the handler under test reads, and
no `projects` collection to prove ownership against. Rather than teach every
one of those fakes Mongo's `$in`, they patch the gate with this: it admits
exactly the (company, project) pairs the test declares, and nothing else — so
a test that forgets to declare ownership still fails closed, which is the
behaviour under test elsewhere.
"""

from contextlib import contextmanager
from unittest import mock

TEST_COMPANY = "co-test"


@contextmanager
def owned_by(company_id=TEST_COMPANY, *project_ids, project_docs=None,
             module=None):
    """Admit `project_ids` as owned by `company_id` for the duration.

    Pass `module=` — the `server` object the TEST imported. Some files in the
    suite reload `server`, so `sys.modules["server"]` can be a different
    object from the one whose functions the test is calling; patching the
    wrong one leaves the real gate in place and the test fails closed."""
    if module is None:
        import server as module
    server = module

    docs = dict(project_docs or {})
    allowed = {str(p) for p in project_ids} | set(docs)

    async def _scope(cid, pid):
        if str(cid or "") == str(company_id) and str(pid or "") in allowed:
            base = {"_id": str(pid), "company_id": company_id,
                    "name": "Test Project"}
            base.update(docs.get(str(pid), {}))
            return base
        return None

    with mock.patch.object(server, "_bot_project_scope", _scope):
        yield
