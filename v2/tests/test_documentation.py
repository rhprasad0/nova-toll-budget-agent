"""Keep Markdown from restating code: each check fails with the fix to make."""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNAL = "v2/journal/pages/"
FACTORY_DEFINITIONS = ("factory/agents/", "factory/rubrics/")


def tracked_markdown() -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "*.md"], cwd=REPO_ROOT, text=True
    )
    return [path for path in output.splitlines() if (REPO_ROOT / path).is_file()]


def test_markdown_files_only_shrink() -> None:
    """New rules belong in checks; journal pages and factory definitions may grow."""
    documents = [
        path
        for path in tracked_markdown()
        if not path.startswith((JOURNAL, *FACTORY_DEFINITIONS))
    ]
    assert len(documents) <= 22, (
        "Do not add Markdown files. Write a deterministic check whose error names "
        "the fix (CLAUDE.md), or delete a stale document to make room."
    )
    assert len(documents) == 22, (
        f"A Markdown file was removed: lower this limit to {len(documents)}."
    )


def anchors(text: str) -> set[str]:
    """GitHub heading anchors, including -1, -2 suffixes for repeats."""
    seen: dict[str, int] = {}
    result: set[str] = set()
    for heading in re.findall(
        r"^#{1,6} +(.+?) *#* *$", strip_fences(text), re.MULTILINE
    ):
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", plain).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def strip_fences(text: str) -> str:
    return re.sub(r"^(```|~~~).*?^\1", "", text, flags=re.MULTILINE | re.DOTALL)


def strip_code(text: str) -> str:
    return re.sub(r"`[^`\n]*`", "", strip_fences(text))


def test_relative_links_and_anchors_resolve() -> None:
    broken: list[str] = []
    for path in tracked_markdown():
        source = REPO_ROOT / path
        for target in re.findall(r"\]\(([^)\s]+)\)", strip_code(source.read_text())):
            if re.match(r"[a-z]+:", target):
                continue
            file, _, anchor = target.partition("#")
            linked = (source.parent / file).resolve() if file else source
            if not linked.exists():
                broken.append(f"{path}: {target} (no such file)")
            elif (
                anchor
                and linked.suffix == ".md"
                and anchor not in anchors(linked.read_text())
            ):
                broken.append(f"{path}: {target} (no such heading)")
    assert not broken, "Fix or remove these Markdown links:\n" + "\n".join(broken)


def test_journal_pages_are_mondays_linked_from_the_index() -> None:
    index = (REPO_ROOT / "v2/journal/EXPERIMENT_JOURNAL.md").read_text()
    for path in tracked_markdown():
        if path.startswith(JOURNAL):
            name = Path(path).stem
            assert date.fromisoformat(name).weekday() == 0, (
                f"Rename {path} to the Monday that starts its week."
            )
            assert f"](pages/{name}.md)" in index, (
                f"Add a row linking pages/{name}.md to v2/journal/EXPERIMENT_JOURNAL.md."
            )


def test_skill_names_an_existing_workflow_step() -> None:
    workflow = ".github/workflows/v2-development-connectivity-verification.yml"
    skill = (REPO_ROOT / ".claude/skills/query-dev-postgres/SKILL.md").read_text()
    match = re.search(r"read the `([^`]+)` step in\s+`([^`]+)`", skill)
    assert match is not None and match.group(2) == workflow
    name = " ".join(match.group(1).split())
    steps = {
        step.get("name")
        for job in yaml.safe_load((REPO_ROOT / workflow).read_text())["jobs"].values()
        for step in job.get("steps", [])
    }
    assert name in steps, (
        f"Update the step name in the query-dev-postgres skill: {name!r}"
    )


def test_anchors_follow_github_slugs() -> None:
    headings = (
        "## The `pricing` schema\n## run_db_tests.sh\n## A *b* [c](d.md)\n## A b c\n"
    )
    assert anchors(headings) == {
        "the-pricing-schema",
        "run_db_testssh",
        "a-b-c",
        "a-b-c-1",
    }
