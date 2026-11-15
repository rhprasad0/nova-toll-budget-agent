import json
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from factory.host import dispatcher, trace


def git(*args: str | Path) -> str:
    return subprocess.run(["git", *map(str, args)], check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(
        trace, "ENDPOINT", f"http://127.0.0.1:{server.server_address[1]}/v1/traces"
    )
    yield received
    server.shutdown()


def test_a_round_span_is_posted_as_otlp_json_under_its_parent(
    collector: list[dict[str, Any]],
) -> None:
    trace_id, root, span = trace.new_id(16), trace.new_id(8), trace.new_id(8)
    assert trace.send(trace_id, span, root, "round", 1, 2,
                      {"session.id": "s", "factory.round": 1, "factory.fix": False})  # fmt: skip
    posted = collector[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert (posted["traceId"], posted["spanId"], posted["parentSpanId"]) == (
        trace_id,
        span,
        root,
    )
    assert (posted["kind"], posted["startTimeUnixNano"], posted["endTimeUnixNano"]) == (
        1,
        "1",
        "2",
    )
    assert {a["key"]: a["value"] for a in posted["attributes"]} == {
        "session.id": {"stringValue": "s"},
        "factory.round": {"intValue": "1"},
        "factory.fix": {"boolValue": False},
    }
    assert trace.traceparent(trace_id, span) == f"00-{trace_id}-{span}-01"


def test_a_lost_collector_never_fails_the_work_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trace, "ENDPOINT", "http://127.0.0.1:9/v1/traces")
    assert not trace.send(trace.new_id(16), trace.new_id(8), None, "round", 1, 2, {})


def test_the_workers_bundle_lands_in_a_fresh_host_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = tmp_path / "seed"
    git("init", "--quiet", "--initial-branch=main", seed)
    git("-C", seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet",
        "--allow-empty", "-m", "base")  # fmt: skip
    origin = tmp_path / "origin.git"
    git("clone", "--quiet", "--bare", seed, origin)
    monkeypatch.setattr(dispatcher, "ORIGIN", origin)
    worker = tmp_path / "worker"
    git("clone", "--quiet", origin, worker)
    git("-C", worker, "checkout", "--quiet", "-b", "factory/issue-7")
    (worker / "fix.txt").write_text("fixed\n")
    git("-C", worker, "add", "fix.txt")
    git(
        "-C",
        worker,
        "-c",
        "user.name=w",
        "-c",
        "user.email=w@w",
        "commit",
        "--quiet",
        "-m",
        "fix",
    )
    git("-C", worker, "branch", "--force", "main", "factory/issue-7")
    bundle = tmp_path / "work.bundle"
    git("-C", worker, "bundle", "create", "--quiet", bundle, "refs/heads/factory/issue-7",
        "refs/heads/main", "^refs/remotes/origin/main")  # fmt: skip
    clean = dispatcher.import_bundle(bundle, "factory/issue-7", tmp_path / "clean")
    assert git("-C", clean, "log", "--format=%s", "main..factory/issue-7") == "fix"
    assert git("-C", clean, "log", "--format=%s", "main") == "base"


def test_the_final_result_is_the_last_result_event(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"type": "system", "session_id": "s"}),
        "not json",
        json.dumps({"type": "result", "result": "first"}),
        json.dumps({"type": "result", "result": "NEEDS CLARIFICATION\nWhich route?", "session_id": "s"}),
    ]))  # fmt: skip
    assert dispatcher.final_result(transcript)["result"].startswith(
        "NEEDS CLARIFICATION"
    )
    transcript.write_text("")
    assert dispatcher.final_result(transcript) == {}
