"""Presentation helpers preloaded in the Goose lab: a consistent chart style, and exporters for charts, Excel, PDF, Word.

apply_style()                      -> clean, consistent matplotlib/seaborn look (called automatically)
save_chart(name, fig=None)         -> saves the current figure as PNG into the gallery; returns {"path", "url"}
to_excel(path, sheets, ...)        -> formatted workbook: {"Sheet name": DataFrame}; header styling, widths, freeze panes, number formats
to_pdf_report(path, markdown, ...) -> styled PDF from markdown (charts via ![..](path) embed automatically)
to_docx(path, markdown)            -> Word document from markdown (headings, paragraphs, bullets, tables, images)
describe(df)                       -> quick, readable profile of a DataFrame (shape, dtypes, nulls, numeric summary)
"""
import os, re, datetime as dt

CHARTS = "/work/images/charts"
GALLERY = (os.environ.get("GALLERY_URL", "").rstrip("/") + "/charts/") if os.environ.get("GALLERY_URL") else ""
HOST_WORK = os.environ.get("HOST_WORK", "/work")   # GOOSE_WORK path on the host, for paths returned to the agent
PALETTE = ["#2563EB", "#F97316", "#10B981", "#8B5CF6", "#EF4444", "#0EA5E9", "#F59E0B", "#64748B"]


def apply_style():
    import matplotlib as mpl, matplotlib.pyplot as plt, seaborn as sns
    sns.set_theme(style="whitegrid", palette=PALETTE, font="DejaVu Sans")
    mpl.rcParams.update({
        "figure.figsize": (10, 5.6), "figure.dpi": 110, "savefig.dpi": 170, "savefig.bbox": "tight", "savefig.facecolor": "white",
        "axes.titlesize": 15, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 12,
        "axes.labelsize": 11.5, "axes.labelcolor": "#374151", "axes.edgecolor": "#D1D5DB", "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#E5E7EB", "grid.linewidth": 0.7,
        "xtick.labelsize": 10, "ytick.labelsize": 10, "xtick.color": "#4B5563", "ytick.color": "#4B5563",
        "legend.frameon": False, "legend.fontsize": 10, "lines.linewidth": 2.2, "axes.prop_cycle": mpl.cycler(color=PALETTE),
    })


def save_chart(name, fig=None, subtitle=None, source=None):
    """Save the current (or given) figure to the gallery as PNG. Adds an optional source/footnote line."""
    import matplotlib.pyplot as plt
    fig = fig or plt.gcf()
    if source:
        fig.text(0.01, -0.02, f"Source: {source}", fontsize=8.5, color="#6B7280", ha="left", va="top", transform=fig.transFigure)
    os.makedirs(CHARTS, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "chart"
    path = os.path.join(CHARTS, f"{stem}.png")
    fig.savefig(path)
    plt.close(fig)
    return {"path": path.replace("/work", HOST_WORK, 1), "url": (GALLERY + os.path.basename(path)) if GALLERY else None}


def to_excel(path, sheets, number_format="#,##0.00", autofit=True, freeze_header=True, table_style=True):
    """Write {sheet_name: DataFrame} to a nicely formatted .xlsx. Returns the host path."""
    import pandas as pd
    path = _work(path, ".xlsx")
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        hdr = wb.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "white", "border": 0, "align": "left", "valign": "vcenter"})
        num = wb.add_format({"num_format": number_format})
        intf = wb.add_format({"num_format": "#,##0"})
        datef = wb.add_format({"num_format": "yyyy-mm-dd"})
        for name, df in sheets.items():
            df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
            df.to_excel(xw, sheet_name=name[:31], index=False, startrow=1, header=False)
            ws = xw.sheets[name[:31]]
            for i, col in enumerate(df.columns):
                ws.write(0, i, str(col), hdr)
                s = df[col]
                fmt = None
                if pd.api.types.is_integer_dtype(s): fmt = intf
                elif pd.api.types.is_float_dtype(s): fmt = num
                elif pd.api.types.is_datetime64_any_dtype(s): fmt = datef
                width = min(max(len(str(col)), int(s.astype(str).str.len().quantile(0.9) if len(s) else 8)) + 2, 60) if autofit else 14
                ws.set_column(i, i, width, fmt)
            if freeze_header: ws.freeze_panes(1, 0)
            if table_style and len(df):
                ws.add_table(0, 0, len(df), len(df.columns) - 1, {"columns": [{"header": str(c)} for c in df.columns], "style": "Table Style Medium 2", "header_row": True})
                for i, col in enumerate(df.columns): ws.write(0, i, str(col), hdr)
    return _host(path)


