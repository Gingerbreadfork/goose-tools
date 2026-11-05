# goose-tools

A collection of extensions, services and recipes that turn a [Goose](https://github.com/aaif-goose/goose) server into a
capable, private personal assistant: one that can see, read documents, analyse data, browse, transcribe media, find
places, remember things, ask you before acting, watch web pages, and talk to you on your phone or in a live voice call.

Everything runs on your own hardware against any **OpenAI-compatible model server** (Halogen, llama.cpp, vLLM, Ollama,
LM Studio, or the OpenAI API itself). No tool in this repo requires a third-party API key; the only external services used
are OpenStreetMap, Open-Meteo and RSS feeds, all keyless.

Each tool is an independent [MCP](https://modelcontextprotocol.io) server. They work with Goose's desktop app and CLI,
with scheduled recipes, and with any other MCP client.

## What's here

| Tool | What it gives the agent | Needs |
|---|---|---|
| `decisions` | Fast calibrated yes/no, multiple-choice and scored decisions (routing, triage, guardrails) | a Jev / System One compatible endpoint (e.g. Halogen `/v1/systemone`) |
| `vision` | Look at any image by path or URL and answer questions about it | a vision-capable chat model |
| `imagegen` | Generate images; returns a displayable link plus the saved file | an `/images/generations` endpoint |
| `briefing` | Weather for any place and RSS/Atom feed reading (news briefings) | nothing |
| `places` | Geocoding, "X near Y" with opening hours, car/bike/foot routing, distance tables, map images | nothing (OpenStreetMap) |
| `documents` | PDF/Word/PowerPoint/Excel/HTML to clean markdown with tables, outlines, table extraction, page rendering for figures, OCR | Docling service (`scripts/start-docling.sh`) |
| `media` | Transcribe YouTube/podcast URLs or local audio/video with timestamps | yt-dlp + ffmpeg (local or in the lab container), an `/audio/transcriptions` endpoint |
| `lab` | Persistent Python sandbox: pandas/polars/duckdb, stats, ML, styled charts, formatted Excel, PDF and Word reports | the lab container (`scripts/start-lab.sh`) |
| `remote-files` | Makes Goose Desktop attachments work when the agent runs on a server: fetches files from the computer you're using, sends results back | a tiny agent on the client machine |
| `signal` | Two-way chat with Goose over Signal (with live progress reactions and image attachments) and a notification tool | signal-cli-rest-api (`scripts/start-signal.sh`) |
| `approvals` | "Ask the user yes/no on Signal and wait" for anything irreversible | the Signal bridge |
| `reminders` | Reminders and timers with repeats, delivered to your phone | a notifier backend |
| `watchers` | Watch web pages for a condition (price drop, back in stock, new item) and alert when it becomes true | a notifier; optionally the browser for JavaScript pages |
| `voice/` | A live voice call with the assistant (LiveKit): local speech recognition, chat model, speech synthesis, turn detection, interruptions | Docker, an OpenAI-compatible server with STT/TTS |

Plus `scripts/` for the supporting services (browser, document converter, lab container, Signal bridge, image gallery,
server health report) and `recipes/` for scheduled jobs (daily news, server health, release watch, watchers).

## Design notes

- **Configuration is environment only.** Copy `config/example.env` to `.env`; every tool reads what it needs. Nothing is
  hard-coded to a machine, user, address or model name.
- **Files, not blobs.** Tools save images, reports and transcripts under `GOOSE_WORK` and return paths. If you set
  `GALLERY_URL` (an HTTPS server for `GOOSE_WORK/images`, see `scripts/start-gallery.sh`) they also return links a chat
  client can render. Goose Desktop only displays https images and pins its server's certificate, so the gallery reuses it.
- **Small models welcome.** Tool descriptions are written to steer a 6B-active model well, and decisions use a calibrated
  classifier instead of asking the chat model to reason.
- **Isolation where it matters.** The lab runs code in a container with read-only mounts of your folders; the browser
  runs in a container with isolated contexts; the file agent on client machines only answers the server and only reads
  exact paths plus a short list of listable folders.

## Install

Requirements: Linux server, Python 3.10+, [uv](https://docs.astral.sh/uv/), Docker, Goose 1.5x.

```bash
git clone <this repo> ~/goose-tools
cd ~/goose-tools
cp config/example.env .env && $EDITOR .env          # model server, work folder, notifier, home location
mkdir -p ~/goose-work
```

Then add the extensions you want to `~/.config/goose/config.yaml` from `config/goose-config.example.yaml`, replacing
`/PATH/TO/goose-tools`, and restart Goose (`systemctl --user restart goose-serve` if you run it as a service). Optionally
append `config/goosehints.example` to `~/.config/goose/.goosehints`; those hints noticeably improve how the agent uses
the tools.

Test a tool without Goose:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
               '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
               '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | bin/run-tool.sh briefing
```

### Supporting services

| Service | Start | Notes |
|---|---|---|
| Document converter | `scripts/start-docling.sh` | Docling, CPU image, models bundled, ~7.5 GB |
| Lab container | `docker build -t goose-lab:latest tools/lab/container && scripts/start-lab.sh` | pandas, polars, duckdb, scipy, sklearn, matplotlib, weasyprint, yt-dlp, ffmpeg |
| Browser | `scripts/start-browser.sh` | Playwright MCP, headless Chromium; register as `streamable_http` |
| Image gallery | `scripts/start-gallery.sh` | nginx over TLS, serves `GOOSE_WORK/images` |
| Signal | `SIGNAL_MODE=normal scripts/start-signal.sh`, then `scripts/signal-link.sh` and scan from Signal > Linked devices, then `scripts/start-signal.sh` | links the bridge to your own account (chat happens in Note to Self), or register a separate number |
| Signal bridge, reminders | `config/systemd/*.service` into `~/.config/systemd/user/`, edit paths, `systemctl --user enable --now ...` | user units, survive reboots with `loginctl enable-linger` |
| Web search | `isokoliuk/mcp-searxng` against a local SearXNG with JSON enabled | not in this repo; see `config/goose-config.example.yaml` |

### Recipes and schedules

`recipes/` holds scheduled jobs. Edit the placeholders (towns, feeds, installed versions, `/PATH/TO`), then:

```bash
goose schedule add --schedule-id daily-news --cron "0 17 * * *" --recipe-source recipes/daily-news.yaml
goose schedule add --schedule-id server-health --cron "0 8 * * *" --recipe-source recipes/server-health.yaml
goose schedule add --schedule-id release-watch --cron "0 8 * * 1" --recipe-source recipes/release-watch.yaml
goose schedule add --schedule-id watchers --cron "0 * * * *" --recipe-source recipes/watchers.yaml
```

Goose copies the recipe into its own store at add time; re-add after editing. A recipe lists exactly the extensions it
needs, so heavy tools (the browser, say) can stay disabled in normal chats and still be used by jobs.

### Goose Desktop on another machine

When the desktop app talks to a remote `goose serve`, attachments are sent as paths on *your* machine. Install the file
agent there and the paths resolve transparently:

```bash
bash tools/remote-files/install-goose-files-agent.sh <server-host>     # Linux; paste REMOTE_FILES_TOKEN when asked
```

The server finds the client by itself (it's the machine connected to `goose serve`), so there is nothing to register.
The agent is a single Python file and also runs on macOS and Windows.

### Voice

`voice/` contains a docker compose stack (LiveKit server, token service, an HTTPS call page) and `agent.py`, a
LiveKit Agents pipeline wired to your model server's transcription, chat and speech endpoints with Silero VAD and a
local end-of-turn model. Copy `voice/example.env` to `voice/.env`, generate keys, set `node_ip` in `livekit.yaml`, then:

```bash
cd voice && docker compose up -d --build
uv venv .venv && . .venv/bin/activate && uv pip install "livekit-agents[openai,silero,turn-detector]~=1.8" livekit-api python-dotenv
python agent.py download-files && python agent.py start      # or install config/systemd/goose-voice.service
```

Open `https://<host>:8444/` on a phone or desktop on the same network and tap the orb. Slow jobs are handed to the full
Goose agent and the result arrives via your notifier.

## Layout

```
bin/            run-tool.sh (MCP launchers), run-service.sh (daemons)
config/         example.env, Goose config snippets, hints, systemd unit templates
tools/<name>/   one MCP server per folder; tools/common has the shared config and notifier
scripts/        start scripts for supporting containers, health report, gallery nginx config
recipes/        scheduled jobs
voice/          LiveKit stack and voice agent
docs/           longer notes per tool (grows over time)
```

## Adding a tool

1. Create `tools/<name>/<name>_mcp.py` using `mcp.server.fastmcp.FastMCP` (pin `mcp<2` until the 2.x API is adopted).
2. Read settings through `tools/common/goosetools_config.py` and notify through `tools/common/notifier.py`.
3. Add a launcher line to `bin/run-tool.sh`, an entry to `config/goose-config.example.yaml`, a row to the table above, and
   a line to `CHANGELOG.md`.
4. Keep tool docstrings short and operational: they are what the model reads.

## Status

Used daily on a single home server; expect rough edges on other setups and please report them. Contributions welcome.

MIT licensed.
