"""Offline release checks: fake AWS and HTTP only, including session lifecycle."""

import base64
import hashlib
import http.cookiejar
import importlib.util
import json
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest

spec = importlib.util.spec_from_file_location(
    "release_check", Path(__file__).parents[1] / "scripts/check_development_release.py"
)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def no_sleep(_seconds: float) -> None:
    pass


@pytest.fixture
def release(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    digest = hashlib.sha256(b"static").hexdigest()
    paths = [f"v2/infra/build/{package}" for _, package in check.FUNCTIONS.values()]
    paths += [
        f"v2/agent/{name}"
        for name in (
            "dev_chat.html",
            "public_chat.mjs",
            "faq.html",
            "privacy.txt",
            "terms.txt",
            "assets/style.css",
        )
    ]
    manifest = {
        "commit_sha": "a" * 40,
        "files": [{"path": path, "sha256": digest} for path in paths],
    }
    resources: dict[str, Any] = {
        "aws_cloudfront_distribution.site": {"id": check.DISTRIBUTION},
        "aws_bedrockagentcore_agent_runtime.tollchat": {
            "agent_runtime_id": check.RUNTIME,
            "agent_runtime_arn": check.RUNTIME_ARN,
            "agent_runtime_version": "8",
        },
        "aws_bedrockagentcore_agent_runtime_endpoint.tollchat": {
            "agent_runtime_id": check.RUNTIME,
            "name": "preview",
            "agent_runtime_version": "8",
        },
        "aws_lambda_alias.tollchat_live": {
            "name": "live",
            "function_name": check.FUNCTIONS["tollchat_proxy"][0],
            "function_version": "12",
        },
    }
    for resource, (name, _) in check.FUNCTIONS.items():
        resources[f"aws_lambda_function.{resource}"] = {
            "function_name": name,
            "source_code_hash": base64.b64encode(bytes.fromhex(digest)).decode(),
            "version": "12",
        }
    state = {
        "values": {
            "root_module": {
                "resources": [
                    {"address": address, "values": values}
                    for address, values in resources.items()
                ]
            },
            "outputs": {"public_site": {"value": {"url": check.SITE}}},
        }
    }
    return state, manifest, resources


def test_expected_release_identity(release: tuple[dict[str, Any], ...]) -> None:
    state, manifest, _ = release
    assert check.expected(state, manifest)["version"] == "8"


@pytest.mark.parametrize(
    "wrong",
    ["sha", "hash", "lambda", "runtime", "endpoint", "alias", "distribution", "site"],
)
def test_wrong_expected_identity_rejected(
    release: tuple[dict[str, Any], ...], wrong: str
) -> None:
    state, manifest, resources = release
    if wrong == "sha":
        manifest["commit_sha"] = "b" * 40
    elif wrong == "site":
        state["values"]["outputs"]["public_site"]["value"]["url"] = (
            "https://tollchat.ai"
        )
    else:
        target, key, value = {
            "hash": ("aws_lambda_function.loader", "source_code_hash", "wrong"),
            "lambda": ("aws_lambda_function.loader", "function_name", "production"),
            "runtime": (
                "aws_bedrockagentcore_agent_runtime.tollchat",
                "agent_runtime_id",
                "wrong",
            ),
            "endpoint": (
                "aws_bedrockagentcore_agent_runtime_endpoint.tollchat",
                "agent_runtime_version",
                "7",
            ),
            "alias": ("aws_lambda_alias.tollchat_live", "function_version", "11"),
            "distribution": ("aws_cloudfront_distribution.site", "id", "wrong"),
        }[wrong]
        resources[target][key] = value
    with pytest.raises(ValueError):
        check.expected(state, manifest)


@pytest.mark.parametrize(
    "wrong",
    [
        None,
        "missing_target",
        "matching_target",
        "conflicting_target",
        "missing_live",
        "transitional_missing_versions",
        "account",
        "hash",
        "lambda",
        "alias",
        "weighted",
        "distribution",
        "old_runtime",
        "failed_runtime",
        "unknown_runtime",
        "malformed",
    ],
)
def test_readiness_exact_versions_and_deadline(
    release: tuple[dict[str, Any], ...],
    monkeypatch: pytest.MonkeyPatch,
    wrong: str | None,
) -> None:
    state, manifest, _ = release
    values = check.expected(state, manifest)
    digest = base64.b64encode(
        bytes.fromhex(next(iter(values["hashes"].values())))
    ).decode()
    calls: list[tuple[str, ...]] = []

    def aws(*args: str) -> dict[str, Any]:
        calls.append(args)
        if wrong == "malformed":
            return {}
        if args[0] == "sts":
            return {"Account": "wrong" if wrong == "account" else check.ACCOUNT}
        if args[1] == "get-function-configuration":
            name = args[3]
            return {
                "FunctionName": name,
                "FunctionArn": f"arn:aws:lambda:us-east-1:{check.ACCOUNT}:function:{name}",
                "State": "Failed" if wrong == "lambda" else "Active",
                "LastUpdateStatus": "Successful",
                "CodeSha256": "wrong" if wrong == "hash" else digest,
            }
        if args[1] == "get-alias":
            return {
                "Name": "live",
                "FunctionVersion": "11" if wrong == "alias" else "12",
                "RoutingConfig": {
                    "AdditionalVersionWeights": {"11": 0.1}
                    if wrong == "weighted"
                    else {}
                },
            }
        if args[0] == "cloudfront":
            return {
                "Distribution": {
                    "Id": check.DISTRIBUTION,
                    "Status": "InProgress" if wrong == "distribution" else "Deployed",
                }
            }
        endpoint = {
            "agentRuntimeArn": check.RUNTIME_ARN,
            "name": "preview",
            "status": (
                "UPDATE_FAILED"
                if wrong == "failed_runtime"
                else "BROKEN"
                if wrong == "unknown_runtime"
                else "UPDATING"
                if wrong == "transitional_missing_versions"
                else "READY"
            ),
        }
        if wrong != "missing_live" and wrong != "transitional_missing_versions":
            endpoint["liveVersion"] = "7" if wrong == "old_runtime" else "8"
        if wrong not in {"missing_target", "transitional_missing_versions"}:
            endpoint["targetVersion"] = "7" if wrong == "conflicting_target" else "8"
        return endpoint

    monkeypatch.setattr(check, "aws", aws)
    monkeypatch.setattr(check.time, "sleep", no_sleep)
    clock = iter([0, 601])
    monkeypatch.setattr(check.time, "monotonic", lambda: next(clock))
    if wrong not in {None, "missing_target", "matching_target"}:
        with pytest.raises(check.CheckFailure):
            check.readiness(values)
    else:
        check.readiness(values)
    assert len(calls) <= 8


def test_readiness_failure_output_is_local_and_bounded(
    release: tuple[dict[str, Any], ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, manifest, _ = release
    values = check.expected(state, manifest)
    sentinel = "raw-response-body-with-secret"

    def aws(*args: str) -> dict[str, Any]:
        if args[0] == "sts":
            return {"Account": check.ACCOUNT}
        if args[1] == "get-function-configuration":
            name = args[3]
            digest = base64.b64encode(
                bytes.fromhex(next(iter(values["hashes"].values())))
            ).decode()
            return {
                "FunctionName": name,
                "FunctionArn": f"arn:aws:lambda:us-east-1:{check.ACCOUNT}:function:{name}",
                "State": "Active",
                "LastUpdateStatus": "Successful",
                "CodeSha256": digest,
            }
        if args[1] == "get-alias":
            return {
                "Name": "live",
                "FunctionVersion": "12",
                "RoutingConfig": {},
            }
        if args[0] == "cloudfront":
            return {"Distribution": {"Id": check.DISTRIBUTION, "Status": "Deployed"}}
        return {
            "agentRuntimeArn": check.RUNTIME_ARN,
            "name": "preview",
            "status": sentinel,
        }

    monkeypatch.setattr(check, "aws", aws)
    with pytest.raises(ValueError):
        check.readiness(values)
    output = capsys.readouterr().err
    assert "stage=readiness" in output
    assert "status=fail" in output
    assert "reason=invalid_state" in output
    assert sentinel not in output


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "error"}],
        [{"type": "answer", "text": "", "blocked": False}],
        [{"type": "answer", "text": "x", "blocked": True}],
        [{"type": "answer", "text": "x", "blocked": False}, {"type": "tool"}],
        [{"type": "answer", "text": "x", "blocked": False}] * 2,
    ],
)
def test_invalid_ndjson_never_passes(events: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        check.answer(
            (
                200,
                "application/x-ndjson",
                b"\n".join(json.dumps(item).encode() for item in events),
            )
        )


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ((500, "application/x-ndjson", b""), "answer_status"),
        ((200, "application/json", b""), "answer_content_type"),
        ((200, "application/x-ndjson", b""), "answer_lines"),
        ((200, "application/x-ndjson", b"[]"), "answer_event"),
        (
            (
                200,
                "application/x-ndjson",
                b'{"type":"answer","text":"sentinel-answer","blocked":true}',
            ),
            "answer_content",
        ),
        (
            (200, "application/x-ndjson", b'{"type":"tool"}'),
            "answer_terminal",
        ),
    ],
)
def test_answer_failures_have_fixed_reasons(
    response: tuple[int, str, bytes],
    reason: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(check.CheckFailure):
        check.answer(response)
    output = capsys.readouterr().err
    assert f"reason={reason}" in output
    assert "sentinel-answer" not in output


def cookie(value: str, *, http_only: bool = True) -> http.cookiejar.Cookie:
    return http.cookiejar.Cookie(
        0,
        check.COOKIE,
        value,
        None,
        False,
        "dev.tollchat.ai",
        False,
        False,
        "/",
        True,
        True,
        None,
        True,
        None,
        None,
        {"HttpOnly": ""} if http_only else {},
        False,
    )


@pytest.mark.parametrize("failure", ["count", "attributes", "value"])
def test_session_cookie_failures_have_fixed_reasons(
    failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    jar = http.cookiejar.CookieJar()
    if failure != "count":
        item = cookie("sentinel-token", http_only=failure != "value")
        if failure == "attributes":
            item.secure = False
        jar.set_cookie(item)
    with pytest.raises(check.CheckFailure):
        check.token(jar)
    output = capsys.readouterr().err
    assert f"reason=session_cookie_{failure}" in output
    assert "sentinel-token" not in output


@pytest.mark.parametrize(
    ("code", "body", "with_cookie", "reason"),
    [
        (502, b"{}", False, "reset_response"),
        (200, b'{"ok": true}', True, "reset_cookie"),
    ],
)
def test_reset_failures_have_fixed_reasons(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: int,
    body: bytes,
    with_cookie: bool,
    reason: str,
) -> None:
    def request_stub(
        _jar: http.cookiejar.CookieJar,
        _path: str,
        _body: dict[str, Any] | None = None,
        *,
        origin: str = check.SITE,
        cookie: str | None = None,
    ) -> tuple[int, str, bytes]:
        del origin, cookie
        return code, "application/json", body

    monkeypatch.setattr(check, "request", request_stub)
    jar = http.cookiejar.CookieJar()
    if with_cookie:
        jar.set_cookie(cookie("sentinel-reset-token"))
    with pytest.raises(check.CheckFailure):
        check.reset(jar)
    output = capsys.readouterr().err
    assert f"reason={reason}" in output
    assert "sentinel-reset-token" not in output


@pytest.mark.parametrize(
    "wrong",
    [
        None,
        "static",
        "robots",
        "config",
        "origin",
        "shared",
        "revoked",
        "reset",
        "blocked",
        "cleanup",
    ],
)
def test_public_smoke_and_two_session_lifecycle(
    release: tuple[dict[str, Any], ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    wrong: str | None,
) -> None:
    state, manifest, _ = release
    values = check.expected(state, manifest)
    created: list[int] = []
    reset_calls: list[int] = []

    def request(
        jar: http.cookiejar.CookieJar,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        origin: str = check.SITE,
        cookie: str | None = None,
    ) -> tuple[int, str, bytes]:
        if path == "/robots.txt":
            return (
                200,
                "text/plain",
                b"wrong" if wrong == "robots" else b"User-agent: *\nDisallow: /\n",
            )
        if path == "/api/config":
            return (
                200,
                "application/json",
                json.dumps(
                    {
                        "chatEnabled": wrong != "config",
                        "maxTurns": 5,
                        "maxMessageChars": 4000,
                    }
                ).encode(),
            )
        if path == "/api/reset":
            reset_calls.append(id(jar))
            if wrong == "reset" or (wrong == "cleanup" and len(reset_calls) > 1):
                return 502, "application/json", b"{}"
            jar.clear()
            return 200, "application/json", b'{"ok": true}'
        if path == "/api/chat":
            if origin != check.SITE:
                return 200 if wrong == "origin" else 403, "application/json", b"{}"
            if cookie is not None:
                return (
                    200 if wrong == "revoked" else 401,
                    "application/json",
                    b'{"error":{"code":"session_expired"}}',
                )
            if not list(jar):
                created.append(id(jar))
                jar.set_cookie(
                    globals()["cookie"](
                        "shared" if wrong == "shared" else str(len(created))
                    )
                )
            return (
                200,
                "application/x-ndjson",
                json.dumps(
                    {
                        "type": "answer",
                        "text": "Benign answer",
                        "blocked": wrong == "blocked",
                    }
                ).encode(),
            )
        return 200, "text/plain", b"wrong" if wrong == "static" else b"static"

    monkeypatch.setattr(check, "request", request)
    monkeypatch.setattr(check.time, "sleep", no_sleep)
    if wrong:
        with pytest.raises(ValueError):
            check.smoke(values)
        expected_reason = {
            "static": "content_mismatch",
            "robots": "http",
            "config": "malformed_response",
            "origin": "http",
            "shared": "session_distinct",
            "revoked": "session_revocation",
            "reset": "reset_response",
            "blocked": "answer_content",
            "cleanup": "reset_failed",
        }[wrong]
        output = capsys.readouterr().err
        assert f"reason={expected_reason}" in output
        if wrong == "cleanup":
            assert output.count("reason=reset_failed") == 1
    else:
        check.smoke(values)
        assert len(set(created)) == 2 and len(reset_calls) == 2


@pytest.mark.parametrize(
    (
        "failure_stage",
        "failure_kind",
        "expected_subcheck",
        "expected_resets",
        "cleanup_failure",
    ),
    [
        ("session_first", "answer", "session_first", 1, False),
        ("session_second", "answer", "session_second", 2, False),
        ("session_reuse", "revoked", "session_reuse", 2, False),
        ("session_first", "answer", "session_first", 1, True),
    ],
)
def test_main_preserves_original_smoke_diagnostic_after_cleanup(
    release: tuple[dict[str, Any], ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    failure_stage: str,
    failure_kind: str,
    expected_subcheck: str,
    expected_resets: int,
    cleanup_failure: bool,
) -> None:
    state, manifest, _ = release
    values = check.expected(state, manifest)
    state_path, manifest_path = tmp_path / "state.json", tmp_path / "manifest.json"
    state_path.write_text("{}")
    manifest_path.write_text("{}")
    reset_calls: list[int] = []
    created = 0
    sentinel = "raw-revoked-response-sentinel"

    def request(
        jar: http.cookiejar.CookieJar,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        origin: str = check.SITE,
        cookie: str | None = None,
    ) -> tuple[int, str, bytes]:
        nonlocal created
        if path == "/robots.txt":
            return 200, "text/plain", b"User-agent: *\nDisallow: /\n"
        if path == "/api/config":
            return (
                200,
                "application/json",
                b'{"chatEnabled": true, "maxTurns": 5, "maxMessageChars": 4000}',
            )
        if path == "/api/reset":
            reset_calls.append(id(jar))
            if cleanup_failure:
                return 502, "application/json", b"{}"
            jar.clear()
            return 200, "application/json", b'{"ok": true}'
        if path == "/api/chat":
            if origin != check.SITE:
                return 403, "application/json", b"{}"
            if cookie is not None:
                if failure_kind == "revoked":
                    raise json.JSONDecodeError(sentinel, sentinel, 0)
                return 401, "application/json", b'{"error":{"code":"session_expired"}}'
            if not list(jar):
                created += 1
                jar.set_cookie(globals()["cookie"](str(created)))
            if failure_kind == "answer" and created == (
                1 if failure_stage == "session_first" else 2
            ):
                return 200, "application/x-ndjson", b"\xff"
            return (
                200,
                "application/x-ndjson",
                b'{"type":"answer","text":"ok","blocked":false}',
            )
        return 200, "text/plain", b"static"

    def expected_stub(
        _state: dict[str, Any], _manifest: dict[str, Any]
    ) -> dict[str, Any]:
        return values

    def readiness_stub(_values: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(check, "expected", expected_stub)
    monkeypatch.setattr(check, "readiness", readiness_stub)
    monkeypatch.setattr(check, "request", request)
    monkeypatch.setattr(
        check.sys, "argv", ["check", str(state_path), str(manifest_path)]
    )

    assert check.main() == 1
    output = capsys.readouterr().err
    assert f"subcheck={expected_subcheck}" in output
    assert "status=fail" in output and "reason=malformed_response" in output
    assert sentinel not in output
    assert len(reset_calls) == expected_resets


def test_request_hashes_exact_json_bytes_and_skips_bodyless_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Request] = []

    class Response:
        status = 200
        headers = Message()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def read(self, _size: int) -> bytes:
            return b"ok"

    class Opener:
        def open(self, req: Request, timeout: int) -> Response:
            assert timeout <= 90
            captured.append(req)
            return Response()

    def build_opener_stub(*_handlers: object) -> Opener:
        return Opener()

    monkeypatch.setattr(
        check.urllib.request,
        "build_opener",
        build_opener_stub,
    )
    jar = http.cookiejar.CookieJar()
    body = {"message": "exact bytes", "items": [3, 1, 4], "nested": {"ok": True}}
    check.request(jar, "/api/chat", body)
    request_with_body = captured.pop()
    assert isinstance(request_with_body.data, bytes)
    assert request_with_body.data == json.dumps(body).encode()
    payload_hash = next(
        value
        for name, value in request_with_body.header_items()
        if name.lower() == "x-amz-content-sha256"
    )
    assert payload_hash == hashlib.sha256(request_with_body.data).hexdigest()
    assert len(payload_hash) == 64 and payload_hash == payload_hash.lower()
    assert all(char in "0123456789abcdef" for char in payload_hash)

    check.request(jar, "/api/config")
    bodyless_request = captured.pop()
    assert bodyless_request.data is None
    assert not any(
        name.lower() in {"content-type", "x-amz-content-sha256"}
        for name, _value in bodyless_request.header_items()
    )


def test_request_path_failure_has_fixed_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(check.CheckFailure):
        check.request(http.cookiejar.CookieJar(), "relative")
    assert "reason=request_path" in capsys.readouterr().err


def test_diagnostics_never_echo_sensitive_inputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response_body = "response-body-secret"
    cookie_token = "cookie-token-secret"
    prompt = "prompt-secret"
    request_header = "https://request-header-secret.example"
    response_header = "response-header-secret"
    exception_text = "exception-text-secret"

    monkeypatch.setattr(check, "PROMPT", prompt)
    with pytest.raises(check.CheckFailure):
        check.answer(
            (
                200,
                "application/x-ndjson",
                json.dumps(
                    {
                        "type": "answer",
                        "text": f"{response_body}:{check.PROMPT}",
                        "blocked": True,
                    }
                ).encode(),
            )
        )

    class FailingOpener:
        def open(self, req: Request, timeout: int) -> object:
            assert req.get_header("Origin") == request_header
            assert req.get_header("Cookie") == f"{check.COOKIE}={cookie_token}"
            raise check.urllib.error.URLError(exception_text)

    def build_failing_opener(*_handlers: object) -> FailingOpener:
        return FailingOpener()

    monkeypatch.setattr(
        check.urllib.request,
        "build_opener",
        build_failing_opener,
    )
    with pytest.raises(check.CheckFailure):
        check.request(
            http.cookiejar.CookieJar(),
            "/api/chat",
            {"message": check.PROMPT},
            origin=request_header,
            cookie=cookie_token,
        )

    jar = http.cookiejar.CookieJar()
    invalid_cookie = cookie(cookie_token, http_only=False)
    jar.set_cookie(invalid_cookie)
    with pytest.raises(check.CheckFailure):
        check.token(jar)

    class OversizedResponse:
        status = 200
        headers = Message()

        def __enter__(self) -> "OversizedResponse":
            self.headers["X-Response-Secret"] = response_header
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def read(self, size: int) -> bytes:
            return b"x" * size

    class OversizedOpener:
        def open(self, _req: Request, timeout: int) -> OversizedResponse:
            return OversizedResponse()

    def build_oversized_opener(*_handlers: object) -> OversizedOpener:
        return OversizedOpener()

    monkeypatch.setattr(
        check.urllib.request,
        "build_opener",
        build_oversized_opener,
    )
    with pytest.raises(check.CheckFailure):
        check.request(http.cookiejar.CookieJar(), "/api/config")

    output = capsys.readouterr().err
    for sentinel in (
        response_body,
        cookie_token,
        prompt,
        request_header,
        response_header,
        exception_text,
    ):
        assert sentinel not in output


def test_redirect_and_oversized_response_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValueError):
        check.NoRedirect().redirect_request(
            None, None, 302, "", None, "https://evil.example"
        )

    class Response:
        status = 200
        headers = Message()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def read(self, size: int) -> bytes:
            return b"x" * size

    class Opener:
        def open(self, req: Request, timeout: int) -> Response:
            assert req.full_url.startswith(check.SITE + "/") and timeout <= 90
            return Response()

    def opener(*_handlers: object) -> Opener:
        return Opener()

    monkeypatch.setattr(check.urllib.request, "build_opener", opener)
    with pytest.raises(ValueError):
        check.request(http.cookiejar.CookieJar(), "/api/config")
    assert "reason=response_size" in capsys.readouterr().err
