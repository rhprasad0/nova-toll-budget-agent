"""Static integration checks for safe assistant Markdown rendering."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "index.html"
RENDERER = ROOT / "site" / "assets" / "chat-markdown-v1.mjs"
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
    assert "default_cache_behavior {" in terraform
    assert "compress               = true" in terraform


def test_renderer_documents_and_enforces_the_untrusted_markdown_subset() -> None:
    renderer = RENDERER.read_text()
    assert "Assistant Markdown contract" in renderer
    assert "html: false" in renderer
    assert "linkify: false" in renderer
    assert "renderer.rules.image" in renderer
    assert 'new URL(url).protocol === "https:"' in renderer
    assert 'token.attrSet("target", "_blank")' in renderer
    assert 'token.attrSet("rel", "noopener noreferrer")' in renderer


def test_chat_renders_only_assistant_messages_as_markdown() -> None:
    page = SITE.read_text()
    assert 'await import("/assets/chat-markdown-v1.mjs")' in page
    assert "if (!config.chatEnabled) return;" in page
    assert 'document.createElement(kind === "user" ? "p" : "article")' in page
    assert "message.textContent = text;" in page
    assert "message.innerHTML = renderAssistantMarkdown(text);" in page
    assert ".chat-message.user { align-self: flex-end;" in page
    assert ".chat-message pre, .chat-message table {" in page
