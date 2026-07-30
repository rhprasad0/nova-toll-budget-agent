# Placeholder only — lets `terraform plan` create Lambda functions before
# WP2 (toll-fetcher) / WP3 (toll-loader) ship real code. WP4's build script
# overrides the deployment package via -var fetcher_package_path / loader_package_path.
from typing import NoReturn


def lambda_handler(_event: object, _context: object) -> NoReturn:
    raise RuntimeError("placeholder handler — real deployment package not yet built")
