import importlib.util
import sys
from pathlib import Path

ROLLUP_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "agent_usage_rollup_handler", ROLLUP_DIR / "handler.py"
)
assert _spec and _spec.loader
rollup_handler = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("agent_usage_rollup_handler", rollup_handler)
_spec.loader.exec_module(rollup_handler)
