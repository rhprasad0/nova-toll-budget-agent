import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOADER_DIR = REPO_ROOT / "lambdas" / "loader"

# parse_csv.py/parse_xml.py are siblings in the loader's flat deployment zip
# (no package __init__) -- reuse them the same way lambdas/loader/tests does,
# rather than writing a second feed parser.
sys.path.insert(0, str(LOADER_DIR))

SAMPLE_DATA_DIR = REPO_ROOT / "vdot_sample_data"
