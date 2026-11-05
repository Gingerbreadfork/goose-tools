# MCP server: give the agent eyes. Sends an image (local path or URL) plus a question to an OpenAI-compatible
# vision-capable chat model and returns the answer as text.
import base64, json, os, re, ssl, sys, urllib.request
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY, WORK, IMAGES, GALLERY_URL, gallery, image_ref
from mcp.server.fastmcp import FastMCP

HALOGEN = OPENAI_BASE_URL
KEY = OPENAI_API_KEY
MODEL = os.environ.get("VISION_MODEL", "gpt-4o-mini")   # any vision-capable model on your server
IMAGE_DIR = IMAGES
IMAGE_URL_BASE = GALLERY_URL
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}

mcp = FastMCP("vision")

def _load(image: str) -> tuple[bytes, str]:
    if IMAGE_URL_BASE and image.startswith(IMAGE_URL_BASE):        # our own gallery: read the file directly
        image = os.path.join(IMAGE_DIR, image[len(IMAGE_URL_BASE):].lstrip('/'))
    if re.match(r"^https?://", image):
        req = urllib.request.Request(image, headers={"User-Agent": "goose-vision/1.0"})
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
            data = r.read(); mime = r.headers.get_content_type()
            if not mime.startswith("image/"): mime = MIME.get(os.path.splitext(image.split("?")[0])[1].lower(), "image/png")
            return data, mime
    path = os.path.expanduser(image)
    with open(path, "rb") as f:
        return f.read(), MIME.get(os.path.splitext(path)[1].lower(), "image/png")

@mcp.tool()
def look_at_image(image: str, question: str = "Describe this image in detail.", max_words: int = 150) -> str:
    """Look at an image and answer a question about it. `image` is a local file path (png/jpg/webp/gif) or an http(s) URL,
    including links from the generate_image tool. Use it to check generated images, read screenshots, charts or photos,
    or extract text from a picture. Returns the vision model's answer (about 2 s)."""
    data, mime = _load(image)
    body = {"model": MODEL, "max_tokens": max(64, int(max_words) * 3), "messages": [{"role": "user", "content": [
        {"type": "text", "text": f"{question}\nAnswer in at most {int(max_words)} words."},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(data).decode()}}]}]}
    req = urllib.request.Request(HALOGEN + "/chat/completions", data=json.dumps(body).encode(),
          headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()

if __name__ == "__main__":
    mcp.run()
