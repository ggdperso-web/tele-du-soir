#!/usr/bin/env python3
"""Télécharge le guide TV des chaînes de la TNT (xmltvfr.fr) et le convertit
en un fichier JSON compact lu par l'appli : data/programmes.json"""
import gzip, io, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request, zipfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

CANDIDATES = [
    "https://xmltvfr.fr/xmltv/xmltv_tnt.xml.gz",
    "https://xmltvfr.fr/xmltv/xmltv_tnt.zip",
    "https://xmltvfr.fr/xmltv/xmltv_tnt.xml",
]
UA = {"User-Agent": "tele-du-soir/1.0 (+github actions)"}
DESC_MAX = 420
REVIEW_MAX = 700

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()

def discover():
    """Si les adresses connues ne répondent plus, cherche le lien TNT sur la page des fichiers."""
    html = get("https://xmltvfr.fr/xmltv.php").decode("utf-8", "replace")
    links = re.findall(r'https?://[^"\'\s<>]+tnt[^"\'\s<>]*\.(?:xml\.gz|zip|xml)', html, re.I)
    links += ["https://xmltvfr.fr/" + l.lstrip("/") for l in re.findall(r'["\'](/?xmltv/[^"\']*tnt[^"\']*\.(?:xml\.gz|zip|xml))', html, re.I)]
    return links

def unpack(raw):
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        return z.read([n for n in z.namelist() if n.endswith(".xml")][0])
    return raw

def download():
    errors = []
    for url in CANDIDATES:
        try:
            data = unpack(get(url))
            if b"<tv" in data[:2000]:
                return data, url
        except Exception as e:
            errors.append(f"{url}: {e}")
    try:
        for url in discover():
            try:
                data = unpack(get(url))
                if b"<tv" in data[:2000]:
                    return data, url
            except Exception as e:
                errors.append(f"{url}: {e}")
    except Exception as e:
        errors.append(f"découverte: {e}")
    sys.exit("Guide TV introuvable :\n" + "\n".join(errors))

def ts(s):
    s = s.strip()
    fmt = "%Y%m%d%H%M%S %z" if " " in s else "%Y%m%d%H%M%S"
    d = datetime.strptime(s, fmt)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())

def text(el, tag):
    c = el.find(tag)
    return (c.text or "").strip() if c is not None and c.text else ""

def convert(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    channels, order = {}, []
    for c in root.iter("channel"):
        cid = c.get("id")
        icon = c.find("icon")
        channels[cid] = {"id": cid, "name": text(c, "display-name") or cid,
                         "logo": icon.get("src") if icon is not None else ""}
        order.append(cid)

    now = int(time.time())
    progs = {cid: [] for cid in order}
    for p in root.iter("programme"):
        cid = p.get("channel")
        if cid not in progs:
            continue
        try:
            start, stop = ts(p.get("start")), ts(p.get("stop") or p.get("start"))
        except Exception:
            continue
        if stop < now - 6 * 3600:      # garde un peu d'historique pour la journée en cours
            continue
        item = {"s": start, "e": stop, "t": text(p, "title")}
        st = text(p, "sub-title")
        if st and st != item["t"]:
            item["st"] = st
        d = text(p, "desc")
        if d:
            item["d"] = d if len(d) <= DESC_MAX else d[:DESC_MAX].rsplit(" ", 1)[0] + "…"
        cat = text(p, "category")
        if cat:
            item["c"] = cat
        ic = p.find("icon")
        if ic is not None and ic.get("src"):
            item["i"] = ic.get("src")
        ep = p.find("episode-num[@system='xmltv_ns']")
        if ep is not None and ep.text:
            parts = (ep.text.split(".") + ["", ""])[:2]
            try:
                se, en = [int(x.split("/")[0]) + 1 if x.strip() else 0 for x in parts]
                if se > 1 or en > 1:
                    item["ep"] = [se, en]
            except ValueError:
                pass
        r = p.find("rating/value")
        if r is not None and r.text and r.text.strip() not in ("", "0", "Tout public", "TP"):
            item["r"] = r.text.strip()
        # Critiques et notes (presse, spectateurs) quand la source les fournit
        reviews = []
        for rv in p.findall("review"):
            txt = (rv.text or "").strip()
            if txt:
                txt = re.sub(r"<[^>]+>", " ", txt)
                txt = re.sub(r"\s+", " ", txt).strip()
                if len(txt) > REVIEW_MAX:
                    txt = txt[:REVIEW_MAX].rsplit(" ", 1)[0] + "…"
                reviews.append({"src": (rv.get("source") or rv.get("reviewer") or "").strip(), "t": txt})
        if reviews:
            item["rv"] = reviews[:4]
        stars = []
        for sr in p.findall("star-rating"):
            v = sr.find("value")
            m = re.match(r"\s*([\d.,]+)\s*/\s*([\d.,]+)", v.text if v is not None and v.text else "")
            if m:
                try:
                    stars.append({"s": (sr.get("system") or "").strip(), "v": round(float(m.group(1).replace(",", ".")), 1), "m": float(m.group(2).replace(",", "."))})
                except ValueError:
                    pass
        if stars:
            item["sr"] = stars[:4]
        cr = p.find("credits")
        if cr is not None:
            directors = [d.text.strip() for d in cr.findall("director") if d.text][:2]
            actors = [a.text.strip() for a in cr.findall("actor") if a.text][:4]
            if directors:
                item["dr"] = directors
            if actors:
                item["ac"] = actors
        year = text(p, "date")
        if year[:4].isdigit():
            item["y"] = int(year[:4])
        if p.find("new") is not None:
            item["n"] = 1
        if p.find("premiere") is not None:
            item["n"] = 1
        progs[cid].append(item)

    out_channels = []
    for cid in order:
        lst = sorted(progs[cid], key=lambda x: x["s"])
        if not lst:
            continue
        ch = dict(channels[cid])
        ch["p"] = lst
        out_channels.append(ch)
    return {"updated": now, "source": source, "channels": out_channels}

# ---------- Notes des spectateurs TMDB (films, séries, documentaires, émissions) ----------
# Clé gratuite à mettre dans les secrets GitHub sous le nom TMDB_KEY. Sans clé, cette étape est sautée.
TMDB_KEY = os.environ.get("TMDB_KEY", "").strip()
CACHE_FILE = "data/tmdb-cache.json"
SKIP = re.compile(r"m[ée]t[ée]o|journal|\binfos?\b|information|clips?|t[ée]l[ée]achat|culture infos|^autre$|loterie|programme ind|fin des programmes", re.I)
MOVIE = re.compile(r"film|cin[ée]ma|t[ée]l[ée]film|court m[ée]trage", re.I)
MIN_VOTES = 15

def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()

def tmdb(path, params):
    params = dict(params, language="fr-FR")
    headers = {"Accept": "application/json", "User-Agent": UA["User-Agent"]}
    if len(TMDB_KEY) > 60:
        headers["Authorization"] = "Bearer " + TMDB_KEY
    else:
        params["api_key"] = TMDB_KEY
    url = "https://api.themoviedb.org/3" + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + attempt * 2); continue
            if e.code in (401, 403):
                raise SystemExit("Clé TMDB refusée : vérifiez le secret TMDB_KEY.")
            return None
        except Exception:
            time.sleep(1)
    return None

