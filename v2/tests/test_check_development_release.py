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
        "account",
        "hash",
        "lambda",
        "alias",
        "weighted",
        "distribution",
        "old_runtime",
        "failed_runtime",
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
        return {
            "agentRuntimeArn": check.RUNTIME_ARN,
            "name": "preview",
            "status": "UPDATE_FAILED" if wrong == "failed_runtime" else "READY",
            "liveVersion": "7" if wrong == "old_runtime" else "8",
            "targetVersion": "8",
        }

    monkeypatch.setattr(check, "aws", aws)
    monkeypatch.setattr(check.time, "sleep", no_sleep)
    clock = iter([0, 601])
    monkeypatch.setattr(check.time, "monotonic", lambda: next(clock))
    if wrong:
        with pytest.raises((ValueError, KeyError)):
            check.readiness(values)
    else:
        check.readiness(values)
    assert len(calls) <= 8


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


def cookie(value: str) -> http.cookiejar.Cookie:
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
        {"HttpOnly": ""},
        False,
    )


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
    else:
        check.smoke(values)
        assert len(set(created)) == 2 and len(reset_calls) == 2


def test_redirect_and_oversized_response_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
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
