# Persistent Python REPL over HTTP for the Goose data-analysis tools.
#   POST /run    {"code": "...", "timeout": 120}  -> {"stdout", "stderr", "result", "error", "new_files", "elapsed"}
#   POST /reset  -> clears all variables
#   GET  /health
# State (variables, DataFrames) persists between calls, like a notebook kernel. Runs as an unprivileged user inside
# the container; the only writable places are /work (shared workspace) and /work/charts (the image gallery).
import io, json, os, sys, time, traceback, contextlib, threading, signal
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/opt/lab")
WORK = "/work"
NS = {}
LOCK = threading.Lock()


def fresh_namespace():
    ns = {"__name__": "__main__", "__builtins__": __builtins__}
    exec("import os, sys, json, math, re, datetime as dt\n"
         "import numpy as np, pandas as pd\n"
         "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt\n"
         "import seaborn as sns\n"
         "from goose_style import apply_style, save_chart, to_excel, to_pdf_report, to_docx, describe\n"
         "apply_style()\n", ns)
    return ns


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout("execution exceeded the time limit")


def snapshot_files():
    out = {}
    for root, _, files in os.walk(WORK):
        for f in files:
            p = os.path.join(root, f)
            try: out[p] = os.stat(p).st_mtime
            except OSError: pass
    return out


def run(code, timeout):
    global NS
    with LOCK:
        if not NS: NS = fresh_namespace()
        before = snapshot_files()
        out, err = io.StringIO(), io.StringIO()
        result, error = None, None
        t0 = time.time()
        signal.signal(signal.SIGALRM, _alarm); signal.alarm(int(timeout))
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    # evaluate the last expression like a notebook cell
                    import ast
                    tree = ast.parse(code)
                    last = tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
                    if last is not None:
                        exec(compile(ast.Module(tree.body[:-1], type_ignores=[]), "<cell>", "exec"), NS)
                        result = eval(compile(ast.Expression(last.value), "<cell>", "eval"), NS)
                    else:
                        exec(compile(tree, "<cell>", "exec"), NS)
                except Timeout as e:
                    error = str(e)
                except Exception:
                    error = traceback.format_exc(limit=6)
        finally:
            signal.alarm(0)
        after = snapshot_files()
        new_files = sorted(p for p, m in after.items() if p not in before or before[p] != m)
        rtxt = None
        if result is not None:
            try:
                import pandas as pd
                if isinstance(result, pd.DataFrame):
                    rtxt = f"DataFrame {result.shape[0]} rows x {result.shape[1]} cols\n" + result.head(30).to_string(max_cols=20)
                else:
                    rtxt = repr(result)
            except Exception:
                rtxt = repr(result)
            if len(rtxt) > 8000: rtxt = rtxt[:8000] + f"\n... ({len(rtxt)} chars, truncated)"
        return {"stdout": out.getvalue()[-12000:], "stderr": err.getvalue()[-3000:], "result": rtxt, "error": error,
                "new_files": new_files, "elapsed": round(time.time() - t0, 2)}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health": return self._send(200, {"ok": True, "vars": len([k for k in NS if not k.startswith("_")])})
        self._send(404, {"error": "unknown"})

    def do_POST(self):
        global NS
        n = int(self.headers.get("Content-Length", "0")); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/reset":
            with LOCK: NS = {}
            return self._send(200, {"ok": True})
        if self.path == "/run":
            return self._send(200, run(body.get("code", ""), min(int(body.get("timeout", 120)), 900)))
        self._send(404, {"error": "unknown"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8800), H).serve_forever()   # single-threaded on purpose: SIGALRM timeouts need the main thread
