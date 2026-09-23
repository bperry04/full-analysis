import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("FA_DATA_ROOT", str(Path(os.environ.get("TEMP", "/tmp")) / "fadata_test"))
