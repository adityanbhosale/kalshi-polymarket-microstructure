"""Make `book` and `fees` importable from the batch_counterfactual/ package dir."""

import sys
from pathlib import Path

BC_DIR = Path(__file__).resolve().parents[1]
if str(BC_DIR) not in sys.path:
    sys.path.insert(0, str(BC_DIR))
