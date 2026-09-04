import json
import runpy
import subprocess
import urllib.error
import urllib.parse
from collections import deque
from email.message import Message
from io import BytesIO
from typing import Any, NoReturn, cast

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
        self.call_kwargs: list[dict[str, object]] = []
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
        self.call_kwargs.append(kwargs)
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
    online: bool = True,
    advertised: list[str] | None = None,
    enabled: list[str] | None = None,
) -> dict[str, object]:
    return {
        "nodeId": node_id,
        "tags": [route.EXPECTED_TAG]
        if tags is None and node_id == "self-node"
        else (tags or []),
        "connectedToControl": online,
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


def core_inventory(document: dict[str, object]) -> dict[str, object]:
    devices = document["devices"]
    assert isinstance(devices, list)
    devices = cast(list[dict[str, object]], devices)
    return {
        "devices": [
            {key: raw_device[key] for key in ("nodeId", "tags", "connectedToControl")}
            for raw_device in devices
        ]
    }


def inventory_responses(document: dict[str, object] | None = None) -> list[Response]:
    document = inventory() if document is None else document
    devices = document["devices"]
    assert isinstance(devices, list)
    devices = cast(list[dict[str, object]], devices)
    return [
        Response(core_inventory(document)),
        *[
            Response(
                {
                    "advertisedRoutes": raw_device["advertisedRoutes"],
                    "enabledRoutes": raw_device["enabledRoutes"],
                }
            )
            for raw_device in devices
        ],
    ]


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
    send_calls = [call for call in fake.calls if "send-command" in call]
    wait_calls = [call for call in fake.calls if "wait" in call]
    get_calls = [call for call in fake.calls if "get-command-invocation" in call]
    assert len(send_calls) == 1
    assert len(wait_calls) == 1
    assert len(get_calls) == 1
    assert "i-0d33b9a9c15db93fc" in send_calls[0]
    assert route.SSM_DOCUMENT in send_calls[0]
    assert "--parameters" not in send_calls[0]
    assert wait_calls[0][wait_calls[0].index("wait") + 1] == "command-executed"
    assert "command_executed" not in wait_calls[0]
    for call in (wait_calls[0], get_calls[0]):
        assert call[1:3] == ["--region", route.REGION]
        assert route.INSTANCE_ID in call
        assert call[call.index("--command-id") + 1] == "command-1"
    wait_index = fake.calls.index(wait_calls[0])
    assert fake.call_kwargs[wait_index]["timeout"] == route.SSM_TIMEOUT
    assert 100.0 < route.SSM_TIMEOUT < 600.0
    get_index = fake.calls.index(get_calls[0])
    assert fake.call_kwargs[get_index]["timeout"] == route.AWS_TIMEOUT
    assert 0.0 < route.AWS_TIMEOUT < route.SSM_TIMEOUT
    assert route.SSM_COMMANDS == ("set -eu", "tailscale status --json")
    assert all("tailscale set" not in " ".join(call) for call in fake.calls)


class AwsWaitFailure:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if "send-command" in args:
            return subprocess.CompletedProcess(args, 0, "command-1\n", "")
        if "wait" in args:
            return subprocess.CompletedProcess(
                args, 1, "", "sensitive waiter failure details"
            )
        pytest.fail("final invocation read must not run after waiter failure")


def test_ssm_waiter_failure_stops_once_without_route_post() -> None:
    fake_aws = AwsWaitFailure()
    fake_url = UrlFake([])
    with pytest.raises(route.ApprovalError) as error_info:
        route.approve_route("client", "secret", runner=fake_aws, opener=fake_url)
    assert error_info.value.stage == "precondition"
    assert "sensitive waiter failure details" not in str(error_info.value)
    assert len([call for call in fake_aws.calls if "send-command" in call]) == 1
    assert len([call for call in fake_aws.calls if "wait" in call]) == 1
    assert not fake_url.requests


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
        "devices:core:read devices:routes",
        "devices:core:read devices:routes:read devices:routes devices:admin",
        "devices:core:read devices:routes:read devices:routes devices:routes",
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
        {"devices": [device("other-node")]},
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
                device(advertised=["::/1"]),
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
                device(online=False),
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


@pytest.mark.parametrize(
    ("advertised", "enabled"),
    [
        ([route.EXIT_NODE_DEFAULT], []),
        ([], [route.EXIT_NODE_DEFAULT]),
        ([route.EXIT_NODE_DEFAULT], [route.EXIT_NODE_DEFAULT]),
    ],
)
def test_unrelated_exit_default_is_accepted_in_each_route_field(
    advertised: list[str], enabled: list[str]
) -> None:
    document = inventory()
    devices = cast(list[dict[str, object]], document["devices"])
    devices[1]["advertisedRoutes"] = advertised
    devices[1]["enabledRoutes"] = enabled

    checked = route.validate_inventory(document, "self-node")

    assert checked.selected.node_id == "self-node"


@pytest.mark.parametrize("field", ["advertisedRoutes", "enabledRoutes"])
def test_selected_exit_default_is_rejected_in_each_route_field(field: str) -> None:
    document = inventory()
    devices = cast(list[dict[str, object]], document["devices"])
    devices[0][field] = (
        [route.EXPECTED_ROUTE, route.EXIT_NODE_DEFAULT]
        if field == "advertisedRoutes"
        else [route.EXIT_NODE_DEFAULT]
    )

    with pytest.raises(route.ApprovalError):
        route.validate_inventory(document, "self-node")


@pytest.mark.parametrize(
    "bad_routes",
    [
        ["0:0:0:0:0:0:0:0/0"],
        ["::/0/"],
        ["not-a-route"],
        [route.EXIT_NODE_DEFAULT, route.EXIT_NODE_DEFAULT],
    ],
)
def test_unrelated_default_requires_canonical_unique_well_formed_route(
    bad_routes: list[str],
) -> None:
    document = inventory()
    devices = cast(list[dict[str, object]], document["devices"])
    devices[1]["advertisedRoutes"] = bad_routes

    with pytest.raises(route.ApprovalError):
        route.validate_inventory(document, "self-node")


@pytest.mark.parametrize(
    "bad_route",
    [
        "fd7a:115c:a1e0:b1a::/95",
        "fd7a:115c:a1e0:b1a:0:1:ac1f:800/120",
    ],
)
def test_unrelated_overlapping_routes_other_than_default_are_rejected(
    bad_route: str,
) -> None:
    document = inventory()
    devices = cast(list[dict[str, object]], document["devices"])
    devices[1]["advertisedRoutes"] = [bad_route]

    with pytest.raises(route.ApprovalError):
        route.validate_inventory(document, "self-node")


def test_fetch_inventory_enriches_every_device_from_canonical_route_reads() -> None:
    document = {
        "devices": [
            {
                **device(
                    advertised=[],
                    enabled=[route.EXPECTED_ROUTE],
                ),
            },
            {
                **device(
                    "other/node",
                    advertised=[route.EXPECTED_ROUTE],
                    enabled=[route.EXPECTED_ROUTE],
                ),
            },
        ]
    }
    fake_url = UrlFake(
        [
            oauth_response(),
            Response(document),
            Response({"advertisedRoutes": [route.EXPECTED_ROUTE], "enabledRoutes": []}),
            Response({"advertisedRoutes": [], "enabledRoutes": []}),
        ]
    )

    summary = json.loads(
        route.diagnose_route("client", "secret", runner=AwsFake(), opener=fake_url)
    )

    assert summary["enabled"] is False
    assert [request.full_url for request in fake_url.requests[1:]] == [
        f"{route.API_ROOT}/tailnet/{urllib.parse.quote(route.TAILNET, safe='')}/devices",
        f"{route.API_ROOT}/device/self-node/routes",
        f"{route.API_ROOT}/device/other%2Fnode/routes",
    ]


@pytest.mark.parametrize(
    "bad_devices",
    [
        [device(node_id="")],
        [device(node_id=cast(str, None))],
        [device(), device()],
    ],
)
def test_invalid_list_node_ids_fail_before_route_requests(
    bad_devices: list[dict[str, object]],
) -> None:
    fake_url = UrlFake([oauth_response(), Response({"devices": bad_devices})])

    with pytest.raises(route.ApprovalError):
        route.diagnose_route("client", "secret", runner=AwsFake(), opener=fake_url)

    assert len(fake_url.requests) == 2


@pytest.mark.parametrize(
    "response",
    [
        Response(None),
        Response({"advertisedRoutes": []}),
        Response({"enabledRoutes": []}),
        Response({"advertisedRoutes": "invalid", "enabledRoutes": []}),
    ],
)
def test_malformed_route_response_fails_closed_without_post(response: Response) -> None:
    fake_url = UrlFake(
        [oauth_response(), Response(core_inventory(inventory())), response]
    )

    with pytest.raises(route.ApprovalError) as error_info:
        route.diagnose_route("client", "secret", runner=AwsFake(), opener=fake_url)

    assert error_info.value.stage == "device-get"
    assert not [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 504])
