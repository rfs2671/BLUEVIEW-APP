"""INFO/DEBUG go to stdout, WARNING+ to stderr (Railway: stderr == error)."""

import io
import logging
import sys
import unittest
from pathlib import Path

from lib import log_streams


class LogStreamsTest(unittest.TestCase):
    def _logger(self, name):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        self.addCleanup(lg.handlers.clear)
        return lg

    def test_levels_split_by_stream(self):
        lg = self._logger("t.split")
        out, err = io.StringIO(), io.StringIO()
        log_streams.install(lg, logging.Formatter("%(levelname)s %(message)s"),
                            out=out, err=err)
        lg.debug("d"); lg.info("i"); lg.warning("w"); lg.error("e"); lg.critical("c")
        self.assertEqual(out.getvalue().split(), ["DEBUG", "d", "INFO", "i"])
        self.assertEqual(err.getvalue().split(),
                         ["WARNING", "w", "ERROR", "e", "CRITICAL", "c"])

    def test_replaces_stderr_handler_and_keeps_its_formatter(self):
        lg = self._logger("t.replace")
        old = logging.StreamHandler(sys.stderr)
        old.setFormatter(logging.Formatter("X %(message)s"))
        lg.addHandler(old)
        out, err = io.StringIO(), io.StringIO()
        log_streams.install(lg, out=out, err=err)
        self.assertNotIn(old, lg.handlers)
        lg.info("hello"); lg.warning("bad")
        self.assertEqual(out.getvalue(), "X hello\n")
        self.assertEqual(err.getvalue(), "X bad\n")

    def test_idempotent_and_leaves_other_handlers(self):
        lg = self._logger("t.idem")
        cap = logging.StreamHandler(io.StringIO())
        lg.addHandler(cap)
        log_streams.install(lg, out=io.StringIO(), err=io.StringIO())
        log_streams.install(lg, out=io.StringIO(), err=io.StringIO())
        self.assertIn(cap, lg.handlers)
        self.assertEqual(len(lg.handlers), 3)

    def test_server_installs_on_root_and_uvicorn(self):
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
        self.assertIn("log_streams.install(logging.getLogger(), ", src)
        self.assertIn('log_streams.install(logging.getLogger("uvicorn"))', src)


if __name__ == "__main__":
    unittest.main()
