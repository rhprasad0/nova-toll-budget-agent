"""Static integration checks for safe assistant Markdown rendering."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_IT = (
    ROOT / "site" / "assets" / "markdown-it-15.0.0" / "markdown-it.esm.min.mjs"
)
LICENSE = ROOT / "site" / "assets" / "markdown-it-15.0.0" / "LICENSE.txt"
TERRAFORM = ROOT / "infra" / "site.tf"


def test_pinned_markdown_assets_are_licensed_and_published() -> None:
    assert sha256(MARKDOWN_IT.read_bytes()).hexdigest() == (
        "eb0a6cb2beb08326ea4d3e0e3b25ac72c1e6f119a619d9bbe061e72000ffa118"
    )
    assert LICENSE.read_text().startswith(
        "Copyright (c) 2014 Vitaly Puzrin, Alex Kocharin."
    )
    terraform = TERRAFORM.read_text()
    assert '"assets/markdown-it-15.0.0/markdown-it.esm.min.mjs"' in terraform
    assert '"assets/chat-markdown-v1.mjs"' in terraform
    assert "depends_on = [aws_s3_object.site_assets]" in terraform
    assert "compress               = true" in terraform
