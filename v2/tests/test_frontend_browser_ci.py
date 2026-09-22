"""Browser CI skips unrelated diffs and runs when its base cannot be resolved."""

import os
import subprocess
from pathlib import Path

import yaml


def test_browser_change_selection(tmp_path: Path) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).parents[2] / ".github/workflows/ci.yml").read_text()
    )
    select = next(
        step["run"]
        for step in workflow["jobs"]["frontend-browser"]["steps"]
        if step.get("id") == "changes"
    )

    def git(*args: str) -> str:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Browser CI test",
                "-c",
                "user.email=browser-ci@example.test",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            cwd=tmp_path,
            text=True,
        ).strip()

    git("init", "-q")
    git("commit", "--allow-empty", "-qm", "base")
    base = git("rev-parse", "HEAD")
    for filename, expected in (
        ("README.md", False),
        ("v2/agent/assets/chat.css", True),
        ("v2/tests/frontend_e2e_browser.cjs", True),
        ("v2/tests/fixtures/costs-production.json", True),
        ("v2/package-lock.json", True),
        (".github/workflows/ci.yml", True),
        ("v2/lambdas/loader/handler.py", False),
    ):
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("change\n")
        git("add", filename)
        git("commit", "-qm", "change")
        output = tmp_path / "output"
        for ref, selected in ((base, expected), ("", True), ("0" * 40, True)):
            output.write_text("")
            subprocess.run(
                ["bash", "-euo", "pipefail", "-c", select],
                cwd=tmp_path,
                env={**os.environ, "BASE_REF": ref, "GITHUB_OUTPUT": str(output)},
                check=True,
            )
            assert output.read_text() == f"frontend={str(selected).lower()}\n"
        base = git("rev-parse", "HEAD")
