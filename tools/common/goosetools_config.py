"""Shared configuration for the goose-tools collection. Everything is read from environment variables so the same code
runs on any machine. Load a .env file first (the launchers do) or export the variables yourself.

  OPENAI_BASE_URL      OpenAI-compatible API root, e.g. http://127.0.0.1:8731/v1 (Halogen, llama.cpp, vLLM, Ollama, OpenAI...)
  OPENAI_API_KEY       key for that server (any string if the server does not check)
  GOOSE_WORK           working folder for files the tools produce (default ~/goose-work)
  GALLERY_URL          optional https URL that serves GOOSE_WORK/images (so chat clients can display images); empty = paths only
  HOST_HOME            optional: the home directory as seen on the host (used inside containers to map paths)
"""
import os

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "none")
WORK = os.path.expanduser(os.environ.get("GOOSE_WORK", "~/goose-work"))
IMAGES = os.path.join(WORK, "images")
GALLERY_URL = os.environ.get("GALLERY_URL", "").rstrip("/")


def gallery(path: str) -> str | None:
    """Public URL for a file under GOOSE_WORK/images, or None when no gallery is configured."""
    if not GALLERY_URL: return None
    rel = os.path.relpath(path, IMAGES)
    return None if rel.startswith("..") else f"{GALLERY_URL}/{rel}"


def image_ref(path: str) -> str:
    """How a tool should refer to an image in its result: markdown link via the gallery when available, else the path."""
    url = gallery(path)
    return f"![{os.path.basename(path)}]({url})\nSaved: {path}" if url else f"Saved: {path}"
