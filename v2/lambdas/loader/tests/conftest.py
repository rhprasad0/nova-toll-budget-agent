import importlib.util
import sys
from pathlib import Path

LOADER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LOADER_DIR))

_spec = importlib.util.spec_from_file_location(
    "pricing_loader_handler", LOADER_DIR / "handler.py"
)
assert _spec and _spec.loader
loader_handler = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("pricing_loader_handler", loader_handler)
_spec.loader.exec_module(loader_handler)
