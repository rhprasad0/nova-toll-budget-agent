import importlib.util
import sys
from pathlib import Path

PUBLISHER_DIR = Path(__file__).resolve().parent.parent
V2_ROOT = PUBLISHER_DIR.parents[1]
sys.path.insert(0, str(V2_ROOT))
sys.path.insert(0, str(PUBLISHER_DIR))

_spec = importlib.util.spec_from_file_location(
    "report_publisher_handler", PUBLISHER_DIR / "handler.py"
)
assert _spec and _spec.loader
publisher_handler = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("report_publisher_handler", publisher_handler)
_spec.loader.exec_module(publisher_handler)
