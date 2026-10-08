"""Recorded repetition counts shared by execution, reporting and comparisons."""

from typing import Any


def trial_numbers(corpus: dict[str, Any]) -> range:
    count = corpus.get("trials_per_case")
    if type(count) is not int or count not in (1, 3):
        raise ValueError("unsupported trials_per_case; expected 1 or 3")
    return range(1, count + 1)


def report_trials(identity: dict[str, Any]) -> range:
    version = identity["harness_version"]
    supported = {
        *(f"1.0.{n}" for n in range(5)),
        "1.1.0",
        "1.2.0",
        "1.2.1",
        "1.2.10",
        *(f"2.0.{n}" for n in range(14)),
        "2.1.0",
        "2.1.1",
        "2.1.2",
        "2.2.0",
        "2.4.0",
        "2.5.0",
        "2.5.1",
        "2.5.2",
        "2.5.3",
        "2.5.4",
        "2.5.5",
        "2.5.6",
        "2.5.7",
        "2.5.8",
        "2.5.9",
        "2.5.10",
        "2.5.11",
        "2.5.12",
        "2.5.13",
        "2.5.14",
        "2.5.15",
        "2.5.16",
        "2.5.17",
        *(f"2.3.{n}" for n in range(29)),
    }
    if version not in supported:
        raise ValueError(f"unsupported harness contract: {version}")
    if version in {
        "2.4.0",
        "2.5.0",
        "2.5.1",
        "2.5.2",
        "2.5.3",
        "2.5.4",
        "2.5.5",
        "2.5.6",
        "2.5.7",
        "2.5.8",
        "2.5.9",
        "2.5.10",
        "2.5.11",
        "2.5.12",
        "2.5.13",
        "2.5.14",
        "2.5.15",
        "2.5.16",
        "2.5.17",
    } and not isinstance(identity.get("execution"), dict):
        raise ValueError("missing training execution contract")
    trials = trial_numbers(
        identity["execution"]
        if version
        in {
            "2.4.0",
            "2.5.0",
            "2.5.1",
            "2.5.2",
            "2.5.3",
            "2.5.4",
            "2.5.5",
            "2.5.6",
            "2.5.7",
            "2.5.8",
            "2.5.9",
            "2.5.10",
            "2.5.11",
            "2.5.12",
            "2.5.13",
            "2.5.14",
            "2.5.15",
            "2.5.16",
            "2.5.17",
        }
        else identity["corpus"]
    )
    if tuple(map(int, version.split("."))) < (2, 3, 21) and len(trials) != 3:
        raise ValueError("historical harness contracts require three trials")
    return trials
