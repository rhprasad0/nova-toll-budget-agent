"""Offline check of Codex's package tree, JavaScript runtime and nested file read."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any


def main() -> None:
    codex = shutil.which("codex")
    assert codex is not None, "Codex is missing"
    assert shutil.which("ps") is not None, "Codex daemon requires ps (procps)"
    package = Path(codex).resolve().parent.parent
    assert (package / "codex-package.json").is_file(), "Codex package is incomplete"
    assert not any(p.is_symlink() and p.is_dir() for p in package.rglob("*")), (
        "Codex daemon rejects directory links; install the package in its own directory"
    )
    host = subprocess.Popen(
        [str(Path(codex).with_name("codex-code-mode-host"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    reader, writer = host.stdout, host.stdin
    assert reader is not None and writer is not None

    def send(message: dict[str, Any]) -> None:
        payload = json.dumps(message).encode()
        writer.write(struct.pack("<I", len(payload)) + payload)
        writer.flush()

    def receive() -> dict[str, Any]:
        header = reader.read(4)
        assert len(header) == 4, "Codex runtime closed its connection"
        size = struct.unpack("<I", header)[0]
        assert 0 < size <= 64 * 1024 * 1024
        return json.loads(reader.read(size))

    try:
        send(
            {
                "type": "connection/hello",
                "supportedVersions": [1],
                "requiredCapabilities": [],
                "optionalCapabilities": [],
            }
        )
        assert receive()["type"] == "connection/ready"
        send(
            {
                "type": "operation/request",
                "id": 1,
                "request": {"method": "session/open", "sessionId": "container-check"},
            }
        )
        assert receive()["result"]["value"]["type"] == "session/ready"
        send(
            {
                "type": "operation/request",
                "id": 2,
                "request": {
                    "method": "session/execute",
                    "sessionId": "container-check",
                    "request": {
                        "tool_call_id": "container-check",
                        "enabled_tools": [
                            {
                                "name": "read_database_procedure",
                                "tool_name": {
                                    "name": "read_database_procedure",
                                    "namespace": None,
                                },
                                "description": "Read the public factory database procedure.",
                                "kind": "function",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {},
                                    "additionalProperties": False,
                                },
                                "output_schema": None,
                            }
                        ],
                        "source": 'const procedure = await tools.read_database_procedure({}); text(procedure.startsWith("# Development data for eval authoring"));',
                        "yield_time_ms": 10000,
                        "max_output_tokens": 200,
                    },
                },
            }
        )
        calls = 0
        while True:
            message = receive()
            if message["type"] == "delegate/request":
                invocation = message["request"]["invocation"]
                assert invocation["tool_name"]["name"] == "read_database_procedure"
                assert invocation["input"] == {}
                calls += 1
                send(
                    {
                        "type": "delegate/response",
                        "id": message["id"],
                        "result": {
                            "status": "ok",
                            "value": {
                                "type": "tool/result",
                                "result": (
                                    Path(__file__).parent / "DATABASE.md"
                                ).read_text(),
                            },
                        },
                    }
                )
            elif message["type"] == "execute/initialResponse":
                result = message["result"]["value"]["Result"]
                assert result["error_text"] is None
                assert result["content_items"] == [
                    {"type": "input_text", "text": "true"}
                ]
                assert calls == 1
                break
        print("Codex JavaScript runtime and nested factory-file read: passed")
    finally:
        host.terminate()
        host.wait(timeout=5)


if __name__ == "__main__":
    main()
