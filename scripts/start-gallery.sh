#!/usr/bin/env bash
# Start (or restart) the HTTPS image gallery: serves GOOSE_WORK/images so chat clients can display images the tools make.
# Goose Desktop only shows https images and pins the goose server's certificate by hostname, so reuse that certificate
# (TLS_DIR, default ~/.config/goose/tls with server.pem/server.key) and set GALLERY_URL=https://<host>:8443/images
set -euo pipefail
WORK="${GOOSE_WORK:-$HOME/goose-work}"; TLS_DIR="${TLS_DIR:-$HOME/.config/goose/tls}"; CONF="$(cd "$(dirname "$0")" && pwd)/gallery-nginx.conf"
mkdir -p "$WORK/images"
docker rm -f goose-images >/dev/null 2>&1 || true
docker run -d --name goose-images --restart unless-stopped \
  -p "${GALLERY_PORT:-8443}:8443" \
  -v "$WORK/images:/srv/images:ro" \
  -v "$TLS_DIR:/etc/nginx/tls:ro" \
  -v "$CONF:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine >/dev/null
sleep 2
echo "container: $(docker inspect -f '{{.State.Status}}' goose-images)"
echo "listing: $(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:${GALLERY_PORT:-8443}/images/)"
