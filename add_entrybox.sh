#!/usr/bin/env bash
# add_entrybox.sh
# Auf dem SERVER ausführen.
# Installiert EntryAgent auf einer EntryBox und trägt sie in devices.json + DB ein.
#
# Nutzung:
#   sudo ./add_entrybox.sh <BOX_IP> [ENTRYPOINT]
#
# Wenn ENTRYPOINT leer: wird der Hostname der Box verwendet.
#
# Voraussetzungen auf dem SERVER:
#   - sshpass, ssh, scp, jq, sqlite3, openssl
#   - Projektstruktur: /opt/entryhub/server/devices.json, /opt/entryhub/heartbeats.db
#
# Voraussetzungen auf der BOX:
#   - ssh erreichbar: korona/korona
#   - python3 vorhanden

set -euo pipefail

SERVER_URL="${SERVER_URL:http://10.10.16.70:8080}"  # später per DNS auflösen
SSH_USER="korona"
SSH_PASS="korona"

DEVICES_JSON="/opt/entryhub/server/devices.json"
DB_PATH="/opt/entryhub/heartbeats.db"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <BOX_IP> [ENTRYPOINT]"
  exit 1
fi

BOX_IP="$1"
ENTRYPOINT="${2:-}"

for cmd in sshpass ssh scp jq sqlite3 openssl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Fehlendes Kommando auf dem SERVER: $cmd"
    exit 2
  fi
done

if [[ ! -f "$DEVICES_JSON" ]]; then
  echo "devices.json nicht gefunden unter $DEVICES_JSON"
  exit 3
fi

echo ">> Hole Hostname und MAC von der Box $BOX_IP ..."
HOSTNAME=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
  "${SSH_USER}@${BOX_IP}" 'hostname' 2>/dev/null | tr -d '\r')
if [[ -z "${HOSTNAME}" ]]; then
  echo "Konnte Hostname von $BOX_IP nicht ermitteln."
  exit 4
fi

MAC=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
  "${SSH_USER}@${BOX_IP}" \
  'cat /sys/class/net/eth0/address 2>/dev/null || cat /sys/class/net/wlan0/address 2>/dev/null || ip link | awk "/ether/ {print \$2; exit}"' \
  2>/dev/null | tr -d '\r')

if [[ -z "${MAC}" ]]; then
  echo "Konnte MAC-Adresse von $BOX_IP nicht ermitteln."
  exit 5
fi

if [[ -z "${ENTRYPOINT}" ]]; then
  ENTRYPOINT="${HOSTNAME}"
fi

echo ">> Verwende ENTRYPOINT=${ENTRYPOINT}, HOSTNAME=${HOSTNAME}, MAC=${MAC}"

echo ">> Generiere Token ..."
TOKEN=$(openssl rand -hex 24)
echo "Token: ${TOKEN}"

echo ">> Trage Gerät in devices.json ein ..."
TMP_JSON=$(mktemp)
jq --arg ep "$ENTRYPOINT" \
   --arg ip "$BOX_IP" \
   --arg mac "$MAC" \
   --arg tok "$TOKEN" \
   '.devices += [{entrypoint:$ep, location:"", ip:$ip, mac_address:$mac, hardware:"RPi", access_type:"", token:$tok, notes:""}]' \
   "$DEVICES_JSON" > "$TMP_JSON"
mv "$TMP_JSON" "$DEVICES_JSON"

echo ">> Trage Gerät in SQLite-DB ein ..."
sqlite3 "$DB_PATH" \
  "INSERT OR REPLACE INTO device (entrypoint, ip, mac_address, token) VALUES ('$ENTRYPOINT', '$BOX_IP', '$MAC', '$TOKEN');"

echo ">> Installiere EntryAgent auf der Box $BOX_IP ..."

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${BOX_IP}" \
  "sudo mkdir -p /opt/entryagent && sudo chown ${SSH_USER}:${SSH_USER} /opt/entryagent"

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${BOX_IP}" \
  "sudo tee /opt/entryagent/agent.py >/dev/null" <<'PYCODE'
#!/usr/bin/env python3
import os, time, socket, json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8080")
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
            print("[entryagent] heartbeat error:", e)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
PYCODE

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${BOX_IP}" \
  "sudo chmod 755 /opt/entryagent/agent.py"

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${BOX_IP}" \
  "sudo tee /etc/entryagent.env >/dev/null" <<EOF
SERVER_URL=${SERVER_URL}
ENTRYPOINT=${ENTRYPOINT}
TOKEN=${TOKEN}
INTERVAL_S=30
EOF

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${BOX_IP}" \
  "sudo tee /etc/systemd/system/entryagent.service >/dev/null" <<'EOF'
[Unit]
Description=EntryBox Heartbeat Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
EnvironmentFile=/etc/entryagent.env
ExecStart=/usr/bin/python3 /opt/entryagent/agent.py
Restart=always
RestartSec=5
Nice=10

[Install]
WantedBy=multi-user.target
EOF

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${BOX_IP}" \
  "sudo systemctl daemon-reload && sudo systemctl enable --now entryagent"

echo ">> Fertig für Box ${BOX_IP} / ENTRYPOINT=${ENTRYPOINT}"
echo ">> Prüfe Status auf dem Server mit:"
echo "   curl -s http://127.0.0.1:8080/api/v1/devices | jq '.[] | select(.entrypoint==\"${ENTRYPOINT}\") | {entrypoint,ip,last_seen,online}'"
