# MCP server: read documents (PDF, Word, PowerPoint, Excel, HTML, images) fully locally via the Docling service,
# with page rendering so the vision model can look at figures and charts. Conversions are cached by file content.
import hashlib, json, os, re, shutil, subprocess, sys, urllib.request
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY, WORK, IMAGES, GALLERY_URL, gallery, image_ref
from typing import Optional
from mcp.server.fastmcp import FastMCP

DOCLING = os.environ.get("DOCLING_URL", "http://127.0.0.1:5001").rstrip("/")
CACHE = os.path.join(WORK, "docs-cache")
IMAGE_DIR = os.path.join(IMAGES, "docs")
GALLERY = (GALLERY_URL + "/docs/") if GALLERY_URL else ""
UV = shutil.which("uv") or "uv"
mcp = FastMCP("documents")


def _key(path, opts):
    st = os.stat(path)
    h = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime}|{json.dumps(opts, sort_keys=True)}".encode()).hexdigest()[:16]
    return os.path.join(CACHE, h)


def _convert(path, pages=None, force_ocr=False, fast=False):
    """Run Docling on a file (cached). Returns dict with md, json(doc), status, time."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise RuntimeError(f"no such file here: {path}. If the user attached it from their computer, call fetch_remote_file first.")
    opts = {"pages": pages, "force_ocr": force_ocr, "fast": fast}
    base = _key(path, opts)
    if os.path.exists(base + ".md") and os.path.exists(base + ".json"):
        return {"md": open(base + ".md").read(), "doc": json.load(open(base + ".json")), "cached": True}
    boundary = "----goosedocs" + hashlib.md5(path.encode()).hexdigest()
    fields = [("to_formats", "md"), ("to_formats", "json"), ("table_mode", "fast" if fast else "accurate"), ("do_ocr", "true"),
              ("force_ocr", "true" if force_ocr else "false"), ("image_export_mode", "placeholder"), ("abort_on_error", "false")]
    if pages:
        fields += [("page_range", str(pages[0])), ("page_range", str(pages[1]))]
    body = b""
    for k, v in fields:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    with open(path, "rb") as f:
        data = f.read()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{os.path.basename(path)}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(DOCLING + "/v1/convert/file", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        res = json.load(r)
    if res.get("status") not in ("success", "partial_success"):
        raise RuntimeError(f"conversion failed: {res.get('status')} {str(res.get('errors'))[:300]}")
    md = res["document"].get("md_content") or ""
    doc = res["document"].get("json_content") or {}
    os.makedirs(CACHE, exist_ok=True)
    open(base + ".md", "w").write(md); json.dump(doc, open(base + ".json", "w"))
    return {"md": md, "doc": doc, "cached": False, "time": res.get("processing_time")}


def _page_count(doc):
    return len(doc.get("pages") or {}) or None


@mcp.tool()
def read_document(path: str, pages: Optional[str] = None, start: int = 0, max_chars: int = 12000, force_ocr: bool = False) -> str:
    """Read a PDF, Word, PowerPoint, Excel, HTML or image file as clean markdown (headings, paragraphs, tables), converted
    locally. `pages` like "1-5" limits a PDF to those pages (recommended for long documents). Long output is paged: the
    result says how many characters remain; call again with `start` to continue. `force_ocr` re-reads scanned or
    image-only PDFs with OCR. Use document_outline first for long files, and render_pages + the vision tool for figures."""
    rng = None
    if pages:
        m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", pages)
        if not m: raise RuntimeError("pages must look like '3' or '2-7'")
        rng = (int(m.group(1)), int(m.group(2) or m.group(1)))
    r = _convert(path, rng, force_ocr)
    md = r["md"]
    chunk = md[start:start + max_chars]
    remaining = max(0, len(md) - (start + max_chars))
    head = f"[{os.path.basename(path)}" + (f", pages {rng[0]}-{rng[1]}" if rng else "") + f"; {len(md)} chars total; showing {start}-{start + len(chunk)}" + (f"; {remaining} remaining -> call again with start={start + max_chars}" if remaining else "; end") + "]\n\n"
    return head + chunk


@mcp.tool()
def document_outline(path: str) -> dict:
    """Structure of a document without reading it all: page count, headings (with levels), number of tables and
    pictures, and the first lines. Use it to decide which pages to read."""
    r = _convert(path)
    doc, md = r["doc"], r["md"]
    heads = []
    for t in doc.get("texts", []):
        if t.get("label") in ("section_header", "title"):
            pg = (t.get("prov") or [{}])[0].get("page_no")
            heads.append({"text": t.get("text", "")[:120], "level": t.get("level", 1), "page": pg})
    return {"file": os.path.basename(path), "pages": _page_count(doc), "chars": len(md), "headings": heads[:150],
            "tables": len(doc.get("tables", [])), "pictures": len(doc.get("pictures", [])), "first_lines": md[:400]}


@mcp.tool()
def extract_tables(path: str, pages: Optional[str] = None) -> list:
    """All tables in a document (or page range like "2-4") as markdown, each with its page number and caption if any."""
    rng = None
    if pages:
        a, _, b = pages.partition("-"); rng = (int(a), int(b or a))
    r = _convert(path, rng)
    out = []
    for i, t in enumerate(r["doc"].get("tables", [])):
        pg = (t.get("prov") or [{}])[0].get("page_no")
        cells = t.get("data", {}).get("grid") or []
        rows = [[(c.get("text") or "").replace("\n", " ").strip() for c in row] for row in cells]
        md = ""
        if rows:
            md = "| " + " | ".join(rows[0]) + " |\n|" + "---|" * len(rows[0]) + "\n" + "\n".join("| " + " | ".join(rw) + " |" for rw in rows[1:])
        cap = " ".join(c.get("text", "") for c in (t.get("captions") or []) if isinstance(c, dict))
        out.append({"index": i + 1, "page": pg, "caption": cap, "rows": len(rows), "markdown": md[:6000]})
    return out


@mcp.tool()
def render_pages(path: str, pages: str = "1", dpi: int = 110) -> list:
    """Render PDF pages to PNG images (saved in the gallery) so you can look at figures, charts, diagrams or layout
    with the vision tool / read_image, or show a page to the user. `pages` like "3" or "2-4" (max 8 pages per call).
    Returns, per page, the local image path and its gallery URL."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path): raise RuntimeError(f"no such file here: {path}")
    a, _, b = pages.partition("-"); p0, p1 = int(a), int(b or a); p1 = min(p1, p0 + 7)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(os.path.basename(path))[0].lower())[:40]
    code = f"""
import fitz, json
doc = fitz.open({path!r}); out = []
for p in range({p0}, min({p1}, doc.page_count) + 1):
    pix = doc[p-1].get_pixmap(dpi={int(dpi)}); fn = {os.path.join(IMAGE_DIR, stem)!r} + f"-p{{p}}.png"; pix.save(fn); out.append((p, fn))
print(json.dumps(out))
"""
    res = subprocess.run([UV, "run", "--with", "pymupdf", "python", "-I", "-c", code], capture_output=True, text=True, timeout=300)
    if res.returncode != 0: raise RuntimeError("render failed: " + res.stderr[-400:])
    return [{"page": p, "path": fn, "url": (GALLERY + os.path.basename(fn)) if GALLERY else None} for p, fn in json.loads(res.stdout.strip().splitlines()[-1])]


if __name__ == "__main__":
    mcp.run()
