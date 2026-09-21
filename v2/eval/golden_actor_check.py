"""Live actor checks against scripted development answers, never application scores."""

from __future__ import annotations

import argparse
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from strands_evals.types.simulation import ActorResponse

from eval import golden
from eval import golden_run as run


def check(example: golden.Example, trial: int, journal: run.Journal) -> run.Attempt:
    case = next(c for c in golden.load_cases() if c.id == example.case_id)
    turns = list(example.turns)
    # The reference answer invites a different origin; this profile must decline it.
    if case.id == "unsupported-origin":
        turns.append(
            golden.Turn(
                user="I mean downtown Baltimore, Maryland.",
                response="That exact Baltimore trip is outside the supported catalog, so I cannot price it.",
                calls=[],
            )
        )
    row = run.Attempt(id=f"{case.id}-{trial}", case_id=case.id, trial=trial)
    journal.append({"event": "attempt_started", **row.model_dump()})
    try:
        with journal.lock:
            model = journal.model(
                run.build_eval_model(), "actor", row, case.actor.max_turns * 3
            )
        actor = golden.make_actor(case, model)
        message = case.prompt
        replay = golden.Replay(case)
        for index, turn in enumerate(turns):
            if case.id == "unsupported-origin" and index == 1:
                if "baltimore" not in message.casefold():
                    raise run.StopRun("actor_profile_mismatch")
            row.turns.append(
                golden.Turn(user=message, response=turn.response, calls=[])
            )
            for call in turn.calls:
                replay.call(call.name, call.input, [t.user for t in row.turns])
            response = cast(ActorResponse, actor.act(turn.response).structured_output)
            row.actor_replies.append(
                {
                    "stop": response.stop,
                    "message": response.message,
                    "stop_reason": response.stop_reason,
                }
            )
            next_message = run.actor_message(response)
            if index == len(turns) - 1:
                if next_message is not None:
                    raise run.StopRun("actor_unnecessary_followup")
            elif next_message is None:
                raise run.StopRun("actor_premature_stop")
            else:
                message = next_message
        if not row.measurements or any(not m.complete for m in row.measurements):
            raise run.StopRun("actor_missing_usage")
        row.status = "scored"
    except Exception as error:
        row.status = "infrastructure"
        row.error = (
            str(error)
            if isinstance(error, (run.StopRun, ValueError))
            else type(error).__name__
        )
    journal.append({"event": "actor_check", **row.model_dump()})
    print(f"{row.id}: {row.error or 'valid scripted exchange'}", flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-spend-usd", type=float, required=True)
    args = parser.parse_args()
    cases = golden.load_cases()
    identity = run.identity(cases)
    examples = [e for e in run.development_examples() if e.label == "good"]
    journal = run.Journal(args.output, 25, args.prior_spend_usd)
    manifest = {
        "mode": "actor-check",
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "identity": identity,
        "prior_spend_usd": args.prior_spend_usd,
        "budget_usd": journal.limit,
        "workers": 4,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(check, example, trial, journal)
            for example in examples
            for trial in (1, 2, 3)
        ]
        rows = [future.result() for future in futures]
    events = [
        json.loads(line)
        for line in (args.output / "events.jsonl").read_text().splitlines()
    ]
    report = {
        "warning": "Scripted development answers; actor checks only, not application quality or release qualification. Human actor review remains required.",
        "expected_trials": len(examples) * 3,
        "valid_trials": sum(r.status == "scored" for r in rows),
        "rows": [r.model_dump() for r in rows],
        "cost_usd": journal.spent - args.prior_spend_usd,
        "unknown_usage": journal.unknown_usage,
        "evidence_sha256": golden.digest({"manifest": manifest, "events": events}),
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Actor checks: {report['valid_trials']}/{report['expected_trials']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
