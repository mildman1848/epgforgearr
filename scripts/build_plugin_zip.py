#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plugin.json"
DIST = ROOT / "dist"


def _plugin_version() -> str:
    import json

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return str(data["version"])


def main() -> int:
    version = _plugin_version()
    DIST.mkdir(exist_ok=True)
    output = DIST / f"epgforgearr-{version}.zip"
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for rel in ("plugin.py", "plugin.json"):
            archive.write(ROOT / rel, rel)
        for path in sorted((ROOT / "epgforgearr").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, str(path.relative_to(ROOT)))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"ZIP={output}")
    print(f"SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
