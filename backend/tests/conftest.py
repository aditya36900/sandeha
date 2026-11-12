import os
import sys
from pathlib import Path

os.environ["SANDEHA_PERSIST"] = "0"  # tests never touch the real session store

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
