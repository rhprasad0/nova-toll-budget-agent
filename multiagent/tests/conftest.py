from collections.abc import Iterable
from types import TracebackType


class FakeCursor:
    def __init__(self, rows: Iterable[tuple[object, ...] | None]) -> None:
        self.rows = iter(rows)
        self.queries: list[tuple[str, dict[str, object]]] = []

    def execute(self, query: str, params: dict[str, object]) -> None:
        self.queries.append((query, params))

    def fetchone(self) -> tuple[object, ...] | None:
        return next(self.rows)


class FakeConnection:
    def __init__(self, rows: Iterable[tuple[object, ...] | None]) -> None:
        self.cur = FakeCursor(rows)
        self.closed = False

    def cursor(self) -> "FakeConnection":
        return self

    def __enter__(self) -> FakeCursor:
        return self.cur

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def close(self) -> None:
        self.closed = True
