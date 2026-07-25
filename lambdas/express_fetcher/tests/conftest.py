import importlib.util
import sys
from pathlib import Path

EXPRESS_FETCHER_DIR = Path(__file__).resolve().parent.parent

# handler.py ships flat in the Lambda zip (no package init). A bare
# `import handler` would collide with lambdas/fetcher/tests/test_handler.py's
# own bare `import handler` depending on collection order -- load this one
# under a private name instead, same trick as lambdas/loader/tests/conftest.py.
_spec = importlib.util.spec_from_file_location(
    "express_fetcher_handler", EXPRESS_FETCHER_DIR / "handler.py"
)
assert _spec and _spec.loader
express_fetcher_handler = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("express_fetcher_handler", express_fetcher_handler)
_spec.loader.exec_module(express_fetcher_handler)