@pytest.mark.parametrize("failure", ["response", "http-error"])
def test_route_get_status_is_numeric_and_sanitized(status: int, failure: str) -> None:
    response: Response | BaseException = Response({}, status=status)
    if failure == "http-error":
        response = http_error(status)
    fake_url = UrlFake(
        [oauth_response(), Response(core_inventory(inventory())), response]
    )

    with pytest.raises(route.ApprovalError) as error_info:
        route.diagnose_route(
            "client-id-sentinel",
            "client-secret-sentinel",
            runner=AwsFake(),
            opener=fake_url,
        )

    assert str(error_info.value) == f"device-get: Tailscale API returned HTTP {status}"
    for sentinel in (
        "response-body-sentinel",
        "response-message-sentinel",
        "header-secret-sentinel",
        "request-secret",
        "client-secret-sentinel",
        "opaque",
    ):
        assert sentinel not in str(error_info.value)


def test_diagnostic_is_read_only_and_sanitized() -> None:
    fake_aws = AwsFake()
    fake_url = UrlFake([oauth_response(), *inventory_responses()])

    summary = json.loads(
        route.diagnose_route(
            "client-id", "client-secret", runner=fake_aws, opener=fake_url
        )
    )

    assert summary["node_id"] == "self-node"
    assert summary["tag"] == route.EXPECTED_TAG
    assert summary["online"] is True
    assert summary["advertised"] is True
    assert summary["enabled"] is False
    assert summary["advertised_route_count"] == 1
    assert summary["enabled_route_count"] == 0
    assert len(summary["advertised_route_hash"]) == 64
    assert len(summary["enabled_route_hash"]) == 64
    assert (
        len([call for call in fake_aws.calls if "get-command-invocation" in call]) == 1
    )
    assert len(fake_url.requests) == 4
    assert fake_url.requests[1].full_url == (
        f"{route.API_ROOT}/tailnet/{urllib.parse.quote(route.TAILNET, safe='')}/devices"
    )
    assert [request.full_url for request in fake_url.requests[2:]] == [
        f"{route.API_ROOT}/device/self-node/routes",
        f"{route.API_ROOT}/device/other-node/routes",
    ]
    assert not [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]
    output = json.dumps(summary)
    assert "client-secret" not in output
    assert "access_token" not in output
    assert "enabledRoutes" not in output


