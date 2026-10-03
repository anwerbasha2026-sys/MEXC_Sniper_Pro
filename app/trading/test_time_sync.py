from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.trading.mexc_spot_api import MEXCSpotAPI


def main() -> int:
    print("=" * 80)
    print("MEXC SERVER TIME SYNC TEST")
    print("=" * 80)

    # Public endpoint: no API credentials required.
    api = MEXCSpotAPI.__new__(MEXCSpotAPI)
    api.api_key = ""
    api.api_secret = ""
    api.timeout = 10.0
    api._time_offset_ms = 0
    api._time_synced_at = 0.0

    server_time = api._request_server_time()
    import time
    local_ms = int(time.time() * 1000)
    raw_diff = server_time - local_ms

    print("Local UTC ms       :", local_ms)
    print("MEXC server ms     :", server_time)
    print("Raw difference ms  :", raw_diff)

    # Full signed test only when credentials are configured.
    if settings.mexc_api_key and settings.mexc_api_secret:
        signed_api = MEXCSpotAPI(
            settings.mexc_api_key,
            settings.mexc_api_secret,
        )
        status = signed_api.time_sync_status()

        print("Offset ms          :", status["offsetMs"])
        print("Estimated server   :", status["estimatedServerTimeMs"])

        account = signed_api.account()
        print("SIGNED ACCOUNT     : PASSED")
        print("Account type       :", account.get("accountType"))
        print("Can trade          :", account.get("canTrade"))
        print("Permissions        :", account.get("permissions", []))
    else:
        print()
        print("SIGNED ACCOUNT     : SKIPPED")
        print("MEXC_API_KEY / MEXC_API_SECRET are not configured.")

    print("=" * 80)
    print("TIME SYNC TEST PASSED")
    print("No order was placed.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
