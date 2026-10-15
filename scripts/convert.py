#!/usr/bin/env python3
"""Télécharge le guide TV des chaînes de la TNT (xmltvfr.fr) et le convertit
en un fichier JSON compact lu par l'appli : data/programmes.json"""
import gzip, io, json, re, sys, time, urllib.request, zipfile
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

if __name__ == "__main__":
    if len(sys.argv) > 1:                         # test local : python convert.py fichier.xml
        raw, src = unpack(open(sys.argv[1], "rb").read()), sys.argv[1]
    else:
        raw, src = download()
    data = convert(raw, src)
    n = sum(len(c["p"]) for c in data["channels"])
    if n < 50:
        sys.exit(f"Trop peu de programmes ({n}), fichier ignoré.")
    import os
    os.makedirs("data", exist_ok=True)
    with open("data/programmes.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(data['channels'])} chaînes, {n} programmes, source {src}")
