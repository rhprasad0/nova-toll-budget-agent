"""Offline contracts for the v2 loopback streaming console."""

# pyright: basic

import asyncio
import json
import threading
import tomllib
import urllib.error
import urllib.request
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from agent import dev_chat
from agent.dev_chat import DevChat, create_server


def test_local_console_uses_refreshable_aws_login_credentials():
    root = Path(__file__).parents[1]
    dependencies = tomllib.loads((root / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    readme = (root / "README.md").read_text()

    assert any(dependency.startswith("boto3[crt]") for dependency in dependencies)
    assert "AWS_PROFILE=nova-toll" in readme
    assert "export-credentials" not in readme


class _Metrics:
    def get_summary(self):
        return {"total_cycles": 2, "tool_usage": {"get_current_toll_price": 1}}


class _Result:
    metrics = _Metrics()

    def __str__(self):
        return "## Price\n\nHello 👋 **$4.25**"

    def to_dict(self):
        return {"message": {"role": "assistant", "content": [{"text": str(self)}]}}


class _Agent:
    def __init__(self, number, factory_kwargs):
        self.number = number
        self.factory_kwargs = factory_kwargs

    async def stream_async(self, prompt):
        yield {"init_event_loop": True}
        yield {"data": f"{self.number}: {prompt} 👋"}
        yield {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": "get_current_toll_price",
                            "input": {"origin_point_id": "a"},
                        }
                    }
                ],
            }
        }
        yield {
            "message": {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "tool-1",
                            "status": "success",
                            "content": [{"text": "priced"}],
                        }
                    }
                ],
            }
        }
        yield {"result": _Result()}


class _Factory:
    def __init__(self):
        self.agents = []

    def __call__(self, **kwargs):
        agent = _Agent(len(self.agents) + 1, kwargs)
        self.agents.append(agent)
        return agent


class _FailingAgent:
    async def stream_async(self, _prompt):
        yield {"data": "partial"}
        raise ValueError("secret failure details")


async def _collect(app, session_id="browser", message="hello"):
    return [event async for event in app.stream(session_id, message)]


def test_streams_raw_events_text_tools_result_and_reuses_session():
    factory = _Factory()
    app = DevChat(factory)

    events = asyncio.run(_collect(app, message="price it"))

    assert [event["sequence"] for event in events] == list(range(5))
    assert events[0]["event"] == {"init_event_loop": True}
    assert events[1]["text_delta"] == "1: price it 👋"
    assert events[2]["tool_updates"] == [
        {
            "index": 0,
            "label": "Checking current toll price",
            "status": "running",
        }
    ]
    assert events[3]["tool_updates"][0]["status"] == "completed"
    assert events[4]["final"] == {
        "text": "## Price\n\nHello 👋 **$4.25**",
        "metrics": {
            "total_cycles": 2,
            "tool_usage": {"get_current_toll_price": 1},
        },
    }
    assert isinstance(events[4]["event"]["result"], dict)

    second = asyncio.run(_collect(app, message="again"))
    assert second[1]["text_delta"].startswith("1:")
    assert len(factory.agents) == 1
    assert factory.agents[0].factory_kwargs == {}


def test_reset_and_new_york_date_create_fresh_agents(monkeypatch):
    dates = iter((date(2026, 8, 22), date(2026, 8, 22), date(2026, 8, 23)))
    monkeypatch.setattr(dev_chat, "_new_york_date", lambda: next(dates))
    factory = _Factory()
    app = DevChat(factory)

    assert asyncio.run(_collect(app))[1]["text_delta"].startswith("1:")
    assert asyncio.run(_collect(app))[1]["text_delta"].startswith("1:")
    assert asyncio.run(_collect(app))[1]["text_delta"].startswith("2:")
    app.reset("browser")
    assert len(factory.agents) == 2


@pytest.mark.parametrize(
    ("session_id", "message"),
    [("", "hello"), ("bad/id", "hello"), ("ok", " "), ("ok", 1)],
)
def test_rejects_invalid_input(session_id, message):
    with pytest.raises((TypeError, ValueError)):
        DevChat(_Factory()).validate(session_id, message)


def test_agent_failure_emits_one_safe_terminal_error(caplog):
    app = DevChat(lambda **_kwargs: _FailingAgent())

    events = asyncio.run(_collect(app))

    assert events[0]["text_delta"] == "partial"
    assert events[-1] == {
        "type": "error",
        "sequence": 1,
        "message": "TollChat couldn't complete the request. Check the server log.",
    }
    assert "secret failure details" in caplog.text
    assert "browser" not in caplog.text


