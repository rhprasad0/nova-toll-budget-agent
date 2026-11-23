import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any, Protocol, cast
from urllib.parse import urlencode

BASE_URL = "https://api.anthropic.com"
USAGE_PATH = "/v1/organizations/analytics/usage"
COST_PATH = "/v1/organizations/analytics/cost"
API_VERSION = "2026-10-21"
BETA = "analytics-usage-cost-2026-08-24"
DEFAULT_WORKSPACE_ID = "wrkspc_01FDNWCYNuxbxcZhFsD76VoQ"


class AnalyticsError(RuntimeError):
    pass


class CursorExpired(AnalyticsError):
    pass


class AnalyticsClient(Protocol):
    def get(self, path: str, params: Sequence[tuple[str, str]]) -> dict[str, Any]: ...


class HttpAnalyticsClient:
    def __init__(
        self, admin_key: str, *, base_url: str = BASE_URL, timeout: float = 60
    ) -> None:
        self._admin_key = admin_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get(self, path: str, params: Sequence[tuple[str, str]]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}{path}?{urlencode(list(params))}",
            headers={
                "x-api-key": self._admin_key,
                "anthropic-version": API_VERSION,
                "anthropic-beta": BETA,
                "accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body: Any = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 410:
                raise CursorExpired(f"cursor expired for {path}") from error
            detail = error.read(300).decode("utf-8", "replace")
            raise AnalyticsError(f"HTTP {error.code} from {path}: {detail}") from error
        except urllib.error.URLError as error:
            raise AnalyticsError(f"cannot reach {path}: {error.reason}") from error
        if not isinstance(body, dict):
            raise AnalyticsError(f"unexpected response from {path}")
        return cast(dict[str, Any], body)
