"""Render a pending review packet from archived calibration reports; no approvals."""

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    lines = [
        "# Prompt experiment calibration review — 2.0.6",
        "",
        "**Pending human review. No application trials have run.**",
        "",
        "Both runs use evaluator semantics 2.0.6. A and B/C have distinct corpus",
        "digests because the existing identity includes the changed tool source files.",
        "Cases, fixtures, labels, grading code, actor/judge prompts and settings are identical.",
        "",
        "Approval would accept the recorded calibration limitations for the bounded local",
        "A/B/C experiment only; it would not approve production or change any verdict.",
        "",
    ]
    prior = json.loads((root / "calibration-a-2.0.6/manifest.json").read_text())[
        "prior_spend_usd"
    ]
    total = prior
    reference_runs = []
    for name in ("calibration-a-2.0.6", "calibration-bc-2.0.6"):
        directory = root / name
        report = json.loads((directory / "report.json").read_text())
        events = [
            json.loads(s) for s in (directory / "events.jsonl").read_text().splitlines()
        ]
        cost = sum(e["cost_usd"] for e in events if e["event"] == "model_finished")
        total += cost
        rows = report["rows"]
        reference_runs.append({r["id"]: r for r in rows})
        disagreement_count = sum(len(r["disagreements"]) for r in rows)
        lines.extend(
            [
                f"## {name}",
                "",
                f"- Complete: **{report['complete']}**; references: **{len(rows)}/{report['expected_examples']}**; measurement failures: **{report['measurement_failures']}**.",
                f"- Disagreements: **{disagreement_count} labels across {sum(bool(r['disagreements']) for r in rows)} references**; estimated cost: **${cost:.6f}**.",
                f"- Evidence SHA-256: `{report['evidence_sha256']}`.",
                f"- [Full report]({name}/report.json), [reference checklist]({name}/report.md), [raw journal]({name}/events.jsonl).",
                "",
                "| Criterion | Correct passes | Correct failures | Missed errors | False failures |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for criterion, matrix in report["confusion_matrices"].items():
            values = [
                matrix[k]
                for k in (
                    "expected_true_predicted_true",
                    "expected_false_predicted_false",
                    "expected_false_predicted_true",
                    "expected_true_predicted_false",
                )
            ]
            lines.append(f"| {criterion} | " + " | ".join(map(str, values)) + " |")
        lines.extend(
            [
                "",
                "Matrices compare judgments with authored labels, not independently adjudicated truth. They exclude actor-invalid/uncertain references; actor disagreements remain below.",
                "",
                "### New semantic controls",
                "",
                "| Control | Expected application verdicts | Measured application verdicts | Actor validity |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            if row["example"].startswith("semantic-"):
                expected = "/".join(
                    str(row["expected"][k]) for k in ("outcome", "grounding", "rules")
                )
                actual = "/".join(
                    str(row["verdicts"][k]["passed"])
                    for k in ("outcome", "grounding", "rules")
                )
                lines.append(
                    f"| {row['id']} | {expected} | {actual} | {row['actor_validity']['status']} |"
                )
        lines.extend(
            [
                "",
                "Verdict order: Outcome / Grounding / Rules. Positive controls preserve meaning; negative controls fabricate official proof or tax entitlement.",
                "",
            ]
        )
        for row in rows:
            if not row["disagreements"]:
                continue
            lines.extend([f"### {row['id']}", ""])
            for criterion in row["disagreements"]:
                if criterion == "actor_validity":
                    expected = row["expected_actor_validity"]
                    measured = row["actor_validity"]["status"]
                    evidence = row["actor_validity"]["evidence"]
                else:
                    expected = row["expected"][criterion]
                    measured = row["verdicts"][criterion]["passed"]
                    evidence = row["verdicts"][criterion]["evidence"]
                lines.extend(
                    [
                        f"**{criterion}: expected {expected}; measured {measured}.**",
                        "",
                        evidence,
                        "",
                    ]
                )
    first, second = reference_runs
    assert first.keys() == second.keys(), "Calibration reference sets differ"
    changed = 0
    for example_id, before in first.items():
        after = second[example_id]
        if not before["measurement_complete"] or not after["measurement_complete"]:
            continue
        changed += (
            any(
                before["verdicts"][key]["passed"] != after["verdicts"][key]["passed"]
                for key in ("outcome", "grounding", "rules")
            )
            or before["actor_validity"]["status"] != after["actor_validity"]["status"]
        )
    lines.extend(
        [
            "## Calibration repeat variability",
            "",
            f"**{changed} of {len(first)} references** received at least one different application-criterion or actor-validity judgment between the two calibrations. This measures judge variation on fixed references, not application-prompt performance. Interpret small downstream score changes cautiously.",
            "",
        ]
    )
    lines.extend(
        [
            "## Spending and decision",
            "",
            f"This revision costs **${total - prior:.6f}**; prior experiment spending is **${prior:.6f}**. Cumulative cost: **${total:.6f} of $15**; remaining estimated allowance: **${15 - total:.6f}**.",
            "",
            "Review both exact evidence digests and disagreements before approving application runs. The runner retains the human-review gate. This explicitly revised judging policy accepts semantic equivalence while retaining substantive checks. Existing labels and all historical results remain unchanged; four new development references test the revision. No application-prompt performance conclusion follows from calibration agreement.",
            "",
        ]
    )
    (root / "CALIBRATION-REVIEW-2.0.6.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