def http_error(status: int) -> urllib.error.HTTPError:
    headers = Message()
    headers["X-Response-Header"] = "header-secret-sentinel"
    return urllib.error.HTTPError(
        "https://api.tailscale.com/secret-url?request-secret=sentinel",
        status,
        "response-message-sentinel",
        headers,
        BytesIO(b"response-body-sentinel"),
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 504])
@pytest.mark.parametrize("failure", ["response", "http-error"])
def test_inventory_get_status_is_numeric_and_sanitized(
    status: int, failure: str
) -> None:
    response: Response | BaseException
    response = Response(
        {"response-body-sentinel": "response-body-sentinel"}, status=status
    )
    if failure == "http-error":
        response = http_error(status)
    fake_url = UrlFake([oauth_response(), response])

    with pytest.raises(route.ApprovalError) as error_info:
        route.diagnose_route(
            "client-id-sentinel",
            "client-secret-sentinel",
            runner=AwsFake(),
            opener=fake_url,
        )

    assert str(error_info.value) == f"device-get: Tailscale API returned HTTP {status}"
    for sentinel in (
        "response-body-sentinel",
        "response-message-sentinel",
        "header-secret-sentinel",
        "request-secret",
        "client-secret-sentinel",
        "opaque",
    ):
        assert sentinel not in str(error_info.value)
    assert not [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]


