import importlib.util
import sys
from pathlib import Path

LOADER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = LOADER_DIR.parent.parent

# handler.py/parse_csv.py/parse_xml.py are siblings in a flat deployment
# zip (no package __init__), so tests import them the same way.
sys.path.insert(0, str(LOADER_DIR))

SAMPLE_DATA_DIR = REPO_ROOT / "vdot_sample_data"

# lambdas/fetcher/handler.py shares the same AWS-entrypoint-convention
# basename. Both Lambdas' conftest.py add their own dir to sys.path, so a
# bare `import handler` would collide across the two test suites depending
# on collection order. Load loader's handler.py under a private name instead.
_spec = importlib.util.spec_from_file_location(
    "loader_handler", LOADER_DIR / "handler.py"
)
assert _spec and _spec.loader
loader_handler = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("loader_handler", loader_handler)
_spec.loader.exec_module(loader_handler)
