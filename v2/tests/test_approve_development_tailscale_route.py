import json
import subprocess
import urllib.parse
from collections import deque
from io import BytesIO
from typing import Any

import pytest

from scripts import approve_development_tailscale_route as route


class Response:
    def __init__(self, body: object, status: int = 200):
        self.status = status
        self.body = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return BytesIO(self.body).read()


class UrlFake:
    def __init__(self, responses: list[Response | BaseException]):
        self.responses = deque(responses)
        self.requests: list[Any] = []

    def __call__(self, request: Any, **kwargs: object) -> Response:
        self.requests.append(request)
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response


class AwsFake:
    def __init__(self, invocation: dict[str, object] | None = None):
        self.calls: list[list[str]] = []
        self.invocation: dict[str, object] = invocation or {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": json.dumps({"Self": {"ID": "self-node"}}),
            "StandardErrorContent": "",
        }

    def __call__(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if "send-command" in args:
            return subprocess.CompletedProcess(args, 0, "command-1\n", "")
        if "get-command-invocation" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.invocation), "")
        return subprocess.CompletedProcess(args, 0, "", "")


class AwsExploding:
    def __init__(self, error: BaseException):
        self.error = error

    def __call__(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise self.error


class AwsNonzero:
    def __call__(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "permission denied")


class AwsIdentitySequence(AwsFake):
    def __init__(self, node_ids: list[str]):
        super().__init__()
        self.node_ids = iter(node_ids)

    def __call__(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "get-command-invocation" not in args:
            return super().__call__(args, **kwargs)
        self.calls.append(args)
        invocation = dict(self.invocation)
        node_id = next(self.node_ids, "drift-node")
        invocation["StandardOutputContent"] = json.dumps({"Self": {"ID": node_id}})
        return subprocess.CompletedProcess(args, 0, json.dumps(invocation), "")


def device(
    node_id: str = "self-node",
    *,
    tags: list[str] | None = None,
    advertised: list[str] | None = None,
    enabled: list[str] | None = None,
) -> dict[str, object]:
    return {
        "nodeId": node_id,
        "tags": [route.EXPECTED_TAG]
        if tags is None and node_id == "self-node"
        else (tags or []),
        "advertisedRoutes": [] if advertised is None else advertised,
        "enabledRoutes": [] if enabled is None else enabled,
    }


def inventory(
    *, enabled: list[str] | None = None, advertised: list[str] | None = None
) -> dict[str, object]:
    return {
        "devices": [
            device(advertised=advertised or [route.EXPECTED_ROUTE], enabled=enabled),
            device("other-node"),
        ]
    }


def oauth_response(scope: str | None = route.OAUTH_SCOPE) -> Response:
    document: dict[str, object] = {"access_token": "opaque", "token_type": "Bearer"}
    if scope is not None:
        document["scope"] = scope
    return Response(document)


def test_parse_ssm_success_and_fail_closed_cases() -> None:
    valid: dict[str, object] = {
        "Status": "Success",
        "ResponseCode": 0,
        "StandardOutputContent": '{"Self":{"ID":"self-node"}}\n',
        "StandardErrorContent": "",
    }
    assert route.parse_ssm_invocation(valid) == "self-node"
    for field, value in (
        ("Status", "Failed"),
        ("ResponseCode", 1),
        ("ResponseCode", False),
        ("ResponseCode", 0.0),
        ("StandardErrorContent", "warning"),
        ("StandardOutputContent", "not-json"),
        ("StandardOutputContent", '{"Self":{}}'),
        ("StandardOutputContent", '{"Self":{"ID":"x"}}\n{"extra":true}'),
        ("StandardOutputContent", '{"Self":{"ID":7}}'),
    ):
        broken = dict(valid)
        broken[field] = value
        with pytest.raises(route.ApprovalError):
            route.parse_ssm_invocation(broken)


def test_ssm_uses_only_fixed_target_and_command() -> None:
    fake = AwsFake()
    assert route.read_router_node_id(runner=fake) == "self-node"
    assert "i-0d33b9a9c15db93fc" in fake.calls[0]
    assert route.SSM_DOCUMENT in fake.calls[0]
    assert "--parameters" not in fake.calls[0]
    assert route.SSM_COMMANDS == ("set -eu", "tailscale status --json")
    assert all("tailscale set" not in " ".join(call) for call in fake.calls)


@pytest.mark.parametrize(
    "runner",
    [
        AwsExploding(TimeoutError()),
        AwsExploding(subprocess.TimeoutExpired(["aws"], 1)),
        AwsExploding(OSError("unavailable")),
        AwsNonzero(),
    ],
)
def test_ssm_runner_failures_stop_without_fallback(runner: object) -> None:
    with pytest.raises(route.ApprovalError):
        route.read_router_node_id(runner=runner)  # type: ignore[arg-type]


def test_oauth_requests_exact_required_scope() -> None:
    fake = UrlFake([oauth_response()])
    assert route.obtain_oauth_token("client", "secret", opener=fake) == "opaque"
    assert fake.requests[0].data is not None
    form = urllib.parse.parse_qs(fake.requests[0].data.decode())
    assert form["scope"] == [route.OAUTH_SCOPE]


@pytest.mark.parametrize(
    "scope",
    [
        None,
        "",
        "devices:core:read",
        "devices:core:read devices:routes devices:admin",
        "devices:core:read devices:routes devices:routes",
    ],
)
def test_oauth_rejects_missing_insufficient_or_overbroad_scope(
    scope: str | None,
) -> None:
    with pytest.raises(route.ApprovalError, match="required scopes"):
        route.obtain_oauth_token(
            "client", "secret", opener=UrlFake([oauth_response(scope)])
        )


def test_inventory_binding_and_route_validation() -> None:
    valid = inventory(enabled=["2001:db8::/64"])
    checked = route.validate_inventory(valid, "self-node")
    assert checked.selected.node_id == "self-node"
    for broken in (
        {**valid, "nextPageToken": ""},
        {"devices": [device(), device()]},
        {
            "devices": [
                device(tags=[route.EXPECTED_TAG, "tag:extra"]),
                device("other-node"),
            ]
        },
        {"devices": [device(advertised=["192.0.2.0/24"]), device("other-node")]},
        {
            "devices": [
                device(advertised=["fd7a:115c:a1e0:b1a::/80"]),
                device("other-node"),
            ]
        },
        {
            "devices": [
                device(advertised=["fd7a:115c:a1e0:b1a:0:2::/112"]),
                device("other-node"),
            ]
        },
        {
            "devices": [
                device(advertised=["fd7a:115c:a1e0:b1a:0:1:ac1f:800/120"]),
                device("other-node"),
            ]
        },
        {
            "devices": [
                device(advertised=[]),
                device("other-node"),
            ]
        },
        {
            "devices": [
                device(advertised=[route.EXPECTED_ROUTE]),
                device("other-node", advertised=[route.EXPECTED_ROUTE]),
            ]
        },
    ):
        with pytest.raises(route.ApprovalError):
            route.validate_inventory(broken, "self-node")


def test_approval_is_idempotent_and_preserves_enabled_routes() -> None:
    existing = "2001:db8::/64"
    fake_aws = AwsFake()
    post = Response(
        {
            "advertisedRoutes": [route.EXPECTED_ROUTE],
            "enabledRoutes": [existing, route.EXPECTED_ROUTE],
        }
    )
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(inventory(enabled=[existing])),
            Response(inventory(enabled=[existing])),
            post,
            Response(inventory(enabled=[existing, route.EXPECTED_ROUTE])),
        ]
    )
    summary = route.approve_route("client", "secret", runner=fake_aws, opener=fake_url)
    assert json.loads(summary)["enabled"] is True
    posts = [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]
    assert len(posts) == 1
    assert json.loads(posts[0].data) == {"routes": [existing, route.EXPECTED_ROUTE]}
    assert "/device/self-node/routes" in posts[0].full_url

    already = UrlFake(
        [
            oauth_response(),
            Response(inventory(enabled=[route.EXPECTED_ROUTE])),
        ]
    )
    route.approve_route("client", "secret", runner=AwsFake(), opener=already)
    assert not [
        request
        for request in already.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]


