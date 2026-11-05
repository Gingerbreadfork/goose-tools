# MCP server: weather (Open-Meteo, no key) and RSS/Atom feeds (feedparser). For daily-briefing style automations.
import html, json, re, urllib.parse, urllib.request
from typing import Optional
import feedparser
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("briefing")
UA = {"User-Agent": "goose-briefing/1.0"}
WMO = {0:"clear",1:"mostly clear",2:"partly cloudy",3:"overcast",45:"fog",48:"icy fog",51:"light drizzle",53:"drizzle",55:"heavy drizzle",
       56:"freezing drizzle",57:"heavy freezing drizzle",61:"light rain",63:"rain",65:"heavy rain",66:"freezing rain",67:"heavy freezing rain",
       71:"light snow",73:"snow",75:"heavy snow",77:"snow grains",80:"light showers",81:"showers",82:"violent showers",85:"snow showers",
       86:"heavy snow showers",95:"thunderstorm",96:"thunderstorm with hail",99:"thunderstorm with heavy hail"}

def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)

@mcp.tool()
def weather_forecast(location: str, days: int = 3, units: str = "metric") -> dict:
    """Current conditions and a daily forecast for a place name (city, town, or 'City, Country'). `days` 1-7.
    `units` is 'metric' (C, km/h, mm) or 'imperial' (F, mph, inch). No API key needed."""
    g = _get("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": location, "count": 1, "language": "en"}))
    if not g.get("results"): return {"error": f"location not found: {location}"}
    r = g["results"][0]
    q = {"latitude": r["latitude"], "longitude": r["longitude"], "timezone": "auto", "forecast_days": max(1, min(int(days), 7)),
         "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
         "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,sunrise,sunset,uv_index_max"}
    if units == "imperial": q.update(temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch")
    f = _get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q))
    c, d = f["current"], f["daily"]
    return {"place": ", ".join(x for x in [r.get("name"), r.get("admin1"), r.get("country")] if x), "timezone": f.get("timezone"), "units": units,
            "now": {"time": c["time"], "temp": c["temperature_2m"], "feels_like": c["apparent_temperature"], "humidity_pct": c["relative_humidity_2m"],
                    "conditions": WMO.get(c["weather_code"], str(c["weather_code"])), "wind": c["wind_speed_10m"], "precipitation": c["precipitation"]},
            "daily": [{"date": d["time"][i], "conditions": WMO.get(d["weather_code"][i], str(d["weather_code"][i])), "high": d["temperature_2m_max"][i],
                       "low": d["temperature_2m_min"][i], "rain_chance_pct": d["precipitation_probability_max"][i], "precipitation": d["precipitation_sum"][i],
                       "wind_max": d["wind_speed_10m_max"][i], "uv_max": d["uv_index_max"][i], "sunrise": d["sunrise"][i][-5:], "sunset": d["sunset"][i][-5:]}
                      for i in range(len(d["time"]))]}

def _clean(s, n=300):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or "")); s = re.sub(r"\s+", " ", s).strip()
    return s[:n] + ("…" if len(s) > n else "")

def _feed(url, limit, summary_chars):
    f = feedparser.parse(url, agent=UA["User-Agent"])
    if f.bozo and not f.entries: return {"feed": url, "error": str(getattr(f, "bozo_exception", "could not parse feed"))}
    items = [{"title": _clean(e.get("title"), 200), "link": e.get("link"), "published": e.get("published") or e.get("updated"),
              "summary": _clean(e.get("summary") or (e.get("content") or [{}])[0].get("value"), summary_chars)} for e in f.entries[:limit]]
    return {"feed": f.feed.get("title") or url, "url": url, "items": items}

@mcp.tool()
def read_feed(url: str, limit: int = 10, summary_chars: int = 300) -> dict:
    """Read an RSS or Atom feed and return its latest items (title, link, published, summary). `limit` max 50."""
    return _feed(url, max(1, min(int(limit), 50)), int(summary_chars))

@mcp.tool()
def read_feeds(urls: list, limit_each: int = 5, summary_chars: int = 200) -> list:
    """Read several RSS/Atom feeds at once and return the latest items of each. Good for a news or blog roundup."""
    return [_feed(u, max(1, min(int(limit_each), 20)), int(summary_chars)) for u in urls[:20]]

if __name__ == "__main__":
    mcp.run()