def find_tmdb(title, kind, year):
    key = norm(title)
    if not key:
        return None
    path = "/search/movie" if kind == "movie" else "/search/tv"
    params = {"query": title, "include_adult": "false"}
    if year and kind == "movie":
        params["year"] = year
    res = tmdb(path, params)
    hits = (res or {}).get("results") or []
    if not hits and year and kind == "movie":
        hits = ((tmdb(path, {"query": title, "include_adult": "false"}) or {}).get("results")) or []
    for h in hits[:8]:
        names = [h.get("title"), h.get("original_title"), h.get("name"), h.get("original_name")]
        if key in [norm(n) for n in names if n]:
            if year and kind == "movie":
                y = (h.get("release_date") or "")[:4]
                if y.isdigit() and abs(int(y) - year) > 1:
                    continue
            return {"id": h["id"], "k": kind, "v": h.get("vote_average") or 0, "n": h.get("vote_count") or 0}
    return None

def enrich_tmdb(data):
    if not TMDB_KEY:
        print("TMDB : pas de clé, étape sautée.")
        return
    try:
        cache = json.load(open(CACHE_FILE, encoding="utf-8"))
    except Exception:
        cache = {}
    now = int(time.time())
    todo = {}
    for ch in data["channels"]:
        for p in ch["p"]:
            cat = p.get("c", "")
            if SKIP.search(cat) or len(p["t"]) < 2:
                continue
            kind = "movie" if MOVIE.search(cat) or MOVIE.search(p.get("st", "")) else "tv"
            todo.setdefault((p["t"], kind, p.get("y") if kind == "movie" else None), []).append(p)
    calls = 0
    for (title, kind, year), progs in todo.items():
        ck = f"{kind}|{norm(title)}|{year or ''}"
        hit = cache.get(ck)
        fresh = hit is not None and now - hit.get("ts", 0) < (30 if hit.get("id") else 7) * 86400
        if not fresh:
            found = find_tmdb(title, kind, year)
            # Une émission notée comme film peut être une série (et inversement)
            if not found:
                found = find_tmdb(title, "tv" if kind == "movie" else "movie", None)
            hit = dict(found or {}, ts=now)
            cache[ck] = hit
            calls += 1
            time.sleep(0.03)
        if hit.get("id") and hit.get("n", 0) >= MIN_VOTES:
            note = {"s": "TMDB", "v": round(hit["v"] / 2, 1), "m": 5.0, "n": hit["n"], "id": hit["id"], "k": hit["k"]}
            for p in progs:
                p["sr"] = [r for r in p.get("sr", []) if r.get("s") != "TMDB"] + [note]
    # Ménage : on oublie les entrées de plus de 60 jours
    cache = {k: v for k, v in cache.items() if now - v.get("ts", 0) < 60 * 86400}
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    noted = sum(1 for ch in data["channels"] for p in ch["p"] if any(r.get("s") == "TMDB" for r in p.get("sr", [])))
    print(f"TMDB : {calls} recherches, {noted} programmes avec une note des spectateurs.")

if __name__ == "__main__":
    if len(sys.argv) > 1:                         # test local : python convert.py fichier.xml
        raw, src = unpack(open(sys.argv[1], "rb").read()), sys.argv[1]
    else:
        raw, src = download()
    data = convert(raw, src)
    n = sum(len(c["p"]) for c in data["channels"])
    if n < 50:
        sys.exit(f"Trop peu de programmes ({n}), fichier ignoré.")
    os.makedirs("data", exist_ok=True)
    enrich_tmdb(data)
    with open("data/programmes.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(data['channels'])} chaînes, {n} programmes, source {src}")
