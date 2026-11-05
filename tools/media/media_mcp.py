# MCP server: media transcription. Downloads audio with yt-dlp, converts with ffmpeg (both run locally if installed,
# otherwise inside the lab container), transcribes with an OpenAI-compatible /audio/transcriptions endpoint in
# timestamped chunks, and saves a transcript.
import json, os, re, shutil, subprocess, sys, time, urllib.request
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
from goosetools_config import OPENAI_BASE_URL, OPENAI_API_KEY, WORK, IMAGES, GALLERY_URL, gallery, image_ref
from typing import Optional
from mcp.server.fastmcp import FastMCP

HALOGEN = OPENAI_BASE_URL; KEY = OPENAI_API_KEY
ASR_MODEL = os.environ.get("ASR_MODEL", "whisper-1")
MEDIA = os.path.join(WORK, "media"); TRANSCRIPTS = os.path.join(WORK, "transcripts")
CONTAINER = os.environ.get("MEDIA_CONTAINER", "goose-lab"); CHUNK_SEC = int(os.environ.get("ASR_CHUNK_SECONDS", "45"))
LOCAL_TOOLS = bool(shutil.which("yt-dlp") and shutil.which("ffmpeg") and shutil.which("ffprobe"))
mcp = FastMCP("media")


def _lab(args, timeout=900):
    """Run yt-dlp/ffmpeg: locally when installed, else inside the lab container (GOOSE_WORK is mounted there at /work)."""
    if LOCAL_TOOLS:
        args = [a.replace("/work", WORK, 1) if a.startswith("/work") else a for a in args]
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    else:
        r = subprocess.run(["docker", "exec", "-u", "lab", CONTAINER] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout)[-600:])
    return r.stdout


def _host(p): return p.replace("/work", WORK, 1)
def _cont(p): return os.path.abspath(os.path.expanduser(p)).replace(WORK, "/work", 1)


@mcp.tool()
def media_info(url: str) -> dict:
    """Title, channel, duration, upload date and description of a YouTube (or other yt-dlp supported) URL, without downloading."""
    out = _lab(["yt-dlp", "--no-warnings", "--skip-download", "--print-json", "--no-playlist", url], timeout=120)
    d = json.loads(out.strip().splitlines()[-1])
    return {"title": d.get("title"), "channel": d.get("uploader") or d.get("channel"), "duration_min": round((d.get("duration") or 0) / 60, 1),
            "upload_date": d.get("upload_date"), "views": d.get("view_count"), "description": (d.get("description") or "")[:800], "url": d.get("webpage_url") or url}


def _transcribe_wav(path_host):
    """Chunked transcription with timestamps. Returns list of (start_sec, text)."""
    dur = float(_lab(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", _cont(path_host)]).strip())
    chunks = []
    n = int(dur // CHUNK_SEC) + 1
    tmpdir = os.path.join(MEDIA, ".chunks"); os.makedirs(tmpdir, exist_ok=True)
    for i in range(n):
        start = i * CHUNK_SEC
        if start >= dur: break
        cp = os.path.join(tmpdir, f"c{i:04d}.wav")
        _lab(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(CHUNK_SEC + 1), "-i", _cont(path_host), "-ac", "1", "-ar", "16000", _cont(cp)])
        with open(cp, "rb") as f: data = f.read()
        boundary = "----goosemedia"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{ASR_MODEL}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"c.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(HALOGEN + "/audio/transcriptions", data=body, headers={"Authorization": "Bearer " + KEY, "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            text = json.load(r).get("text", "").strip()
        if text: chunks.append((start, text))
        os.remove(cp)
    return dur, chunks


def _fmt(sec): return f"{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}" if sec >= 3600 else f"{int(sec // 60):02d}:{int(sec % 60):02d}"


@mcp.tool()
def transcribe(source: str, keep_audio: bool = False) -> str:
    """Transcribe a YouTube/podcast/web video URL or a local audio/video file (mp3, m4a, wav, mp4, ogg, voice notes...).
    Everything runs locally. Returns the title, duration and the first part of a timestamped transcript, plus the path of
    the saved transcript file; use read_transcript to page through the rest. A 10-minute video takes roughly a minute."""
    os.makedirs(MEDIA, exist_ok=True); os.makedirs(TRANSCRIPTS, exist_ok=True)
    t0 = time.time(); title = os.path.basename(source); src_path = None
    if re.match(r"^https?://", source):
        info = _lab(["yt-dlp", "--no-warnings", "--no-playlist", "--skip-download", "--print-json", source], timeout=120)
        d = json.loads(info.strip().splitlines()[-1]); title = d.get("title") or title
        stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "media"
        _lab(["yt-dlp", "--no-warnings", "--no-playlist", "-f", "bestaudio/best", "-x", "--audio-format", "wav", "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
              "-o", f"/work/media/{stem}.%(ext)s", source], timeout=1800)
        src_path = os.path.join(MEDIA, stem + ".wav")
    else:
        src = os.path.expanduser(source)
        if not os.path.isfile(src): raise RuntimeError(f"no such file: {src} (if it is on the user's computer, fetch_remote_file first)")
        stem = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(os.path.basename(src))[0].lower()).strip("-")[:60] or "media"
        src_path = os.path.join(MEDIA, stem + ".wav")
        if not src.startswith(WORK):
            import shutil; tmp = os.path.join(MEDIA, ".in-" + os.path.basename(src)); shutil.copy(src, tmp); src = tmp
        _lab(["ffmpeg", "-y", "-v", "error", "-i", _cont(src), "-vn", "-ac", "1", "-ar", "16000", _cont(src_path)])
        if os.path.basename(src).startswith(".in-"): os.remove(src)
    dur, chunks = _transcribe_wav(src_path)
    lines = [f"[{_fmt(s)}] {t}" for s, t in chunks]
    tpath = os.path.join(TRANSCRIPTS, stem + ".md")
    with open(tpath, "w") as f:
        f.write(f"# {title}\n\nSource: {source}\nDuration: {_fmt(dur)}\nTranscribed: {time.strftime('%Y-%m-%d %H:%M')}\n\n" + "\n".join(lines) + "\n")
    if not keep_audio: os.remove(src_path)
    full = "\n".join(lines)
    head = f"{title} | {_fmt(dur)} | {len(full.split())} words | transcript saved: {tpath} | took {time.time() - t0:.0f}s\n\n"
    return head + (full[:9000] + (f"\n\n... {len(full) - 9000} more characters: read_transcript(\"{tpath}\", start=9000)" if len(full) > 9000 else ""))


@mcp.tool()
def read_transcript(path: str, start: int = 0, max_chars: int = 12000) -> str:
    """Page through a saved transcript (from transcribe)."""
    s = open(os.path.expanduser(path)).read()
    return s[start:start + max_chars] + (f"\n\n... {len(s) - start - max_chars} more characters remain" if len(s) > start + max_chars else "")


@mcp.tool()
def list_transcripts() -> list:
    """Transcripts saved so far (title, path, date)."""
    out = []
    for f in sorted(os.listdir(TRANSCRIPTS)) if os.path.isdir(TRANSCRIPTS) else []:
        p = os.path.join(TRANSCRIPTS, f); first = open(p).readline().strip("# \n")
        out.append({"title": first, "path": p, "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
    return out


if __name__ == "__main__":
    mcp.run()
