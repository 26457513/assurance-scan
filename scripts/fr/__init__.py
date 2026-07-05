"""FR-driven dashboard rendering package.

Imported by generate_dashboard.py at the bottom of the file (after all
function definitions). fr/ modules import shared utilities from
generate_dashboard via:
    from generate_dashboard import load_json, short_text, sev_badde, ...
"""
import sys
from pathlib import Path

_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in sys.path:
    sys.path.insert(0, _parent)
