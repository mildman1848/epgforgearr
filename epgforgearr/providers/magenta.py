from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


class MagentaProvider:
    """Magenta TV EPG provider adapter.

    Based on the public flow used by michaz1988/.epg/make_guide.py. It does not
    use household credentials, but it is still an unofficial endpoint, so callers
    should keep retries bounded and cache generated XMLTV output.
    """

    AUTH_URL = "https://api.prod.sngtv.magentatv.de/EPG/JSON/Authenticate"
    CHANNELS_URL = "https://api.prod.sngtv.magentatv.de/EPG/JSON/AllChannel"
    DATA_URL = "https://api.prod.sngtv.magentatv.de/EPG/JSON/PlayBillList?userContentFilter=241221015&sessionArea=1&SID=ottall&T=PC_firefox_75"
    HEADERS = {
        "Host": "api.prod.sngtv.magentatv.de",
        "origin": "https://web.magentatv.de",
        "referer": "https://web.magentatv.de/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/132.0 Safari/537.36",
    }

    def __init__(self) -> None:
        self.session: requests.Session | None = None

    def _session(self) -> requests.Session:
        if self.session is not None:
            return self.session
        mac = str(uuid.uuid4())
        ter = str(uuid.uuid4())
        payload = json.dumps({
            "areaid": "1",
            "cnonce": "c4b11948545fb3089720dd8b12c81f8e",
            "mac": mac,
            "preSharedKeyID": "NGTV000001",
            "subnetId": "4901",
            "templatename": "NGTV",
            "terminalid": ter,
            "terminaltype": "WEB-MTV",
            "terminalvendor": "WebTV",
            "timezone": "UTC",
            "usergroup": "-1",
            "userType": 3,
            "utcEnable": 1,
        })
        session = requests.Session()
        for attempt in range(20):
            response = session.post(self.AUTH_URL, data=payload, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            if response.json().get("retcode") == "-2":
                time.sleep(0.2 + attempt * 0.02)
                continue
            break
        token = session.cookies.get("CSRFSESSION")
        if not token:
            raise RuntimeError("Magenta auth returned no CSRFSESSION")
        session.headers.update({"X_CSRFToken": token})
        self.session = session
        return session

    def list_channels(self) -> list[dict[str, Any]]:
        payload = {
            "properties": [{"name": "logicalChannel", "include": "/channellist/logicalChannel/contentId,/channellist/logicalChannel/name"}],
            "metaDataVer": "Channel/1.1",
            "channelNamespace": "2",
            "filterlist": [{"key": "IsHide", "value": "-1"}],
            "returnSatChannel": "0",
        }
        response = self._session().post(self.CHANNELS_URL, json=payload, headers=self.HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data.get("channellist", []) if isinstance(data, dict) else []

    def fetch_programmes(self, provider_channel_id: str, days: int = 1) -> list[dict[str, Any]]:
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = start + timedelta(days=days)
        payload = {
            "channelid": str(provider_channel_id),
            "type": "2",
            "offset": "0",
            "count": "-1",
            "isFillProgram": "1",
            "properties": '[{"name":"playbill","include":"id,channelid,name,subName,starttime,endtime,introduce,genres,seasonNum,subNum"}]',
            "begintime": start.strftime("%Y%m%d%H%M%S"),
            "endtime": end.strftime("%Y%m%d%H%M%S"),
        }
        response = self._session().post(self.DATA_URL, json=payload, headers=self.HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
        rows = data.get("playbilllist", []) if isinstance(data, dict) else []
        return [
            {
                "title": row.get("name"),
                "subtitle": row.get("subName"),
                "description": row.get("introduce"),
                "start": row.get("starttime"),
                "stop": row.get("endtime"),
                "raw": row,
            }
            for row in rows
        ]
