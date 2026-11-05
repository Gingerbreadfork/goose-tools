# Goose voice agent: a LiveKit voice pipeline against any OpenAI-compatible server (STT, chat, TTS endpoints).
#   ears  : /audio/transcriptions (ASR_MODEL)  brain : /chat/completions (CHAT_MODEL)
#   mouth : /audio/speech (TTS_MODEL, VOICE)   turns : Silero VAD + local end-of-turn model (CPU)
# Slow jobs are handed to the full Goose agent and the result comes back via the notifier (e.g. Signal).
import asyncio, datetime as dt, json, logging, os, subprocess, sys, urllib.parse, urllib.request
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, TurnHandlingOptions, function_tool
from livekit.plugins import openai, silero
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel   # local end-of-turn model (CPU)
    except Exception:
        MultilingualModel = None

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
HALOGEN = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "none")
VOICE = os.environ.get("GOOSE_VOICE", "alloy")
ASR_MODEL = os.environ.get("ASR_MODEL", "whisper-1"); CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o-mini"); TTS_MODEL = os.environ.get("TTS_MODEL", "tts-1")
HOME_PLACE = os.environ.get("PLACES_HOME_NAME", "the user's home")
TOOLS_DIR = os.environ.get("GOOSE_TOOLS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
log = logging.getLogger("goose-voice")
sys.path.insert(0, os.path.join(TOOLS_DIR, "reminders"))
import reminders_store as rs

INSTRUCTIONS = f"""You are Goose, a voice assistant running on the user's home server near {HOME_PLACE}.
You are talking out loud, so: answer in one to three short sentences, plain spoken language, no lists, no markdown, no
URLs, no code. Say numbers the way people say them. If a question needs real research, browsing, documents or files, do not
guess: call hand_to_goose with a clear task and tell the user it is being worked on and will arrive on Signal. Use get_weather
for weather, get_time for the date or time, and set_reminder / list_reminders for reminders (they arrive on the user's phone). Be warm, direct and brief. If you did not catch something, ask them to repeat it."""


class GooseVoice(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    @function_tool()
    async def get_time(self, context: RunContext) -> str:
        """The current local date and time."""
        return dt.datetime.now().strftime("%A %d %B %Y, %I:%M %p")

    @function_tool()
    async def get_weather(self, context: RunContext, place: str = "") -> str:
        """Current weather and today's forecast for a place (default: the user's home)."""
        place = place or os.environ.get("PLACES_HOME_NAME") or "London"
        def fetch():
            g = json.load(urllib.request.urlopen("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": place, "count": 1}), timeout=15))
            r = g["results"][0]
            f = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
                "latitude": r["latitude"], "longitude": r["longitude"], "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,weather_code,wind_speed_10m", "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"}), timeout=15))
            c, d = f["current"], f["daily"]
            return (f"{r['name']}: currently {round(c['temperature_2m'])} degrees, wind {round(c['wind_speed_10m'])} km/h. "
                    f"Today high {round(d['temperature_2m_max'][0])}, low {round(d['temperature_2m_min'][0])}, rain chance {d['precipitation_probability_max'][0]} percent.")
        try:
            return await asyncio.get_event_loop().run_in_executor(None, fetch)
        except Exception as e:
            return f"Weather lookup failed: {e}"

    @function_tool()
    async def set_reminder(self, context: RunContext, text: str, when: str, repeat: str = "none") -> str:
        """Set a reminder sent to the user's phone. `when`: '+20m', '+2h', '18:30', '7am', 'tomorrow 09:00', 'fri 17:00'.
        `repeat`: none, daily, weekdays, weekly, monthly."""
        try:
            item = rs.add(text, when, repeat, source="voice")
            return "Set for " + dt.datetime.fromisoformat(item["when"]).strftime("%A %I:%M %p") + "."
        except ValueError as e:
            return f"I could not understand that time: {e}"

    @function_tool()
    async def list_reminders(self, context: RunContext) -> str:
        """The user's pending reminders."""
        items = rs.pending()
        return "; ".join(rs.describe(i) for i in items[:8]) if items else "No reminders set."

    @function_tool()
    async def hand_to_goose(self, context: RunContext, task: str) -> str:
        """Hand a task that needs tools (web research, browsing, documents, files, images, server checks) to the full Goose
        agent. It runs in the background and sends the result to the user's Signal. Give a complete, specific task."""
        def run():
            env = dict(os.environ)
            prompt = (task + "\n\n(This task came from a voice call. When done, send the result to the user with send_notification, "
                      "title 'From your call', concise and in plain text.)")
            import shutil
            subprocess.Popen([os.environ.get("GOOSE_BIN") or shutil.which("goose") or os.path.expanduser("~/.local/bin/goose"), "run", "-q", "--no-session", "--max-turns", "40", "-t", prompt],
                             cwd=os.path.expanduser("~"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.get_event_loop().run_in_executor(None, run)
        log.info("handed to goose: %s", task[:120])
        return "Handed over. Tell the user it is being worked on and the answer will arrive on Signal in a few minutes."


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    try:
        turn_detection = MultilingualModel() if MultilingualModel else "vad"
    except Exception as e:  # model not downloaded: fall back to VAD-only turn detection
        log.warning("turn detector unavailable (%s); using VAD", e)
        turn_detection = "vad"

    session = AgentSession(
        vad=silero.VAD.load(min_silence_duration=0.45, activation_threshold=0.55),
        stt=openai.STT(model=ASR_MODEL, base_url=HALOGEN, api_key=KEY, use_realtime=False, language=os.environ.get("ASR_LANGUAGE", "en"),
                       prompt=os.environ.get("ASR_PROMPT", "Goose")),
        llm=openai.LLM(model=CHAT_MODEL, base_url=HALOGEN, api_key=KEY, temperature=0.6, max_completion_tokens=220,
                       extra_body=json.loads(os.environ.get("CHAT_EXTRA_BODY", "{}"))),
        tts=openai.TTS(model=TTS_MODEL, voice=VOICE, base_url=HALOGEN, api_key=KEY, response_format="pcm", sample_rate=int(os.environ.get("TTS_SAMPLE_RATE", "24000"))),
        turn_handling=TurnHandlingOptions(turn_detection=turn_detection),
        min_endpointing_delay=0.4,
        max_endpointing_delay=3.0,
        preemptive_generation=True,
    )
    await session.start(room=ctx.room, agent=GooseVoice())
    await session.generate_reply(instructions="Greet the user in one short sentence and ask what they need.")


if __name__ == "__main__":
    agents.cli.run_app(server)
