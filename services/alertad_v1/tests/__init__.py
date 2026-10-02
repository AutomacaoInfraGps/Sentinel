from __future__ import annotations

import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SOURCE_ROOT))

