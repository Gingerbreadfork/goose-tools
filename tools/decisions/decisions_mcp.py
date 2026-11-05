# MCP server exposing a System One / Jev-compatible decision endpoint (e.g. Halogen's /v1/systemone or TypeSafe's API)
# as three fast, calibrated tools: yes/no, choice, score.
import base64, json, os, sys, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY
from typing import Optional
from mcp.server.fastmcp import FastMCP

URL = os.environ.get("SYSTEMONE_URL", OPENAI_BASE_URL + "/systemone")   # Jev-compatible endpoint
KEY = os.environ.get("SYSTEMONE_API_KEY", OPENAI_API_KEY)
DEFAULT_MODEL = os.environ.get("SYSTEMONE_MODEL", "d3-nano")

mcp = FastMCP("decisions")

def _call(state, questions, model, image_path=None):
    body = {"model": model or DEFAULT_MODEL, "state": state, "questions": questions}
    if image_path:
        with open(image_path, "rb") as f:
            body["images"] = ["data:image/png;base64," + base64.b64encode(f.read()).decode()]
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
          headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["answers"]

@mcp.tool()
def decide_choice(state: str, question: str, options: dict, model: Optional[str] = None, image_path: Optional[str] = None) -> dict:
    """Pick one option for a question about `state`. `options` maps option name -> a short description of what belongs in it.
    ALWAYS give every option a real description (what kinds of cases fall under it); bare names give weak, low-confidence results.
    Returns the chosen option, a probability for every option, and a confidence 0-1. Fast (~70 ms), calibrated, no text generation.
    Use for routing, classification, triage, yes/no gates with more than two outcomes. `image_path` lets d3-nano decide over a picture."""
    criteria = {k: (v or None) for k, v in options.items()}
    return _call(state, {"q": {"type": "choice", "instructions": question, "criteria": criteria}}, model, image_path)["q"]

@mcp.tool()
def decide_yes_no(state: str, question: str, model: Optional[str] = None, image_path: Optional[str] = None) -> dict:
    """Answer a yes/no question about `state`. Returns {'noul': probability_of_yes}. Use for guardrails such as
    'is this command destructive?', 'is this task finished?', 'does this message need a human?'."""
    return _call(state, {"q": {"type": "noul", "instructions": question}}, model, image_path)["q"]

@mcp.tool()
def decide_score(state: str, question: str, levels: list, model: Optional[str] = None, image_path: Optional[str] = None) -> dict:
    """Place `state` on an ordered scale. `levels` is an ordered list of level DESCRIPTIONS, lowest first.
    Each level must be a short sentence saying what qualifies, e.g. ["low: can wait a week, no business impact",
    "medium: should be handled today, one user affected", "high: outage or money loss, act now"]. Single words
    like "low"/"medium"/"high" give near-random, low-confidence scores.
    Returns an expected score (0 = first level), per-level probabilities, and confidence 0-1. Use for urgency, severity, quality grading."""
    return _call(state, {"q": {"type": "score", "instructions": question, "criteria": list(levels)}}, model, image_path)["q"]

if __name__ == "__main__":
    mcp.run()
