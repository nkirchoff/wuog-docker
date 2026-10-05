"""Spinitron collector for WUOG.

Pulls the station calendar feed (every show, with its Spinitron category) and the
spins inside each logged playlist into SQLite. Incremental and polite: one
request per `interval` seconds, per Spinitron's robots.txt Crawl-delay.
"""
import json
import logging
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://spinitron.com"
log = logging.getLogger("wuog.collector")

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY,          -- Spinitron playlist id
    show_id INTEGER,
    title TEXT, dj TEXT, category TEXT, description TEXT,
    start TEXT, end TEXT,            -- ISO 8601 with offset
    url TEXT, duplicate INTEGER DEFAULT 0,
    fetched_at TEXT, n_spins INTEGER
);
CREATE TABLE IF NOT EXISTS slots (    -- scheduled shows with no playlist logged
    show_id INTEGER, start TEXT, end TEXT,
    title TEXT, dj TEXT, category TEXT, url TEXT,
    PRIMARY KEY (show_id, start)
);
CREATE TABLE IF NOT EXISTS spins (
    id INTEGER PRIMARY KEY,          -- Spinitron spin id
    playlist_id INTEGER REFERENCES playlists(id),
    ts TEXT, artist TEXT, song TEXT, release TEXT, label TEXT,
    released TEXT, isrc TEXT, local INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feed_weeks (week_start TEXT PRIMARY KEY, fetched_at TEXT);
CREATE INDEX IF NOT EXISTS spins_ts ON spins(ts);
CREATE INDEX IF NOT EXISTS playlists_start ON playlists(start);
"""


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")      # readers never wait on a long sync
    db.executescript(SCHEMA)
    return db


def migrate(db):
    # Rows stored before automation got its own category (see is_automation).
    db.execute("""UPDATE playlists SET category='Automation' WHERE coalesce(category,'') != 'Automation'
                  AND (upper(trim(title))='AUTOMATION' OR title LIKE 'WUOG 90.5FM%'
                       OR trim(dj) IN ('Automation','DJ Automatic DJ','Automatic DJ'))""")
    db.commit()


class Spinitron:
    def __init__(self, station, interval=10, user_agent="wuog-semester-playlists/2.0 (personal, non-commercial)"):
        self.station = station
        self.interval = interval
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._last = 0.0

    def get(self, path, **params):
        for attempt in range(5):
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.session.get(BASE + path, params=params, timeout=30)
            except requests.RequestException as e:
                self._last = time.monotonic()
                log.warning("GET %s failed (%s); retrying", path, e)
                time.sleep(30 * (attempt + 1))
                continue
            self._last = time.monotonic()        # crawl delay counts from the end of a response
            if r.status_code in (429, 500, 502, 503, 504):
                log.warning("GET %s -> %s; backing off", path, r.status_code)
                time.sleep(60 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"giving up on {path}")

    def calendar(self, start, end):
        return self.get(f"/{self.station}/calendar-feed", timeslot=30,
                        start=start.isoformat(), end=end.isoformat()).json()

    def playlist(self, url):
        return self.get(url).text


def parse_playlist(html, start_iso, tz):
    """Return (header dict, list of spin dicts) from a playlist page."""
    soup = BeautifulSoup(html, "html.parser")
    head = soup.select_one("div.head.playlist")
    header = {}
    if head:
        show = head.select_one("h3.show-title a")
        if show and (m := re.search(r"/show/(\d+)/", show.get("href", ""))):
            header["show_id"] = int(m.group(1))
        desc = head.select_one("div.description")
        header["description"] = desc.get_text(" ", strip=True) if desc else None

    start = datetime.fromisoformat(start_iso).astimezone(tz)
    spins = []
    for row in soup.select("tr.spin-item"):
        def text(sel):
            el = row.select_one(sel)
            return el.get_text(strip=True) if el else None

        meta = json.loads(row.get("data-spin") or "{}")
        t = datetime.strptime(text("td.spin-time"), "%I:%M %p").time()
        ts = datetime.combine(start.date(), t, tz)
        if ts < start - timedelta(hours=2):      # show crossed midnight
            ts += timedelta(days=1)
        spins.append({
            "id": int(row["data-key"]),
            "ts": ts.isoformat(),
            "artist": meta.get("a") or text("span.artist"),
            "song": meta.get("s") or text("span.song"),
            "release": meta.get("r") or text("span.release"),
            "label": text("span.label"),
            "released": text("span.released"),
            "isrc": meta.get("i") or text("span.isrc") or None,
            "local": 1 if row.select_one("span.local") else 0,
        })
    return header, spins


def is_automation(title, dj):
    """Spinitron files the overnight automation block under "Rotation"; split it out."""
    return ((title or "").strip().upper() == "AUTOMATION"
            or (title or "").startswith("WUOG 90.5FM")
            or (dj or "").strip() in ("Automation", "DJ Automatic DJ", "Automatic DJ"))


def store_feed(db, events):
    for e in events:
        category = (e.get("data") or {}).get("category")
        if is_automation(e["title"], e.get("text")):
            category = "Automation"
        if "/pl/" in e["url"]:
            db.execute(
                """INSERT INTO playlists (id, title, dj, category, start, end, url, duplicate)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, dj=excluded.dj,
                     category=excluded.category, start=excluded.start, end=excluded.end,
                     url=excluded.url, duplicate=excluded.duplicate""",
                (e["id"], e["title"], e.get("text"), category, e["start"], e["end"],
                 e["url"], int("playlist-duplicate" in e.get("className", ""))))
        else:
            db.execute(
                """INSERT OR REPLACE INTO slots (show_id, start, end, title, dj, category, url)
                   VALUES (?,?,?,?,?,?,?)""",
                (e["id"], e["start"], e["end"], e["title"], e.get("text"), category, e["url"]))


def collect_feed(db, api, since, until, refresh_after=None):
    """Fetch the calendar feed week by week. Weeks already fetched after they ended are skipped."""
    week = since - timedelta(days=since.weekday())
    while week < until:
        nxt = week + timedelta(days=7)
        row = db.execute("SELECT fetched_at FROM feed_weeks WHERE week_start=?", (week.isoformat(),)).fetchone()
        complete = row and row["fetched_at"] >= (nxt + timedelta(days=1)).isoformat()
        if not complete:
            events = api.calendar(week, nxt)
            store_feed(db, events)
            db.execute("INSERT OR REPLACE INTO feed_weeks VALUES (?,?)",
                       (week.isoformat(), datetime.now().isoformat()))
            db.commit()
            log.info("feed %s: %d events", week, len(events))
        week = nxt


def collect_spins(db, api, tz, since=None, settle_hours=3, limit=None):
    """Fetch spins for every playlist that ended at least `settle_hours` ago and hasn't been fetched."""
    cutoff = (datetime.now(tz) - timedelta(hours=settle_hours)).isoformat()
    q = "SELECT id, url, start FROM playlists WHERE fetched_at IS NULL AND end <= ?"
    args = [cutoff]
    if since:
        q += " AND start >= ?"
        args.append(since.isoformat())
    q += " ORDER BY start"
    if limit:
        q += f" LIMIT {int(limit)}"
    todo = db.execute(q, args).fetchall()
    log.info("%d playlists to fetch", len(todo))
    for i, pl in enumerate(todo, 1):
        try:
            header, spins = parse_playlist(api.playlist(pl["url"]), pl["start"], tz)
        except requests.HTTPError as e:
            log.warning("playlist %s: %s", pl["id"], e)
            if e.response is not None and e.response.status_code == 404:
                db.execute("UPDATE playlists SET fetched_at=?, n_spins=0 WHERE id=?",
                           (datetime.now().isoformat(), pl["id"]))
                db.commit()
            continue
        db.executemany(
            """INSERT OR REPLACE INTO spins (id, playlist_id, ts, artist, song, release, label, released, isrc, local)
               VALUES (:id, :pl, :ts, :artist, :song, :release, :label, :released, :isrc, :local)""",
            [{**s, "pl": pl["id"]} for s in spins])
        db.execute("UPDATE playlists SET fetched_at=?, n_spins=?, show_id=?, description=? WHERE id=?",
                   (datetime.now().isoformat(), len(spins), header.get("show_id"),
                    header.get("description"), pl["id"]))
        db.commit()
        if i % 25 == 0 or i == len(todo):
            log.info("spins: %d/%d playlists", i, len(todo))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/wuog.db")
    p.add_argument("--since", type=date.fromisoformat, required=True)
    p.add_argument("--until", type=date.fromisoformat, default=date.today() + timedelta(days=1))
    p.add_argument("--feed-only", action="store_true")
    p.add_argument("--spins-since", type=date.fromisoformat)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tz = ZoneInfo("America/New_York")
    db = connect(args.db)
    api = Spinitron("WUOG")
    collect_feed(db, api, args.since, args.until)
    if not args.feed_only:
        collect_spins(db, api, tz, since=args.spins_since or args.since)
