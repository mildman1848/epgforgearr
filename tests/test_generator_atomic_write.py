from __future__ import annotations

import gzip
import os
from pathlib import Path

from epgforgearr.generator import generate_xmltv


class EmptyProvider:
    def fetch_programmes(self, provider_channel_id: str, days: int = 1):
        return []


def test_generate_xmltv_replaces_non_writable_existing_files(tmp_path: Path):
    """Atomic replace must survive stale files created by the wrong user/mode."""
    output_path = tmp_path / "epg.xml"
    gz_path = tmp_path / "epg.xml.gz"
    output_path.write_text("old xml")
    gz_path.write_bytes(b"old gz")
    output_path.chmod(0o444)
    gz_path.chmod(0o444)

    try:
        result = generate_xmltv(
            {
                "output_path": str(output_path),
                "gzip_output": True,
                "days": 1,
                "mapping_config_json": [
                    {
                        "channel_id": "demo.channel",
                        "display_name": "Demo Channel",
                        "sources": [
                            {
                                "provider": "demo",
                                "provider_channel_id": "demo",
                                "label": "Demo",
                                "priority": 1,
                            }
                        ],
                    }
                ],
            },
            provider_factory=lambda _provider: EmptyProvider(),
        )
    finally:
        # Make pytest cleanup robust on platforms where replace unexpectedly failed.
        for path in (output_path, gz_path):
            if path.exists():
                os.chmod(path, 0o664)

    assert result["status"] == "ok"
    assert output_path.read_text().startswith("<?xml")
    assert gzip.open(gz_path, "rb").read().startswith(b"<?xml")
    assert output_path.stat().st_mode & 0o777 == 0o664
    assert gz_path.stat().st_mode & 0o777 == 0o664
