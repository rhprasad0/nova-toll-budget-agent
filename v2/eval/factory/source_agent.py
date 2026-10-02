"""Reuse the frozen replay protocol with source snapshots and locked installed deps."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from eval import golden
from eval import golden_run as run
from eval.artifact_agent import ArtifactAgent
from eval.factory.kit import CONTRACT, sha


class SourceAgent(ArtifactAgent):
    """Only bootstrap differs from an ARM64 deployment bundle; protocol is shared."""

    def __init__(
        self,
        bundle: Path,
        api_key: str,
        case: golden.GoldenCase,
        attempt: run.Attempt,
        journal: run.Journal,
        messages: list[str],
    ) -> None:
        self.case, self.attempt, self.journal = case, attempt, journal
        self.messages = messages
        self.replay = golden.Replay(case)
        self.reserved = None
        self.calls = 0
        self.buffer = b""
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("source_worker.py")),
                str(bundle.resolve()),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "OTEL_SDK_DISABLED": "true"},
            cwd=bundle,
        )
        try:
            if self.receive() != {"event": "ready"}:
                raise run.StopRun("source_bootstrap")
            self.send(
                {
                    "event": "init",
                    "api_key": api_key,
                    "points": json.loads(
                        (golden.ROOT / "prompt-points.json").read_text()
                    ),
                    "dates": {"current": case.frozen_time.date().isoformat()},
                }
            )
            value = self.receive()
            if value.get("event") != "identity":
                raise run.StopRun("source_identity")
            self.identity = value["identity"]
            if (
                self.identity["model_config"]
                != CONTRACT["settings"]["application_model_config"]
            ):
                raise run.StopRun("source_model_config")
            for name, hashed in self.identity["imported_files"].items():
                path = (bundle / name).resolve()
                if (
                    not path.is_relative_to(bundle.resolve())
                    or sha(path.read_bytes()) != hashed
                ):
                    raise run.StopRun("source_import_hash")
            journal.append(
                {
                    "event": "source_identity",
                    "attempt": attempt.id,
                    "identity": self.identity,
                }
            )
        except BaseException:
            self.close()
            raise