def test_agent_construction_failure_emits_one_safe_terminal_error(caplog):
    def fail(**_kwargs):
        raise ValueError("startup secret details")

    events = asyncio.run(_collect(DevChat(fail)))

    assert events == [
        {
            "type": "error",
            "sequence": 0,
            "message": "TollChat couldn't complete the request. Check the server log.",
        }
    ]
    assert "startup secret details" in caplog.text


def test_http_server_serves_assets_streams_ndjson_and_resets():
    factory = _Factory()
    app = DevChat(factory)
    server = create_server(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base_url, timeout=2)
        assert page.headers["Cache-Control"] == "no-store"
        html = page.read().decode()
        assert "counts anonymous chat sessions that send a message" in html
        assert "Responses storage disabled" in html
        assert "abuse-monitoring logs" in html
        assert "up to 30 days by default" in html
        assert "retains Responses API data for at least 30 days" not in html
        assert "tradeoff to keep TollChat free to use" in html
        assert "https://developers.openai.com/api/docs/guides/your-data" in html
        assert "reasonable tax and vehicle-cost assumptions" in html
        assert "rough take-home-pay estimate" in html
        assert "We observed no fabricated costs in our 1,000-answer test" in html
        assert (
            "Toll and take-home-pay figures come from code, not AI arithmetic" in html
        )
        assert "996 responses (99.6%) used only supplied numbers" in html
        assert "constrained route and pricing tools" not in html
        assert "supplied tool evidence under the strict policy" not in html
        assert "contact@tollchat.ai" in html
        assert "not affiliated with VDOT or any toll operator" in html
        assert "VDOT SmarterRoads" in html
        assert "https://smarterroads.vdot.virginia.gov/faq" in html
        assert 'href="/privacy.txt"' in html
        assert 'href="/terms.txt"' in html
        assert 'href="/assets/favicon.png"' in html
        assert "Do not submit names, exact home or work addresses" in html
        assert "not a navigation or emergency service" in html
        assert "2026 Benevolent Clankers LLC" in html
        assert "TollChat name and branding reserved" in html
        assert "blob/main/LICENSE" in html
        assert 'href="/faq.html#hallucinations-title"' in html
        assert 'href="/faq.html#take-home-title"' in html
        assert "What is the current price from Dumfries to Washington?" in html
        assert "$130,000 gross annual salary" in html
        assert "general information only" in html
        assert "financial or employment decisions" in html
        assert "Strands events" not in html
        assert 'id="reset-map"' in html
        assert "Small pins mark supported entrances and exits" in html
        assert "price unavailable" not in html.lower()
        assert "data-facility" not in html
        assert (
            "consumeNdjson"
            in urllib.request.urlopen(f"{base_url}/dev_chat.mjs", timeout=2)
            .read()
            .decode()
        )
        logo = urllib.request.urlopen(f"{base_url}/assets/tollchat-logo.png", timeout=2)
        assert logo.headers.get_content_type() == "image/png"
        assert sha256(logo.read()).hexdigest() == (
            "da0167c64714b0e37c234d18695aecf6f81226627ca21e105e1fcc43c397e1a6"
        )
        faq = urllib.request.urlopen(f"{base_url}/faq.html", timeout=2).read().decode()
        assert 'href="/assets/favicon.png"' in faq
        assert "How TollChat estimates commute costs" in faq
        assert "Why doesn't TollChat cover I-66 Outside the Beltway?" in faq
        assert "VDOT's public feeds do not include" in faq
        assert "Why is TollChat free?" in faq
        assert "production AI experience is comically hard to get" in faq
        assert "99.6%" in faq
        assert "93.1%" in faq
        assert "one frozen" in faq
        assert (
            "Pricing tools calculate its toll and take-home-pay figures in code" in faq
        )
        assert "best-effort estimates" in faq
        assert "not for financial planning, salary or job negotiations" in faq
        assert "330 origin-destination (OD) pairs" in faq
        assert "mean absolute error of $0.106, compared with $0.154" in faq
        assert "largest error was $8.05" in faq
        assert "two cumulative, non-identifying counters" in faq
        assert "These are sessions, not verified people" in faq
        assert "Responses storage disabled" in faq
        assert "abuse-monitoring logs" in faq
        assert "up to 30 days by default" in faq
        assert "retains Responses API data for at least 30 days" not in faq
        assert "tradeoff to keep TollChat free to use" in faq
        assert "https://developers.openai.com/api/docs/guides/your-data" in faq
        assert "OpenFreeMap" in faq
        assert "2026 Benevolent Clankers LLC" in faq
        assert "TollChat name and branding reserved" in faq
        assert "general information only" in faq
        favicon = urllib.request.urlopen(f"{base_url}/assets/favicon.png", timeout=2)
        favicon_bytes = favicon.read()
        assert favicon.headers.get_content_type() == "image/png"
        assert favicon_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert tuple(
            int.from_bytes(favicon_bytes[offset : offset + 4], "big")
            for offset in (16, 20)
        ) == (64, 64)
        privacy_response = urllib.request.urlopen(f"{base_url}/privacy.txt", timeout=2)
        assert privacy_response.headers.get_content_type() == "text/plain"
        privacy = privacy_response.read().decode()
        assert "TollChat privacy notice" in privacy
        assert "Starting a new chat does not change OpenAI's retention" in privacy
        assert "Responses storage disabled (`store=false`)" in privacy
        assert "does not use OpenAI's stored response state" in privacy
        assert "stateful OpenAI Responses API" not in privacy
        assert "Responses API application state for at least 30 days" not in privacy
        assert "abuse monitoring as a tradeoff to keep TollChat free to use" in privacy
        assert "https://developers.openai.com/api/docs/guides/your-data" in privacy
        assert "does not sell this data or use it for targeted advertising" in privacy
        assert "https://openfreemap.org/privacy/" in privacy
        terms_response = urllib.request.urlopen(f"{base_url}/terms.txt", timeout=2)
        assert terms_response.headers.get_content_type() == "text/plain"
        terms = terms_response.read().decode()
        assert "TollChat terms" in terms
        assert "not a navigation or emergency service" in terms
        assert "provided as is and as available" in terms
        assert "https://smarterroads.vdot.virginia.gov/termsOfService" in terms
        assert "does not attach the credential to traces or logs" in faq
        estimates = json.load(
            urllib.request.urlopen(
                f"{base_url}/assets/commute-estimates.json", timeout=2
            )
        )
        assert [item["id"] for item in estimates["estimates"]] == [
            "dumfries",
            "springfield-franconia",
            "leesburg",
            "i66-west",
        ]
        for path in (
            "/assets/commute-map.mjs",
            "/assets/commute-routes.mjs",
            "/assets/coverage-locations.json",
            "/assets/maplibre-gl-6.0.0/maplibre-gl.css",
            "/assets/maplibre-gl-6.0.0/maplibre-gl.mjs",
            "/assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs",
            "/assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs",
        ):
            assert urllib.request.urlopen(f"{base_url}{path}", timeout=2).status == 200
        coverage_locations = json.load(
            urllib.request.urlopen(
                f"{base_url}/assets/coverage-locations.json", timeout=2
            )
        )
        assert len(coverage_locations["locations"]) == 103
        assert (
            sum(len(location["points"]) for location in coverage_locations["locations"])
            == 220
        )
        csp = page.headers["Content-Security-Policy"]
        assert "img-src 'self' data:" in csp
        assert "connect-src 'self' https://tiles.openfreemap.org" in csp
        assert "worker-src 'self' blob:" in csp

        response = _post(
            f"{base_url}/api/chat",
            {"session_id": "browser", "message": "hello 👋"},
        )
        assert response.headers.get_content_type() == "application/x-ndjson"
        events = [json.loads(line) for line in response]
        assert events[1]["text_delta"] == "1: hello 👋 👋"
        assert events[-1]["final"]["text"].startswith("## Price")

        with pytest.raises(urllib.error.HTTPError) as foreign_reset:
            _post(
                f"{base_url}/api/reset",
                {"session_id": "browser"},
                origin="https://evil.example",
            )
        assert foreign_reset.value.code == 403
        response = _post(
            f"{base_url}/api/chat",
            {"session_id": "browser", "message": "still here"},
        )
        events = [json.loads(line) for line in response]
        assert events[1]["text_delta"].startswith("1:")

        reset = _post(f"{base_url}/api/reset", {"session_id": "browser"})
        assert json.load(reset) == {"ok": True}
        assert len(factory.agents) == 1

        with pytest.raises(urllib.error.HTTPError) as invalid:
            _post(
                f"{base_url}/api/chat",
                {"session_id": "bad/id", "message": "hello"},
            )
        assert invalid.value.code == 400
        assert json.load(invalid.value) == {"error": "invalid session id"}

        for origin, content_type, expected_status in (
            ("https://evil.example", "application/json", 403),
            (base_url, "text/plain", 415),
            (None, "application/json", 403),
        ):
            with pytest.raises(urllib.error.HTTPError) as rejected:
                _post(
                    f"{base_url}/api/chat",
                    {"session_id": "blocked", "message": "do not run"},
                    origin=origin,
                    content_type=content_type,
                )
            assert rejected.value.code == expected_status
        assert len(factory.agents) == 1
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _post(
    url, body, *, origin: str | None = "same-origin", content_type="application/json"
):
    if origin == "same-origin":
        origin = url.removesuffix("/api/chat").removesuffix("/api/reset")
    headers = {"Content-Type": content_type}
    if origin is not None:
        headers["Origin"] = origin
    return urllib.request.urlopen(
        urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        ),
        timeout=2,
    )