def test_uncertain_post_is_read_once_and_never_retried() -> None:
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(inventory()),
            Response(inventory()),
            TimeoutError(),
            Response(inventory()),
        ]
    )
    with pytest.raises(route.ApprovalError, match="uncertain"):
        route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)
    posts = [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]
    assert len(posts) == 1


def test_selected_route_state_drift_aborts_before_post() -> None:
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(inventory()),
            Response(inventory(enabled=["2001:db8::/64"])),
        ]
    )
    with pytest.raises(route.ApprovalError, match="changed"):
        route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)
    assert not [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]


@pytest.mark.parametrize("status", [401, 403, 500])
def test_oauth_and_api_status_fail_closed(status: int) -> None:
    fake_url = UrlFake([Response({}, status=status)])
    with pytest.raises(route.ApprovalError):
        route.obtain_oauth_token("client", "secret", opener=fake_url)
    api_url = UrlFake([oauth_response(), Response({}, status=status)])
    with pytest.raises(route.ApprovalError):
        route.approve_route("client", "secret", runner=AwsFake(), opener=api_url)


def test_post_readback_proof_is_required() -> None:
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(inventory()),
            Response(inventory()),
            Response({"accepted": True}),
            Response(inventory()),
        ]
    )
    with pytest.raises(route.ApprovalError, match="post-write"):
        route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)


def test_post_readback_rejects_dropped_unrelated_enabled_route() -> None:
    existing = "2001:db8::/64"
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(inventory(enabled=[existing])),
            Response(inventory(enabled=[existing])),
            Response({"accepted": True}),
            Response(inventory(enabled=[route.EXPECTED_ROUTE])),
        ]
    )
    with pytest.raises(route.ApprovalError, match="preservation"):
        route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)


def test_post_readback_rejects_ssm_identity_drift() -> None:
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(inventory()),
            Response(inventory()),
            Response({"accepted": True}),
        ]
    )
    with pytest.raises(route.ApprovalError, match="SSM node ID changed"):
        route.approve_route(
            "client",
            "secret",
            runner=AwsIdentitySequence(["self-node", "drift-node"]),
            opener=fake_url,
        )
