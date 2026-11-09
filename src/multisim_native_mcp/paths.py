"""Packaged resources and per-user session storage."""
import os
from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get(
    "MULTISIM_NATIVE_DATA_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "MultisimNativeMCP"),
)).expanduser().resolve()
