import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# config.py reads DATA_DIR at import time: keep tests away from the repo.
os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parent / ".data"))
