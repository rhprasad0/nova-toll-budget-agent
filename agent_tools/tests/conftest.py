import sys
from pathlib import Path

AGENT_TOOLS_DIR = Path(__file__).resolve().parent.parent

# i66_route.py/i95_route.py are flat siblings (no package __init__), matching
# the lambdas/*/tests/ convention -- distinct basenames here, so a plain
# sys.path insert is enough (no importlib private-name trick needed).
sys.path.insert(0, str(AGENT_TOOLS_DIR))
