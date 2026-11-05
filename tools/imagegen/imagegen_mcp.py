# MCP server: image generation via an OpenAI-compatible /images/generations endpoint. Saves PNGs under
# GOOSE_WORK/images and returns a gallery link (if configured) so the chat can display the picture, plus the path.
import base64, json, os, re, sys, time, urllib.request
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY, WORK, IMAGES, GALLERY_URL, gallery, image_ref
from typing import Optional
from mcp.server.fastmcp import FastMCP

HALOGEN = OPENAI_BASE_URL
KEY = OPENAI_API_KEY
MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-1")
IMAGE_DIR = IMAGES
URL_BASE = GALLERY_URL
RETURN_INLINE = os.environ.get("IMAGE_RETURN_INLINE", "1") == "1"

mcp = FastMCP("images")

def _slug(s, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].rstrip("-") or "image"

@mcp.tool()
def generate_image(prompt: str, size: str = "768x768", n: int = 1, name: Optional[str] = None):
    """Generate image(s) with the configured image model.
    `size` is WIDTHxHEIGHT, multiples of 64, e.g. 768x768, 1024x576, 576x1024. `name` is an optional file name stem.
    Saves PNG files and returns, for each image, a markdown image line and the file path.
    IMPORTANT: copy the returned markdown image line(s) verbatim into your reply so the user sees the picture in chat.
    You cannot view the image yourself; do not claim to have checked it."""
    os.makedirs(IMAGE_DIR, exist_ok=True)
    body = {"model": MODEL, "prompt": prompt, "n": max(1, min(int(n), 4)), "size": size, "response_format": "b64_json"}
    req = urllib.request.Request(HALOGEN + "/images/generations", data=json.dumps(body).encode(),
          headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)["data"]
    stem = _slug(name or prompt); stamp = time.strftime("%Y%m%d-%H%M%S")
    lines, inline = [], []
    for i, item in enumerate(data):
        fname = f"{stem}-{stamp}" + (f"-{i+1}" if len(data) > 1 else "") + ".png"
        path = os.path.join(IMAGE_DIR, fname)
        with open(path, "wb") as f:
            f.write(base64.b64decode(item["b64_json"]))
        link = f"{URL_BASE}/{fname}" if URL_BASE else path
        lines.append(f"![{prompt[:80]}]({link})\nSaved: {path}")
        if RETURN_INLINE:
            from mcp.server.fastmcp import Image
            inline.append(Image(data=base64.b64decode(item["b64_json"]), format="png"))
    text = "\n\n".join(lines)
    return [text, *inline] if inline else text

if __name__ == "__main__":
    mcp.run()
