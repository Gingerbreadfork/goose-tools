#!/usr/bin/env bash
# Start (or restart) the Docling document-conversion service (CPU). Loopback only; used by the "documents" Goose extension.
set -euo pipefail
docker rm -f docling >/dev/null 2>&1 || true
docker run -d --name docling --restart unless-stopped \
  -p 127.0.0.1:5001:5001 \
  -e DOCLING_SERVE_ENABLE_UI=0 -e DOCLING_SERVE_MAX_SYNC_WAIT=900 -e OMP_NUM_THREADS=16 -e UVICORN_WORKERS=1 \
  --memory=48g \
  ghcr.io/docling-project/docling-serve-cpu:latest >/dev/null
for i in $(seq 1 90); do curl -sf -m 3 http://127.0.0.1:5001/health >/dev/null 2>&1 && break; sleep 2; done
echo "container: $(docker inspect -f '{{.State.Status}}' docling) | health: $(curl -s -m 3 http://127.0.0.1:5001/health)"
