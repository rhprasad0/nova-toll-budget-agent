"""The compatibility adapter must fail closed without changing checked sources."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import check_workflows as checker


def test_compatibility_requires_original_source_and_existing_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    path = ".github/workflows/v2-development-migrations.yml"
    source = tmp_path / path
    source.parent.mkdir(parents=True)
    source.write_text("queue: max\n")
    diagnostic: checker.Diagnostic = {
        "filepath": "./" + path,
        "line": 1,
        "message": checker.QUEUE_MESSAGE,
    }
    assert checker.filter_workflow_diagnostics([diagnostic], [path]) == []
    assert "unused" in checker.filter_workflow_diagnostics([], [path])[0]
    source.write_text("queue: invalid\n")
    assert len(checker.filter_workflow_diagnostics([diagnostic], [path])) == 2
    assert (
        checker.filter_workflow_diagnostics([], [".github/workflows/example.yml"]) == []
    )
    unexpected: checker.Diagnostic = {**diagnostic, "message": 'unexpected key "typo"'}
    assert (
        'unexpected key "typo"'
        in checker.filter_workflow_diagnostics([unexpected], [path])[0]
    )


@pytest.mark.parametrize("workflow", [False, True])
def test_unused_shellcheck_directives_fail_without_writing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: bool
) -> None:
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    path = "sample.sh"
    source = tmp_path / path
    content = "#!/bin/bash\ntrue\n# Literal jq variable.\n# shellcheck disable=SC2016\nprintf '$variable'\n"
    source.write_text(content)

    def check_command(
        _command: Sequence[str], text: str | None = None
    ) -> list[checker.Diagnostic]:
        assert text is not None and "disable=SC2016" not in text
        assert text.count("\n") == content.count("\n")
        return [
            {
                "code": 2016,
                "message": "shellcheck reported issue in this script: SC2016:info:4:1: literal",
            }
        ]

    monkeypatch.setattr(checker, "check_command", check_command)
    assert checker.unused_directives(path, ["checker"], [], workflow=workflow) == []
    assert source.read_text() == content

    def no_diagnostics(
        _command: Sequence[str], _text: str | None = None
    ) -> list[checker.Diagnostic]:
        return []

    monkeypatch.setattr(checker, "check_command", no_diagnostics)
    assert checker.unused_directives(path, ["checker"], [], workflow=workflow) == [
        "sample.sh:4: unused ShellCheck exception SC2016"
    ]
    assert source.read_text() == content


@pytest.mark.parametrize(
    "prefix,workflow", [("#!/bin/bash\n", False), ("run: |\n", True)]
)
def test_file_leading_directives_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str, workflow: bool
) -> None:
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    source = tmp_path / "sample.sh"
    source.write_text(
        prefix + "# explanation\n# shellcheck disable=SC2016\nprintf '$variable'\n"
    )
    assert checker.unused_directives(
        "sample.sh", ["must-not-run"], [], workflow=workflow
    ) == ["sample.sh:3: file-leading ShellCheck exceptions are forbidden"]
