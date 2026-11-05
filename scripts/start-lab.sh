#!/usr/bin/env bash
# Start (or restart) the goose-lab sandbox: persistent Python kernel for data analysis + yt-dlp/ffmpeg for media.
set -euo pipefail
WORK="${GOOSE_WORK:-$HOME/goose-work}"; mkdir -p "$WORK/images/charts" "$WORK/reports" "$WORK/media" "$WORK/transcripts" "$HOME/Downloads" "$HOME/Documents" "$HOME/Desktop"
# Build the image once from tools/lab/container:  docker build -t goose-lab:latest tools/lab/container
docker rm -f goose-lab >/dev/null 2>&1 || true
docker run -d --name goose-lab --restart unless-stopped \
  -p 127.0.0.1:8800:8800 --memory="${LAB_MEMORY:-16g}" --cpus="${LAB_CPUS:-8}" \
  -e GALLERY_URL="${GALLERY_URL:-}" -e HOST_WORK="$WORK" \
  -v "$WORK:/work" \
  -v "$HOME/Downloads:$HOME/Downloads:ro" \
  -v "$HOME/Documents:$HOME/Documents:ro" \
  -v "$HOME/Desktop:$HOME/Desktop:ro" \
  goose-lab:latest >/dev/null
for i in $(seq 1 30); do curl -sf -m 2 http://127.0.0.1:8800/health >/dev/null 2>&1 && break; sleep 1; done
echo "goose-lab: $(docker inspect -f '{{.State.Status}}' goose-lab) | $(curl -s -m 3 http://127.0.0.1:8800/health)"
