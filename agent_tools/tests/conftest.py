import sys
from pathlib import Path

AGENT_TOOLS_DIR = Path(__file__).resolve().parent.parent

# i66_route.py/i95_route.py/i495_route.py/_oracle_route.py are flat siblings
# (no package __init__), matching the lambdas/*/tests/ convention --
# distinct basenames here, so a plain sys.path insert is enough (no
# importlib private-name trick needed).
sys.path.insert(0, str(AGENT_TOOLS_DIR))


class FakeCursor:
    """Duck-typed psycopg cursor: .execute()/.fetchone(), no real DB.

    `responses` is consumed one entry per execute() call, in order -- lets a
    test script "row found on the primary query" vs "None, then a row on the
    fallback query" vs "None, None" (neither source has it) for i95's
    two-table lookup, or a single row/None for i66's single-table lookup.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self._last = None
        self.queries: list[tuple[str, dict | None]] = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self._last = self._responses.pop(0) if self._responses else None

    def fetchone(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Duck-typed psycopg connection wrapping one FakeCursor."""

    def __init__(self, responses):
        self.cur = FakeCursor(responses)
        self.closed = False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


def connect_returning(*rows):
    """Fresh FakeConnection per call, each yielding `rows` in order to execute()."""
    return lambda: FakeConnection(list(rows))
