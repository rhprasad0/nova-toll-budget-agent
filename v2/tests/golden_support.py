"""Explicit, test-only inputs for replay and runner regression checks."""

from pathlib import Path

from eval import golden

ROOT = Path(__file__).with_name("fixtures") / "golden"


def case(number: int) -> golden.GoldenCase:
    return next(c for c in golden.load_cases(ROOT) if c.number == number)
