#!/usr/bin/env python3
import os, time, socket, json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

SERVER_URL = os.environ.get("SERVER_URL", "http://10.10.12.70:8080")
ENTRYPOINT = os.environ.get("ENTRYPOINT", "CHANGE_ME_entrypoint")
TOKEN = os.environ.get("TOKEN", "CHANGE_ME_token")
INTERVAL = int(os.environ.get("INTERVAL_S", "30"))

def post_json(url, data, token):
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }, method="POST")
    with urlopen(req, timeout=5) as r:
        return r.read()

def main():
    endpoint = SERVER_URL.rstrip("/") + "/api/v1/heartbeat"
    while True:
        try:
            payload = {
                "entrypoint": ENTRYPOINT,
                "hostname": socket.gethostname(),
                "ts": datetime.now(timezone.utc).isoformat(),
                "uptime_s": None,
                "load1": None,
                "mem_free_mb": None,
                "agent": {"ver": "0.1.0"}
            }
            post_json(endpoint, payload, TOKEN)
        except (HTTPError, URLError, OSError) as e:
            print("[agent] heartbeat error:", e)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
