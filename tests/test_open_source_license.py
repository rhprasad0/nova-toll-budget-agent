"""Keep the repository license and public copyright notice aligned."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_apache_license_is_complete_and_publicly_disclosed() -> None:
    license_text = (ROOT / "LICENSE").read_text()
    readme = (ROOT / "README.md").read_text()
    site = (ROOT / "site" / "preview.html").read_text()

    for heading in (
        "Apache License\n                           Version 2.0",
        "2. Grant of Copyright License.",
        "3. Grant of Patent License.",
        "6. Trademarks.",
    ):
        assert heading in license_text

    assert "## License" in readme
    assert "[Apache License 2.0](LICENSE)" in readme
    assert "Copyright 2026 Benevolent Clankers LLC" in readme
    assert "TollChat name and branding" in readme
    assert "Third-party code, assets, and data" in readme

    assert "Apache-2.0" in site
    assert "TollChat name and branding reserved" in site
    assert "All rights reserved" not in site
