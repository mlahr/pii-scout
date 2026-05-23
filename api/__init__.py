from pathlib import Path

# Extend package path to include src/api for backwards-compatible imports.
_src_api = Path(__file__).resolve().parent.parent / "src" / "api"
if _src_api.exists():
    __path__.append(str(_src_api))
