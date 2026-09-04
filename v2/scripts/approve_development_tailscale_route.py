"""Approve the reviewed development Tailscale subnet route."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from typing import Protocol, cast

API_ROOT = "https://api.tailscale.com/api/v2"
OAUTH_TOKEN_URL = f"{API_ROOT}/oauth/token"
TAILNET = "rhprasad0.github"
REGION = "us-east-1"
INSTANCE_ID = "i-0d33b9a9c15db93fc"
SSM_DOCUMENT = "nova-toll-v2-route-control-status-dev"
SSM_COMMANDS = ("set -eu", "tailscale status --json")
EXPECTED_TAG = "tag:nova-toll-development-router"
EXPECTED_ROUTE = "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
VIA6_SPACE = ipaddress.ip_network("fd7a:115c:a1e0:b1a::/64")
REQUIRED_SCOPES = ("devices:core:read", "devices:routes")
OAUTH_SCOPE = " ".join(REQUIRED_SCOPES)
AWS_TIMEOUT = 30.0
# The native waiter polls 20 times at 5 seconds; leave a small process margin.
SSM_TIMEOUT = 110.0
HTTP_TIMEOUT = 15.0

AwsRunner = Callable[..., subprocess.CompletedProcess[str]]


class ResponseLike(Protocol):
    status: int

    def __enter__(self) -> ResponseLike: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


UrlOpener = Callable[..., AbstractContextManager[ResponseLike]]
DEFAULT_OPENER = cast(UrlOpener, urllib.request.urlopen)


STAGES = ("precondition", "oauth-token", "device-get", "re-get", "post", "verification")
INVENTORY_GET_STAGES = ("device-get", "re-get", "verification")


class ApprovalError(RuntimeError):
    """A fail-closed route approval error."""

    def __init__(self, message: str, *, stage: str = "precondition") -> None:
        if stage not in STAGES:
            raise ValueError("invalid approval error stage")
        super().__init__(message)
        self.stage = stage

    def __str__(self) -> str:
        return f"{self.stage}: {self.args[0]}"


class UncertainWriteError(ApprovalError):
    """The route POST may have reached Tailscale, so it must not be retried."""


@dataclass(frozen=True)
class Device:
    node_id: str
    tags: tuple[str, ...]
    online: bool
    advertised_routes: tuple[str, ...]
    enabled_routes: tuple[str, ...]


@dataclass(frozen=True)
class Inventory:
    devices: tuple[Device, ...]
    selected: Device


def _fail(message: str, *, stage: str = "precondition") -> ApprovalError:
    return ApprovalError(message, stage=stage)


def _stage(error: ApprovalError, stage: str) -> ApprovalError:
    if error.stage == stage:
        return error
    return type(error)(str(error.args[0]), stage=stage)


def _aws(
    arguments: Sequence[str],
    *,
    timeout: float,
    runner: AwsRunner = subprocess.run,
) -> str:
    try:
        result = runner(
            ["aws", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except Exception as error:
        raise _fail("AWS command failed or timed out") from error
    if result.returncode != 0:
        raise _fail("AWS command failed")
    return result.stdout


def parse_ssm_invocation(document: object) -> str:
    """Validate the private SSM result and return only its local node ID."""
    if not isinstance(document, dict):
        raise _fail("invalid SSM invocation")
    document = cast(dict[str, object], document)
    response_code = document.get("ResponseCode")
    if (
        document.get("Status") != "Success"
        or type(response_code) is not int
        or response_code != 0
    ):
        raise _fail("SSM command did not succeed")
    if document.get("StandardErrorContent") != "":
        raise _fail("SSM command returned stderr")
    output = document.get("StandardOutputContent")
    if not isinstance(output, str) or not output.strip():
        raise _fail("SSM command returned invalid output")
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, TypeError) as error:
        raise _fail("SSM command returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise _fail("SSM status output is not an object")
    parsed = cast(dict[str, object], parsed)
    self_document = parsed.get("Self")
    if not isinstance(self_document, dict):
        raise _fail("SSM status output has no Self object")
    self_document = cast(dict[str, object], self_document)
    node_id = self_document.get("ID")
    if (
        not isinstance(node_id, str)
        or not node_id
        or not re.fullmatch(r"[A-Za-z0-9_-]+", node_id)
    ):
        raise _fail("SSM status output has an invalid Self.ID")
    return node_id


def read_router_node_id(
    *, runner: AwsRunner = subprocess.run, timeout: float = SSM_TIMEOUT
) -> str:
    """Read Self.ID from exactly the enrolled development router."""
    command_output = _aws(
        [
            "--region",
            REGION,
            "ssm",
            "send-command",
            "--instance-ids",
            INSTANCE_ID,
            "--document-name",
            SSM_DOCUMENT,
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        timeout=AWS_TIMEOUT,
        runner=runner,
    )
    command_lines = command_output.splitlines()
    if len(command_lines) != 1:
        raise _fail("SSM did not return exactly one command ID")
    command_id = command_lines[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", command_id):
        raise _fail("SSM returned an invalid command ID")

    _aws(
        [
            "--region",
            REGION,
            "ssm",
            "wait",
            "command-executed",
            "--command-id",
            command_id,
            "--instance-id",
            INSTANCE_ID,
        ],
        timeout=timeout,
        runner=runner,
    )
    invocation = _aws(
        [
            "--region",
            REGION,
            "ssm",
            "get-command-invocation",
            "--command-id",
            command_id,
            "--instance-id",
            INSTANCE_ID,
            "--query",
            "{Status:Status,ResponseCode:ResponseCode,StandardOutputContent:StandardOutputContent,StandardErrorContent:StandardErrorContent}",
            "--output",
            "json",
        ],
        timeout=AWS_TIMEOUT,
        runner=runner,
    )
    try:
        invocation_document = json.loads(invocation)
    except (json.JSONDecodeError, TypeError) as error:
        raise _fail("SSM invocation output is invalid JSON") from error
    return parse_ssm_invocation(invocation_document)


def _response_status(response: object) -> int | None:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    code = getcode() if callable(getcode) else None
    return code if isinstance(code, int) else None


def _inventory_get_status_error(
    method: str, stage: str, status: object
) -> ApprovalError | None:
    if (
        method == "GET"
        and stage in INVENTORY_GET_STAGES
        and type(status) is int
        and 100 <= status <= 599
    ):
        return _fail(f"Tailscale API returned HTTP {status}", stage=stage)
    return None


def _request_json(
    method: str,
    path: str,
    *,
    token: str,
    opener: UrlOpener,
    body: bytes | None = None,
    stage: str = "device-get",
) -> object:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{API_ROOT}{path}", headers=headers, data=body, method=method
    )
    try:
        with opener(request, timeout=HTTP_TIMEOUT) as response:
            status = _response_status(response)
            if status != 200:
                status_error = _inventory_get_status_error(method, stage, status)
                if status_error is not None:
                    raise status_error
                if status in (401, 403):
                    raise _fail(
                        "Tailscale OAuth scope or authorization denied", stage=stage
                    )
                if method == "POST" and (status is None or status >= 500):
                    raise UncertainWriteError(
                        "route update response is uncertain", stage="post"
                    )
                raise _fail("Tailscale API returned an unexpected status", stage=stage)
            return json.loads(response.read())
    except ApprovalError:
        raise
    except urllib.error.HTTPError as error:
        status_error = _inventory_get_status_error(method, stage, error.code)
        if status_error is not None:
            raise status_error from None
        if error.code in (401, 403):
            raise _fail(
                "Tailscale OAuth scope or authorization denied", stage=stage
            ) from error
        if method == "POST":
            raise UncertainWriteError(
                "route update response is uncertain", stage="post"
            ) from error
        raise _fail("Tailscale API request failed", stage=stage) from error
    except Exception as error:
        if method == "POST":
            raise UncertainWriteError(
                "route update response is uncertain", stage="post"
            ) from error
        raise _fail("Tailscale API request failed", stage=stage) from error


def obtain_oauth_token(
    client_id: str,
    client_secret: str,
    *,
    opener: UrlOpener = DEFAULT_OPENER,
) -> str:
    """Exchange protected OAuth client credentials without exposing them."""
    if not client_id:
        raise _fail("missing OAuth client ID", stage="oauth-token")
    if not client_secret:
        raise _fail("missing OAuth client secret", stage="oauth-token")
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": OAUTH_SCOPE,
        }
    ).encode()
    request = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=HTTP_TIMEOUT) as response:
            if _response_status(response) != 200:
                raise _fail("OAuth exchange failed", stage="oauth-token")
            document = json.loads(response.read())
    except ApprovalError:
        raise
    except Exception as error:
        raise _fail("OAuth exchange failed", stage="oauth-token") from error
    if not isinstance(document, dict):
        raise _fail("OAuth exchange returned invalid output", stage="oauth-token")
    document = cast(dict[str, object], document)
    token = document.get("access_token")
    if not isinstance(token, str) or not token:
        raise _fail("OAuth exchange returned no bearer token", stage="oauth-token")
    token_type = document.get("token_type")
    if token_type is not None and token_type != "Bearer":
        raise _fail(
            "OAuth exchange returned an invalid token type", stage="oauth-token"
        )
    scope = document.get("scope")
    scope_tokens = scope.split() if isinstance(scope, str) else []
    if len(scope_tokens) != len(REQUIRED_SCOPES) or set(scope_tokens) != set(
        REQUIRED_SCOPES
    ):
        raise _fail("OAuth token lacks required scopes", stage="oauth-token")
    return token


def _route_list(
    device: dict[str, object], field: str, node_id: str, selected_node_id: str
) -> tuple[str, ...]:
    value = device.get(field)
    if not isinstance(value, list):
        raise _fail("device route fields are malformed")
    values = cast(list[object], value)
    if any(not isinstance(route, str) for route in values):
        raise _fail("device route fields are malformed")
    routes = tuple(cast(str, route) for route in values)
    if len(routes) != len(set(routes)):
        raise _fail("device route fields contain duplicates")
    for route in routes:
        try:
            network = ipaddress.ip_network(route, strict=False)
        except ValueError as error:
            raise _fail("device route is malformed") from error
        if str(network) != route:
            raise _fail("device route is not canonical")
        if network.version == 4:
            if node_id == selected_node_id:
                raise _fail("intended device may not advertise or enable IPv4")
            continue
        if not network.overlaps(VIA6_SPACE):
            continue
        if network.prefixlen < 96:
            raise _fail("ambiguous 4via6 route")
        translator_identifier = (int(network.network_address) >> 32) & 0xFFFFFFFF
        if translator_identifier > 0xFFFF or (translator_identifier & 0xFFFF) != 1:
            raise _fail("foreign 4via6 route")
        if route != EXPECTED_ROUTE:
            raise _fail("unexpected site-1 4via6 route")
    return routes


def validate_inventory(document: object, self_id: str) -> Inventory:
    """Validate a complete inventory and bind it to the SSM-reported node."""
    if not self_id:
        raise _fail("missing SSM node ID")
    if not isinstance(document, dict):
        raise _fail("device inventory is not complete all-at-once data")
    document = cast(dict[str, object], document)
    if set(document) != {"devices"}:
        raise _fail("device inventory is not complete all-at-once data")
    devices_value = document.get("devices")
    if not isinstance(devices_value, list):
        raise _fail("device inventory is malformed")
    devices_value = cast(list[object], devices_value)

    devices: list[Device] = []
    node_ids: set[str] = set()
    route_owners: dict[str, set[str]] = {}
    tagged: list[Device] = []
    for raw_device in devices_value:
        if not isinstance(raw_device, dict):
            raise _fail("device inventory contains a malformed device")
        raw_device = cast(dict[str, object], raw_device)
        node_id = raw_device.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            raise _fail("device inventory contains a missing nodeId")
        if node_id in node_ids:
            raise _fail("device inventory contains duplicate nodeId")
        node_ids.add(node_id)
        tags_value = raw_device.get("tags")
        if not isinstance(tags_value, list):
            raise _fail("device tags are malformed")
        tag_values = cast(list[object], tags_value)
        if any(not isinstance(tag, str) for tag in tag_values):
            raise _fail("device tags are malformed")
        tags = tuple(cast(str, tag) for tag in tag_values)
        if len(tags) != len(set(tags)):
            raise _fail("device tags contain duplicates")
        online = raw_device.get("online")
        if not isinstance(online, bool):
            raise _fail("device online state is malformed")
        advertised = _route_list(raw_device, "advertisedRoutes", node_id, self_id)
        enabled = _route_list(raw_device, "enabledRoutes", node_id, self_id)
        device = Device(node_id, tags, online, advertised, enabled)
        devices.append(device)
        if EXPECTED_TAG in tags:
            tagged.append(device)
        for route in (*advertised, *enabled):
            network = ipaddress.ip_network(route, strict=True)
            if network.version == 6 and network.overlaps(VIA6_SPACE):
                route_owners.setdefault(route, set()).add(node_id)
    selected_matches = [device for device in devices if device.node_id == self_id]
    if len(selected_matches) != 1:
        raise _fail("SSM node ID is absent or ambiguous in inventory")
    selected = selected_matches[0]
    if not selected.online:
        raise _fail("bound device is offline")
    if len(tagged) != 1 or tagged[0] != selected:
        raise _fail("development router tag is absent or ambiguous")
    if selected.tags != (EXPECTED_TAG,):
        raise _fail("bound device does not have exactly the development tag")
    if any(owners != {self_id} for owners in route_owners.values()):
        raise _fail("4via6 route ownership is ambiguous")
    if EXPECTED_ROUTE not in selected.advertised_routes:
        raise _fail("exact development route is not advertised")
    return Inventory(tuple(devices), selected)


def _fetch_inventory(
    token: str,
    self_id: str,
    *,
    opener: UrlOpener,
    stage: str = "device-get",
) -> Inventory:
    try:
        document = _request_json(
            "GET",
            f"/tailnet/{urllib.parse.quote(TAILNET, safe='')}/devices",
            token=token,
            opener=opener,
            stage=stage,
        )
        return validate_inventory(document, self_id)
    except ApprovalError as error:
        raise _stage(error, stage) from error


def _post_enabled_routes(
    inventory: Inventory, token: str, *, opener: UrlOpener
) -> None:
    routes = list(inventory.selected.enabled_routes)
    if EXPECTED_ROUTE not in routes:
        routes.append(EXPECTED_ROUTE)
    body = json.dumps({"routes": routes}, separators=(",", ":")).encode()
    _request_json(
        "POST",
        f"/device/{urllib.parse.quote(inventory.selected.node_id, safe='')}/routes",
        token=token,
        opener=opener,
        body=body,
        stage="post",
    )


def _summary(inventory: Inventory) -> str:
    return json.dumps(
        {
            "account": "903859731897",
            "instance_id": INSTANCE_ID,
            "node_id": inventory.selected.node_id,
            "route": EXPECTED_ROUTE,
            "advertised": EXPECTED_ROUTE in inventory.selected.advertised_routes,
            "enabled": EXPECTED_ROUTE in inventory.selected.enabled_routes,
            "commit_sha": os.environ.get("GITHUB_SHA", ""),
            "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        },
        sort_keys=True,
    )


def _route_hash(routes: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(routes)).encode()).hexdigest()


def _diagnostic_summary(inventory: Inventory) -> str:
    selected = inventory.selected
    return json.dumps(
        {
            "account": "903859731897",
            "instance_id": INSTANCE_ID,
            "node_id": selected.node_id,
            "tag": EXPECTED_TAG,
            "online": selected.online,
            "route": EXPECTED_ROUTE,
            "advertised": EXPECTED_ROUTE in selected.advertised_routes,
            "enabled": EXPECTED_ROUTE in selected.enabled_routes,
            "advertised_route_count": len(selected.advertised_routes),
            "enabled_route_count": len(selected.enabled_routes),
            "advertised_route_hash": _route_hash(selected.advertised_routes),
            "enabled_route_hash": _route_hash(selected.enabled_routes),
        },
        sort_keys=True,
    )


def approve_route(
    client_id: str,
    client_secret: str,
    *,
    runner: AwsRunner = subprocess.run,
    opener: UrlOpener = DEFAULT_OPENER,
) -> str:
    """Approve the route once, preserving every existing enabled route."""
    self_id = read_router_node_id(runner=runner)
    token = obtain_oauth_token(client_id, client_secret, opener=opener)
    initial = _fetch_inventory(token, self_id, opener=opener, stage="device-get")
    if EXPECTED_ROUTE in initial.selected.enabled_routes:
        return _summary(initial)
    current = _fetch_inventory(token, self_id, opener=opener, stage="re-get")
    if current.selected != initial.selected:
        raise _fail("selected device route state changed before write", stage="re-get")
    if EXPECTED_ROUTE in current.selected.enabled_routes:
        return _summary(current)
    expected_enabled_routes = frozenset(current.selected.enabled_routes)
    try:
        _post_enabled_routes(current, token, opener=opener)
    except UncertainWriteError as error:
        with suppress(ApprovalError):
            _fetch_inventory(token, self_id, opener=opener, stage="verification")
        raise _fail(
            "route update response is uncertain; no retry performed", stage="post"
        ) from error
    try:
        post_self_id = read_router_node_id(runner=runner)
    except ApprovalError as error:
        raise _stage(error, "verification") from error
    if post_self_id != self_id:
        raise _fail("SSM node ID changed after route update", stage="verification")
    verified = _fetch_inventory(token, self_id, opener=opener, stage="verification")
    expected_enabled_after = expected_enabled_routes | {EXPECTED_ROUTE}
    if frozenset(verified.selected.enabled_routes) != expected_enabled_after:
        raise _fail(
            "post-write enabled route preservation proof failed", stage="verification"
        )
    return _summary(verified)


def diagnose_route(
    client_id: str,
    client_secret: str,
    *,
    runner: AwsRunner = subprocess.run,
    opener: UrlOpener = DEFAULT_OPENER,
) -> str:
    """Read and summarize route state without any route-control write path."""
    self_id = read_router_node_id(runner=runner)
    token = obtain_oauth_token(client_id, client_secret, opener=opener)
    inventory = _fetch_inventory(token, self_id, opener=opener, stage="device-get")
    return _diagnostic_summary(inventory)


def main() -> None:
    arguments = sys.argv[1:]
    if arguments not in ([], ["--read-only"]):
        raise _fail("invalid arguments")
    client_id = os.environ.get("TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("TS_DEVELOPMENT_ROUTE_OAUTH_SECRET", "")
    if arguments == ["--read-only"]:
        print(diagnose_route(client_id, client_secret))
    else:
        print(approve_route(client_id, client_secret))


if __name__ == "__main__":
    try:
        main()
    except ApprovalError as error:
        operation = "diagnostic" if sys.argv[1:] == ["--read-only"] else "approval"
        raise SystemExit(
            f"development Tailscale route {operation} failed ({error})"
        ) from error
