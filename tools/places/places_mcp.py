# MCP server: places and travel via OpenStreetMap services (no API keys). Geocoding and place search (Nominatim,
# Overpass), routing for car/bike/foot (OSRM), and static map images rendered into the gallery.
import json, math, os, re, shutil, socket, sys, time, urllib.error, urllib.parse, urllib.request

if os.environ.get("FORCE_IPV4", "0") == "1":   # hosts with a broken IPv6 route: avoid long timeouts
    _orig_gai = socket.getaddrinfo
    def _gai4(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_gai(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _gai4
from typing import Optional
from mcp.server.fastmcp import FastMCP

UA = os.environ.get("PLACES_USER_AGENT", "goose-tools-places/1.0 (self-hosted agent)")   # OSM policy: identify yourself
NOMINATIM = "https://nominatim.openstreetmap.org"
OVERPASS = [u for u in os.environ.get("OVERPASS_URLS", "https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter").split(",") if u]
ROUTERS = {"car": "https://router.project-osrm.org/route/v1/driving/", "bike": "https://routing.openstreetmap.de/routed-bike/route/v1/driving/",
           "foot": "https://routing.openstreetmap.de/routed-foot/route/v1/driving/"}
HOME_LAT = float(os.environ.get("PLACES_HOME_LAT", "0") or 0); HOME_LON = float(os.environ.get("PLACES_HOME_LON", "0") or 0)
HOME_NAME = os.environ.get("PLACES_HOME_NAME", "")          # default "near" when none given, e.g. "Ballarat, Victoria"
COUNTRY = os.environ.get("PLACES_COUNTRY", "")                # ISO code to bias geocoding, e.g. "au"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
from goosetools_config import IMAGES, GALLERY_URL
IMAGE_DIR = os.path.join(IMAGES, "maps"); GALLERY = (GALLERY_URL + "/maps/") if GALLERY_URL else ""
mcp = FastMCP("places")
_last = [0.0]


def _get(url, timeout=30, data=None):
    gap = time.time() - _last[0]
    if gap < 1.1: time.sleep(1.1 - gap)                       # Nominatim/Overpass usage policy: 1 request per second
    _last[0] = time.time()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en-AU,en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _geocode(place, limit=1):
    if isinstance(place, (list, tuple)): return [{"lat": place[0], "lon": place[1], "display_name": f"{place[0]},{place[1]}"}]
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", str(place))
    if m: return [{"lat": float(m.group(1)), "lon": float(m.group(2)), "display_name": place}]
    foreign = re.search(r"\b(uk|england|usa|united states|new zealand|nz|japan|france|germany|canada|italy|spain|india|china|indonesia|bali|thailand|vietnam|singapore|australia)\b", place, re.I)
    params = {"q": place, "format": "jsonv2", "limit": limit, "addressdetails": 1}
    if not foreign:
        if COUNTRY: params["countrycodes"] = COUNTRY             # home-country results unless another country is named
        if HOME_NAME: params["viewbox"] = f"{HOME_LON - 1.5},{HOME_LAT + 1.0},{HOME_LON + 1.5},{HOME_LAT - 1.0}"   # prefer the home region
    rs = _get(f"{NOMINATIM}/search?" + urllib.parse.urlencode(params))
    if not rs and not foreign:
        params.pop("viewbox", None); rs = _get(f"{NOMINATIM}/search?" + urllib.parse.urlencode(params))
    out = [{"lat": float(r["lat"]), "lon": float(r["lon"]), "display_name": r["display_name"], "type": r.get("type"), "address": r.get("address", {})} for r in rs]
    if not out and not foreign and HOME_NAME:                  # last resort: a named feature near home (e.g. "<Town> Town Hall")
        words = re.sub(r"[^\w ]", " ", place).strip()
        q = f'[out:json][timeout:25];nwr["name"~"{re.escape(words)}",i](around:80000,{HOME_LAT},{HOME_LON});out center 3;'
        for url in OVERPASS:
            try:
                els = _get(url, timeout=45, data=urllib.parse.urlencode({"data": q}).encode())["elements"]
                for e in els:
                    la = e.get("lat") or (e.get("center") or {}).get("lat"); lo = e.get("lon") or (e.get("center") or {}).get("lon")
                    if la is not None: out.append({"lat": la, "lon": lo, "display_name": e.get("tags", {}).get("name", words) + ", near " + HOME_NAME, "type": "osm"})
                if out: break
            except Exception:
                continue
    if not out:
        raise RuntimeError(f"could not find a place called '{place}'; try a town, suburb or street address")
    return out


def _haversine(a, b):
    R = 6371.0; la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


@mcp.tool()
def geocode(place: str, limit: int = 3) -> list:
    """Find a place: name/address -> coordinates and full address. Home-country places are assumed unless a country is given."""
    return _geocode(place, max(1, min(int(limit), 10)))


@mcp.tool()
def find_places(what: str, near: Optional[str] = None, radius_km: float = 5.0, limit: int = 10) -> list:
    """Find places of a kind near a location, e.g. what="pharmacy", "cafe", "supermarket", "fuel", "playground", "hospital",
    "atm", "hardware store", near="<town>" (default: the configured home). Returns name, type, distance, address, opening hours,
    phone and website where OpenStreetMap has them. Uses Overpass, falling back to Nominatim."""
    if not near and not HOME_NAME: raise RuntimeError("give a `near` location (no PLACES_HOME_NAME configured)")
    centre = _geocode(near or HOME_NAME)[0]; lat, lon = centre["lat"], centre["lon"]
    r = int(max(0.2, min(float(radius_km), 50)) * 1000)
    tagmap = {"pharmacy": '["amenity"="pharmacy"]', "chemist": '["amenity"="pharmacy"]', "cafe": '["amenity"="cafe"]', "coffee": '["amenity"="cafe"]',
              "restaurant": '["amenity"="restaurant"]', "pub": '["amenity"="pub"]', "bar": '["amenity"="bar"]', "fast food": '["amenity"="fast_food"]',
              "supermarket": '["shop"="supermarket"]', "grocery": '["shop"~"supermarket|convenience"]', "fuel": '["amenity"="fuel"]', "petrol": '["amenity"="fuel"]',
              "hospital": '["amenity"="hospital"]', "doctor": '["amenity"~"doctors|clinic"]', "gp": '["amenity"~"doctors|clinic"]', "dentist": '["amenity"="dentist"]',
              "atm": '["amenity"="atm"]', "bank": '["amenity"="bank"]', "post office": '["amenity"="post_office"]', "library": '["amenity"="library"]',
              "playground": '["leisure"="playground"]', "park": '["leisure"="park"]', "pool": '["leisure"="swimming_pool"]', "gym": '["leisure"="fitness_centre"]',
              "hardware": '["shop"~"hardware|doityourself"]', "hardware store": '["shop"~"hardware|doityourself"]', "bakery": '["shop"="bakery"]',
              "butcher": '["shop"="butcher"]', "bottle shop": '["shop"="alcohol"]', "hotel": '["tourism"~"hotel|motel"]', "motel": '["tourism"~"hotel|motel"]',
              "caravan park": '["tourism"="caravan_site"]', "camping": '["tourism"~"camp_site|caravan_site"]', "toilet": '["amenity"="toilets"]',
              "ev charger": '["amenity"="charging_station"]', "charging": '["amenity"="charging_station"]', "school": '["amenity"="school"]',
              "vet": '["amenity"="veterinary"]', "police": '["amenity"="police"]', "market": '["amenity"="marketplace"]'}
    key = what.lower().strip()
    sel = tagmap.get(key) or f'["name"~"{re.escape(what)}",i]'
    query = f'[out:json][timeout:25];nwr{sel}(around:{r},{lat},{lon});out center tags {max(1, min(int(limit), 30)) * 2};'
    elements = None
    for url in OVERPASS:
        try:
            elements = _get(url, timeout=45, data=urllib.parse.urlencode({"data": query}).encode())["elements"]; break
        except Exception:
            continue
    results = []
    if elements is not None:
        for e in elements:
            t = e.get("tags", {}); la = e.get("lat") or (e.get("center") or {}).get("lat"); lo = e.get("lon") or (e.get("center") or {}).get("lon")
            if la is None or not t.get("name"): continue
            addr = " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:suburb") or t.get("addr:city")] if x)
            results.append({"name": t.get("name"), "type": t.get("amenity") or t.get("shop") or t.get("leisure") or t.get("tourism"),
                            "distance_km": round(_haversine((lat, lon), (la, lo)), 1), "address": addr or None, "opening_hours": t.get("opening_hours"),
                            "phone": t.get("phone") or t.get("contact:phone"), "website": t.get("website") or t.get("contact:website"), "lat": la, "lon": lo})
    else:  # Nominatim fallback (bounded box ~ radius)
        d = r / 111000.0
        rs = _get(f"{NOMINATIM}/search?" + urllib.parse.urlencode({"q": what, "format": "jsonv2", "limit": limit, "bounded": 1, "addressdetails": 1,
                                                                  "viewbox": f"{lon - d},{lat + d},{lon + d},{lat - d}"}))
        for x in rs:
            results.append({"name": x.get("name") or x["display_name"].split(",")[0], "type": x.get("type"),
                            "distance_km": round(_haversine((lat, lon), (float(x["lat"]), float(x["lon"]))), 1), "address": x["display_name"],
                            "lat": float(x["lat"]), "lon": float(x["lon"])})
    results.sort(key=lambda x: x["distance_km"])
    return results[:max(1, min(int(limit), 30))] or [{"note": f"nothing tagged as '{what}' within {radius_km} km of {centre['display_name'][:60]}"}]


