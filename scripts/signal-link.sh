#!/usr/bin/env bash
# Link the Signal bridge to your own Signal account as a device named "Goose". Produces a QR code in the gallery.
set -euo pipefail
OUT="${GOOSE_WORK:-$HOME/goose-work}/images/signal-link.png"
curl -s -m 60 "http://127.0.0.1:8090/v1/qrcodelink?device_name=Goose" -o "$OUT"
file "$OUT" | grep -q PNG && echo "QR saved to $OUT (open it and scan from Signal > Linked devices within a few minutes)" || { echo "no QR returned:"; head -c 300 "$OUT"; echo; }
