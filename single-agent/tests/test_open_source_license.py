"""Keep the public Apache-2.0 notice aligned."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_apache_license_notice() -> None:
    license_text = (ROOT.parent / "LICENSE").read_text()
    readme = (ROOT / "README.md").read_text()
    site = (ROOT / "site" / "preview.html").read_text()

    assert "Apache License\n                           Version 2.0" in license_text
    assert "[Apache License 2.0](../LICENSE)" in readme
    assert "Apache-2.0" in site
    assert "All rights reserved" not in site
