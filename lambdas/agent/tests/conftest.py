import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "tools"

# catalog.py/sql_tool.py/route_tool.py ship flat (no package __init__), so
# tests import them as siblings, same as the loader/fetcher suites.
sys.path.insert(0, str(AGENT_DIR))