def to_pdf_report(path, markdown_text, title=None, author="Goose", css_extra=""):
    """Render markdown (with ![caption](chart path) images, tables, code) into a clean PDF report."""
    import markdown as md
    from weasyprint import HTML, CSS
    path = _work(path, ".pdf")
    body = md.markdown(_localize_images(markdown_text), extensions=["tables", "fenced_code", "codehilite", "toc", "sane_lists"])
    head = f"<h1 class='title'>{title}</h1><p class='meta'>{author} · {dt.date.today():%d %B %Y}</p>" if title else ""
    html = f"<html><body>{head}{body}</body></html>"
    HTML(string=html, base_url="/work").write_pdf(path, stylesheets=[CSS("/opt/lab/report.css"), CSS(string=css_extra)])
    return _host(path)


def to_docx(path, markdown_text, title=None):
    """Markdown -> Word document (headings, paragraphs, bullet/numbered lists, tables, images)."""
    from docx import Document
    from docx.shared import Inches
    path = _work(path, ".docx")
    doc = Document()
    if title: doc.add_heading(title, 0)
    lines = _localize_images(markdown_text).splitlines(); i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip(): i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m: doc.add_heading(m.group(2), min(len(m.group(1)), 4)); i += 1; continue
        m = re.match(r"^!\[[^\]]*\]\(([^)]+)\)", line.strip())
        if m:
            p = m.group(1)
            if os.path.exists(p): doc.add_picture(p, width=Inches(6.2))
            i += 1; continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|?\s*:?-{3,}", lines[i]): rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if rows:
                t = doc.add_table(rows=len(rows), cols=len(rows[0])); t.style = "Light Grid Accent 1"
                for r, row in enumerate(rows):
                    for c, val in enumerate(row[:len(rows[0])]): t.cell(r, c).text = _strip_md(val)
            continue
        m = re.match(r"^\s*[-*]\s+(.*)", line)
        if m: doc.add_paragraph(_strip_md(m.group(1)), style="List Bullet"); i += 1; continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if m: doc.add_paragraph(_strip_md(m.group(1)), style="List Number"); i += 1; continue
        para = [line.strip()]
        while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#{1,6}\s|[-*]\s|\d+[.)]\s|!\[|\|)", lines[i + 1].strip()):
            i += 1; para.append(lines[i].strip())
        doc.add_paragraph(_strip_md(" ".join(para))); i += 1
    doc.save(path)
    return _host(path)


def describe(df, max_cols=40):
    import pandas as pd
    parts = [f"{df.shape[0]} rows x {df.shape[1]} columns"]
    info = pd.DataFrame({"dtype": df.dtypes.astype(str), "nulls": df.isna().sum(), "unique": df.nunique()})
    parts.append(info.head(max_cols).to_string())
    num = df.select_dtypes("number")
    if not num.empty: parts.append(num.describe().T.round(3).head(max_cols).to_string())
    return "\n\n".join(parts)


def _work(path, ext):
    path = os.path.expanduser(str(path))
    if not os.path.isabs(path): path = os.path.join("/work", path)
    path = path.replace(HOST_WORK, "/work") if HOST_WORK != "/work" else path
    if not path.lower().endswith(ext): path += ext
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _host(path):
    return path.replace("/work", HOST_WORK, 1)


def _localize_images(text):  # host/gallery chart references -> container paths
    t = text.replace(HOST_WORK.rstrip("/") + "/", "/work/") if HOST_WORK != "/work" else text
    return t.replace(GALLERY, "/work/images/charts/") if GALLERY else t


def _strip_md(s):
    return re.sub(r"[*_`]+", "", s)
