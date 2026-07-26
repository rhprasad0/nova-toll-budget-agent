import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(AGENT_DIR))
