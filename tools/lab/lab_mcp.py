# MCP server: data analysis in the goose-lab sandbox (persistent Python kernel in a container). pandas/polars/duckdb,
# scipy/statsmodels/scikit-learn, styled charts, formatted Excel, PDF and Word reports. Files the user attached are
# visible at their normal paths; outputs go to ~/goose-work (reports) and the image gallery (charts).
import json, os, sys, urllib.request
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY, WORK, IMAGES, GALLERY_URL, gallery, image_ref
from typing import Optional
from mcp.server.fastmcp import FastMCP

LAB = os.environ.get("LAB_URL", "http://127.0.0.1:8800").rstrip("/")
mcp = FastMCP("lab")

HELP = """Python sandbox with persistent state (like a notebook). Preloaded: np, pd, plt, sns, and helpers:
  save_chart(name, source=None)     -> saves the current matplotlib figure to the gallery; returns {"path","url"} (show the url as a markdown image)
  to_excel(path, {"Sheet": df, ...}) -> formatted .xlsx (styled header, autofit, number formats, frozen header, table style); returns host path
  to_pdf_report(path, markdown, title=) -> polished PDF report from markdown; embed charts with ![caption](chart path); returns host path
  to_docx(path, markdown, title=)   -> Word document from markdown (headings, lists, tables, images)
  describe(df)                       -> readable profile of a DataFrame
Also available: polars, duckdb, scipy, statsmodels, sklearn, plotly (kaleido export), openpyxl/xlsxwriter, python-docx/pptx, weasyprint.
Paths: /work = the GOOSE_WORK folder on the host (read/write; put reports in /work/reports). The host user's Downloads, Documents
and Desktop are mounted read-only at their host paths. Charts: /work/images/charts (served by the gallery if configured).
Deliver results to the user as files (e.g. send_file_to_machine when the remote-files tool is installed) and show charts via the gallery URL.
Style: charts are pre-styled; always give a title and axis labels, format thousands, cite the source with save_chart(source=...)."""


def _post(path, body, timeout=950):
    req = urllib.request.Request(LAB + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


@mcp.tool()
def run_python(code: str, timeout: int = 180) -> str:
    """Run Python in the persistent data-analysis sandbox (variables and DataFrames survive between calls). Returns stdout,
    the value of the last expression (DataFrames shown as a table), errors, and any files created. Use lab_help first for
    the preloaded helpers (save_chart, to_excel, to_pdf_report, to_docx, describe)."""
    try:
        r = _post("/run", {"code": code, "timeout": timeout})
    except Exception as e:
        raise RuntimeError(f"lab sandbox not reachable ({e}); start it with ~/goose-tools/start-lab.sh")
    parts = []
    if r.get("stdout"): parts.append(r["stdout"].rstrip())
    if r.get("result") is not None: parts.append("=> " + r["result"])
    if r.get("stderr"): parts.append("stderr: " + r["stderr"].rstrip()[-1500:])
    if r.get("error"): parts.append("ERROR:\n" + r["error"])
    if r.get("new_files"):
        host = [p.replace("/work", WORK, 1) for p in r["new_files"]]
        urls = [(GALLERY_URL + "/charts/" + os.path.basename(p)) for p in r["new_files"] if GALLERY_URL and p.startswith("/work/images/charts/")]
        parts.append("files: " + ", ".join(host) + (("\nchart urls: " + ", ".join(urls)) if urls else ""))
    parts.append(f"({r.get('elapsed')}s)")
    return "\n".join(parts) or "(no output)"


@mcp.tool()
def reset_python() -> str:
    """Clear all variables in the sandbox (start a fresh analysis)."""
    _post("/reset", {}, timeout=30); return "sandbox reset"


@mcp.tool()
def lab_help() -> str:
    """What the sandbox provides: preloaded libraries, the chart/Excel/PDF/Word helpers, paths and conventions."""
    return HELP


if __name__ == "__main__":
    mcp.run()
