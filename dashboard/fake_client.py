from collections import defaultdict
from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from dashboard.analytics import AnalyticsError, CursorExpired


def _shift(row: dict[str, Any], days: int) -> dict[str, Any]:
    copy = deepcopy(row)
    for key in ("starting_at", "ending_at"):
        moved = datetime.fromisoformat(copy[key]) + timedelta(days=days)
        copy[key] = moved.strftime("%Y-%m-%dT%H:%M:%SZ")
    return copy


class FakeAnalytics:
    def __init__(
        self,
        usage: Sequence[dict[str, Any]],
        cost: Sequence[dict[str, Any]],
        *,
        usage_refreshed_at: str = "2026-01-01T00:00:00Z",
        cost_refreshed_at: str = "2026-01-01T00:00:00Z",
        page_size: int = 1000,
        shift_days: int = 0,
        expire_cursor_once: bool = False,
    ) -> None:
        self._rows = {
            "usage": [_shift(row, shift_days) for row in usage],
            "cost": [_shift(row, shift_days) for row in cost],
        }
        self._refreshed = {"usage": usage_refreshed_at, "cost": cost_refreshed_at}
        self._page_size = page_size
        self._expire_cursor = expire_cursor_once
        self.cursor_expirations = 0
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def get(self, path: str, params: Sequence[tuple[str, str]]) -> dict[str, Any]:
        query: dict[str, list[str]] = defaultdict(list)
        for key, value in params:
            query[key].append(value)
        self.requests.append((path, dict(query)))
        kind = path.rsplit("/", 1)[-1]
        if kind not in self._rows:
            raise AnalyticsError(f"fake has no endpoint {path}")
        start = datetime.fromisoformat(query["starting_at"][0])
        end = datetime.fromisoformat(query["ending_at"][0])
        matching = [
            row
            for row in self._rows[kind]
            if start <= datetime.fromisoformat(row["starting_at"]) < end
        ]
        offset = 0
        if query.get("page"):
            if self._expire_cursor:
                self._expire_cursor = False
                self.cursor_expirations += 1
                raise CursorExpired(path)
            offset = int(query["page"][0].removeprefix("offset-"))
        size = min(
            int(query["limit"][0]) if query.get("limit") else self._page_size,
            self._page_size,
        )
        more = offset + size < len(matching)
        return {
            "data": matching[offset : offset + size],
            "data_refreshed_at": self._refreshed[kind],
            "has_more": more,
            "next_page": f"offset-{offset + size}" if more else None,
        }