@mcp.tool()
def route(origin: str, destination: str, mode: str = "car", waypoints: Optional[list] = None) -> dict:
    """Travel distance, duration and turn-by-turn summary between places (names, addresses or 'lat,lon'). mode: car, bike or foot.
    Optional waypoints in between. Durations are typical, without live traffic."""
    mode = mode.lower()
    if mode not in ROUTERS: raise RuntimeError("mode must be car, bike or foot")
    pts = [_geocode(origin)[0]] + [_geocode(w)[0] for w in (waypoints or [])] + [_geocode(destination)[0]]
    coords = ";".join(f"{p['lon']},{p['lat']}" for p in pts)
    try:
        res = _get(ROUTERS[mode] + coords + "?overview=false&steps=true", timeout=40)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"routing service error {e.code}: {e.read().decode(errors='replace')[:200]} (coords {coords})")
    if res.get("code") != "Ok" or not res.get("routes"): raise RuntimeError(f"no route found: {res.get('message') or res.get('code')}")
    rt = res["routes"][0]; steps = []
    for leg in rt["legs"]:
        for s in leg["steps"]:
            nm = s.get("name") or ""; mv = s.get("maneuver", {}); d = s.get("distance", 0)
            if d >= 300 or mv.get("type") in ("depart", "arrive"):
                steps.append(f"{mv.get('type', '')} {mv.get('modifier', '') or ''} {('onto ' + nm) if nm else ''} ({d / 1000:.1f} km)".replace("  ", " ").strip())
    return {"mode": mode, "from": pts[0]["display_name"][:80], "to": pts[-1]["display_name"][:80], "distance_km": round(rt["distance"] / 1000, 1),
            "duration_min": round(rt["duration"] / 60), "duration_text": f"{int(rt['duration'] // 3600)} h {int(rt['duration'] % 3600 // 60)} min" if rt["duration"] >= 3600 else f"{round(rt['duration'] / 60)} min",
            "steps": steps[:25]}


