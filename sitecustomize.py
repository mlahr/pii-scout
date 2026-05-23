import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
src_root = repo_root / "src"
if src_root.exists():
    sys.path.insert(0, str(src_root))