def test_read_only_cli_flag_cannot_fall_through_to_approval(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def diagnostic_stub(*_args: object, **_kwargs: object) -> str:
        return '{"diagnostic":true}'

    def approval_stub(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("diagnostic fell through to approval")

    monkeypatch.setattr(route.sys, "argv", ["route.py", "--read-only"])
    monkeypatch.setattr(route, "diagnose_route", diagnostic_stub)
    monkeypatch.setattr(route, "approve_route", approval_stub)

    route.main()

    assert capsys.readouterr().out == '{"diagnostic":true}\n'


def test_read_only_cli_reports_sanitized_numeric_http_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(route.subprocess, "run", AwsFake())
    monkeypatch.setattr(
        route.urllib.request,
        "urlopen",
        UrlFake([oauth_response(), Response({}, status=403)]),
    )
    monkeypatch.setenv("TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("TS_DEVELOPMENT_ROUTE_OAUTH_SECRET", "secret")
    monkeypatch.setattr(route.sys, "argv", [str(route.__file__), "--read-only"])

    with pytest.raises(SystemExit) as error_info:
        runpy.run_path(str(route.__file__), run_name="__main__")

    assert str(error_info.value) == (
        "development Tailscale route diagnostic failed "
        "(device-get: Tailscale API returned HTTP 403)"
    )


@pytest.mark.parametrize("diagnostic", [True, False])
def test_production_ipv4_route_is_rejected_before_any_write(diagnostic: bool) -> None:
    document = inventory(advertised=[route.EXPECTED_ROUTE, "172.31.0.0/16"])
    fake_url = UrlFake([oauth_response(), *inventory_responses(document)])
    with pytest.raises(route.ApprovalError):
        if diagnostic:
            route.diagnose_route("client", "secret", runner=AwsFake(), opener=fake_url)
        else:
            route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)
    assert not [
        request
        for request in fake_url.requests
        if request.method == "POST" and request.full_url.endswith("/routes")
    ]


def test_diagnostic_stage_errors_are_sanitized() -> None:
    with pytest.raises(route.ApprovalError) as error_info:
        route.diagnose_route(
            "client",
            "secret",
            runner=AwsExploding(RuntimeError("secret-response-payload")),
            opener=UrlFake([]),
        )
    assert error_info.value.stage == "precondition"
    assert str(error_info.value).startswith("precondition:")
    assert "secret-response-payload" not in str(error_info.value)

    with pytest.raises(route.ApprovalError) as error_info:
        route.diagnose_route(
            "client",
            "secret",
            runner=AwsFake(),
            opener=UrlFake([Response({}, status=403)]),
        )
    assert error_info.value.stage == "oauth-token"
    assert str(error_info.value).startswith("oauth-token:")
    assert "secret-response-payload" not in str(error_info.value)

    with pytest.raises(route.ApprovalError) as error_info:
        route.diagnose_route(
            "client",
            "secret",
            runner=AwsFake(),
            opener=UrlFake(
                [oauth_response(), Response({"devices": "secret-response-payload"})]
            ),
        )
    assert error_info.value.stage == "device-get"
    assert str(error_info.value).startswith("device-get:")
    assert "secret-response-payload" not in str(error_info.value)


def test_normal_approval_failure_stages_remain_distinct() -> None:
    re_get = UrlFake(
        [oauth_response(), *inventory_responses(), Response({}, status=500)]
    )
    with pytest.raises(route.ApprovalError) as error_info:
        route.approve_route("client", "secret", runner=AwsFake(), opener=re_get)
    assert error_info.value.stage == "re-get"
    assert str(error_info.value) == "re-get: Tailscale API returned HTTP 500"

    post = UrlFake(
        [
            oauth_response(),
            *inventory_responses(),
            *inventory_responses(),
            TimeoutError(),
            *inventory_responses(),
        ]
    )
    with pytest.raises(route.ApprovalError) as error_info:
        route.approve_route("client", "secret", runner=AwsFake(), opener=post)
    assert error_info.value.stage == "post"

    verification = UrlFake(
        [
            oauth_response(),
            *inventory_responses(),
            *inventory_responses(),
            Response({"ok": True}),
        ]
    )
    with pytest.raises(route.ApprovalError) as error_info:
        route.approve_route(
            "client",
            "secret",
            runner=AwsIdentitySequence(["self-node", "drift-node"]),
            opener=verification,
        )
    assert error_info.value.stage == "verification"


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
            *inventory_responses(inventory(enabled=[existing])),
            *inventory_responses(inventory(enabled=[existing])),
            post,
            *inventory_responses(inventory(enabled=[existing, route.EXPECTED_ROUTE])),
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
            *inventory_responses(inventory(enabled=[route.EXPECTED_ROUTE])),
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
            *inventory_responses(),
            *inventory_responses(),
            TimeoutError(),
            *inventory_responses(),
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
            *inventory_responses(),
            *inventory_responses(inventory(enabled=["2001:db8::/64"])),
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
            *inventory_responses(),
            *inventory_responses(),
            Response({"accepted": True}),
            *inventory_responses(),
        ]
    )
    with pytest.raises(route.ApprovalError, match="post-write"):
        route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)


def test_post_readback_rejects_dropped_unrelated_enabled_route() -> None:
    existing = "2001:db8::/64"
    fake_url = UrlFake(
        [
            oauth_response(),
            *inventory_responses(inventory(enabled=[existing])),
            *inventory_responses(inventory(enabled=[existing])),
            Response({"accepted": True}),
            *inventory_responses(inventory(enabled=[route.EXPECTED_ROUTE])),
        ]
    )
    with pytest.raises(route.ApprovalError, match="preservation"):
        route.approve_route("client", "secret", runner=AwsFake(), opener=fake_url)


def test_post_readback_rejects_ssm_identity_drift() -> None:
    fake_url = UrlFake(
        [
            oauth_response(),
            *inventory_responses(),
            *inventory_responses(),
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
