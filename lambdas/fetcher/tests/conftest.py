import sys
from pathlib import Path

# handler.py ships flat in the Lambda zip (no package init) — add its
# directory to sys.path so tests can `import handler` directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
