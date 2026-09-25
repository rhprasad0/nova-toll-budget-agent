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
    # Ask explicitly: an optional invitation after refusal needs no reply.
    if case.contract_version < 2 and case.id == "unsupported-origin":
        turns[0] = turns[0].model_copy(
            update={
                "response": "Downtown Baltimore is outside the supported origin list. I cannot price that whole trip. Which supported Greenway entry would you like instead?"
            }
        )
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
        row.failure_phase = "actor"
        with journal.lock:
            model = journal.model(
                run.build_eval_model(), "actor", row, case.actor.max_turns * 3
            )
        actor = golden.make_actor(case, model)
        message = case.prompt
        replay = golden.Replay(case)
        for index, turn in enumerate(turns):
            if (
                case.id == "unsupported-origin"
                and case.contract_version < 2
                and index == 1
                and "baltimore" not in message.casefold()
            ):
                raise run.StopRun("actor_profile_mismatch")
            row.turns.append(
                golden.Turn(user=message, response=turn.response, calls=[])
            )
            for call in turn.calls:
                row.turns[-1].calls.append(
                    replay.call(call.name, call.input, [t.user for t in row.turns])
                )
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
            raise run.StopRun("missing_usage")
        if case.contract_version >= 2:
            row.failure_phase = "judge"
            with journal.lock:
                model = journal.model(run.build_eval_model(), "judge", row, 3)
            run.assess_outcome(
                case,
                row,
                model,
                f"Declared terminal objective: {case.terminal_objective}.\n{case.expected_assertion}",
                json.dumps([t.model_dump() for t in row.turns]),
            )
            row.verdicts.clear()  # Scripted assistant answers are not application trials.
            if row.actor_validity is None or row.actor_validity.status != "valid":
                raise run.StopRun("actor_profile_mismatch")
            if any(not m.complete for m in row.measurements):
                raise run.StopRun("missing_usage")
        row.status = "scored"
        row.failure_phase = None
    except Exception as error:
        row.status = "infrastructure"
        row.error = run.error_code(error)
        if case.contract_version >= 2 and (row.error or "").startswith("actor_"):
            row.status = "inconclusive"
            if row.actor_validity is None:
                row.actor_validity = run.ActorAssessment(
                    status="invalid", evidence=row.error or "actor_invalid"
                )
        row.failure_class = run.failure_class(row)
        if row.status == "infrastructure":
            with journal.lock:
                journal.stop_requested = True
    journal.append({"event": "actor_check", **row.model_dump()})
    print(f"{row.id}: {row.error or 'valid scripted exchange'}", flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-usd", type=float, required=True)
    parser.add_argument("--prior-run", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=16)
    args = parser.parse_args()
    cases = golden.load_cases()
    identity = run.identity(cases)
    passing: dict[str, golden.Example] = {}
    for example in run.development_examples():
        if (
            example.actor_validity == "valid"
            and example.expected is not None
            and all(example.expected.model_dump().values())
        ):
            passing.setdefault(example.case_id, example)
    examples = list(passing.values())
    prior, spent = run.prior_accounting(args.prior_run)
    journal = run.Journal(args.output, args.budget_usd, spent)
    manifest = {
        "mode": "actor-check",
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "identity": identity,
        "prior_run_id": prior["run_id"] if prior else None,
        "prior_spend_usd": spent,
        "budget_usd": journal.limit,
        "workers": args.workers,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
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
        "cost_usd": journal.spent - spent,
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
