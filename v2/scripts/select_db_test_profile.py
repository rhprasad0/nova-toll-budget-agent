"""Select disposable database coverage conservatively from an explicit Git range."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

FULL_PREFIXES = (
    "v2/db/",
    "v2/oracle/",
    "v2/tests/",
    "v2/scripts/",
    "v2/infra/",
    "infra/",
    ".github/",
)
FULL_FILES = {"v2/pyproject.toml", "v2/uv.lock"}


def select_profile(
    repo: Path, *, event: str, ref: str, base: str, head: str
) -> tuple[str, str]:
    """Return the coverage profile and a reason; uncertain comparisons run full."""
    if ref.startswith("refs/tags/"):
        return "full", "tag validation"
    if event == "push" and ref == "refs/heads/main":
        return "fast", "main push; delivery independently runs full coverage"
    if event not in {"pull_request", "merge_group"}:
        return "full", "unrecognized event or ref"
    if not base or not head or set(base) == {"0"} or set(head) == {"0"}:
        return "full", "missing comparison commit"
    try:
        # Resolve commits first: option-like input must never become a Git option.
        commits = [
            subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "--verify",
                    "--end-of-options",
                    f"{value}^{{commit}}",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            .stdout.strip()
            .decode("ascii")
            for value in (base, head)
        ]
        paths = subprocess.run(
            ["git", "diff", "--name-only", "-z", "--no-renames", *commits, "--"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return "full", "comparison unavailable"
    for raw_path in paths:
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path in FULL_FILES or path.startswith(FULL_PREFIXES):
            return "full", "database-sensitive paths changed"
    return "fast", "comparison contains no database-sensitive changes"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("event", "ref", "base", "head"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    profile, reason = select_profile(
        Path(__file__).resolve().parents[2],
        event=str(args.event),
        ref=str(args.ref),
        base=str(args.base),
        head=str(args.head),
    )
    print(f"Database profile: {profile} ({reason})", file=sys.stderr)
    print(profile)


if __name__ == "__main__":
    main()
