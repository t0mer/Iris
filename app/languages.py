"""The backend and frontend share the supported UI language registry."""

import json
from pathlib import Path

SUPPORTED_LANGUAGES = frozenset(
    json.loads((Path(__file__).parent / "assets" / "ui-languages.json").read_text(encoding="utf-8"))
)
