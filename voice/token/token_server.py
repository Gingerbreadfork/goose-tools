# Mints LiveKit access tokens for the call page. POST /token {"name": "..."} -> {"token", "url"}
import json, os, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from livekit import api

KEY, SECRET = os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
ROOM = os.environ.get("LIVEKIT_ROOM", "goose")


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0")); body = json.loads(self.rfile.read(n) or b"{}")
        name = (body.get("name") or "you")[:40]
        tok = (api.AccessToken(KEY, SECRET).with_identity(f"{name}-{uuid.uuid4().hex[:6]}").with_name(name)
               .with_grants(api.VideoGrants(room_join=True, room=ROOM, can_publish=True, can_subscribe=True)).to_jwt())
        out = json.dumps({"token": tok, "room": ROOM}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a): pass


ThreadingHTTPServer(("0.0.0.0", 8090), H).serve_forever()