@mcp.tool()
def distances(origin: str, destinations: list, mode: str = "car") -> list:
    """Distance and travel time from one place to several (up to 10), sorted by time. Useful for 'which is closest'."""
    out = []
    for d in destinations[:10]:
        try:
            r = route(origin, d, mode); out.append({"to": d, "distance_km": r["distance_km"], "duration_min": r["duration_min"]})
        except Exception as e:
            out.append({"to": d, "error": str(e)[:100]})
    return sorted(out, key=lambda x: x.get("duration_min", 1e9))


@mcp.tool()
def map_image(places: list, title: Optional[str] = None, zoom: Optional[int] = None) -> dict:
    """Render a map (OpenStreetMap tiles) with numbered markers for up to 12 places (names, addresses or 'lat,lon') into the
    gallery, for showing the user where things are. Returns the image path, gallery URL and the marker legend."""
    import subprocess
    pts = []
    for p in places[:12]:
        g = _geocode(p)[0]; pts.append((g["lat"], g["lon"], (str(p) if not re.match(r"^\s*-?\d", str(p)) else g["display_name"].split(",")[0])[:40]))
    os.makedirs(IMAGE_DIR, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", (title or "map-" + time.strftime("%H%M%S")).lower()).strip("-")[:40]
    out = os.path.join(IMAGE_DIR, stem + ".png")
    code = f"""
from staticmap import StaticMap, CircleMarker
from staticmap.staticmap import _lon_to_x, _lat_to_y
import json
pts = {json.dumps(pts)}
m = StaticMap(1100, 760, url_template='https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', headers={{'User-Agent': {UA!r}}})
for i,(la,lo,_) in enumerate(pts):
    m.add_marker(CircleMarker((lo, la), '#ffffff', 22)); m.add_marker(CircleMarker((lo, la), '#2563EB', 16))
img = m.render({'zoom=' + str(int(zoom)) if zoom else ''})
from PIL import ImageDraw, ImageFont
d = ImageDraw.Draw(img)
try: f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 15)
except Exception: f = None
# number the markers
for i,(la,lo,_) in enumerate(pts):
    x, y = m._x_to_px(_lon_to_x(lo, m.zoom)), m._y_to_px(_lat_to_y(la, m.zoom))
    d.text((x-5 if i < 9 else x-9, y-9), str(i+1), fill='white', font=f)
d.rectangle([0, img.height-18, img.width, img.height], fill=(255,255,255,200)); d.text((6, img.height-16), '© OpenStreetMap contributors', fill='#374151', font=f)
img.save({out!r})
"""
    res = subprocess.run([shutil.which("uv") or "uv", "run", "--with", "staticmap", "--with", "pillow", "python", "-I", "-c", code],
                         capture_output=True, text=True, timeout=180)
    if res.returncode != 0: raise RuntimeError("map render failed: " + res.stderr[-300:])
    return {"path": out, "url": (GALLERY + os.path.basename(out)) if GALLERY else None, "legend": [f"{i + 1}. {n}" for i, (_, _, n) in enumerate(pts)]}


if __name__ == "__main__":
    mcp.run()
