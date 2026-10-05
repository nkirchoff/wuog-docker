"""Semester playlist sync: spins -> per-view track lists -> Apple Music library playlists.

Each open semester gets one playlist per configured view. Playlists only ever
grow (new tracks appended in first-aired order). Once a semester passes its end
date plus the grace period it gets one last sync and is frozen for good.
"""
import logging
import re
import sqlite3
from collections import OrderedDict
from datetime import date, datetime

from applemusic import AppleMusic, SearchLimited, _norm

log = logging.getLogger("wuog.sync")

SCHEMA = """
CREATE TABLE IF NOT EXISTS am_matches (key TEXT PRIMARY KEY, song_id TEXT, method TEXT, checked_at TEXT);
CREATE TABLE IF NOT EXISTS am_playlists (
    view TEXT, semester TEXT, volume INTEGER, playlist_id TEXT, name TEXT,
    created_at TEXT, frozen_at TEXT, PRIMARY KEY (view, semester, volume));
CREATE TABLE IF NOT EXISTS am_items (playlist_id TEXT, song_id TEXT, added_at TEXT, PRIMARY KEY (playlist_id, song_id));
"""

# Spinitron rows that aren't songs (station IDs, PSAs, DJ breaks).
NOT_MUSIC = re.compile(r"^(wuog|station id|psa|legal id|dj break|talk|weather|underwriting)\b", re.I)


def track_key(isrc, artist, song):
    return isrc.upper() if isrc else f"{_norm(artist)}|{_norm(song)}"


def view_tracks(db, semester, view):
    """Ordered {key: (isrc, artist, song)} for one view of one semester, by first airing."""
    q = """SELECT s.ts, s.isrc, s.artist, s.song, s.local, p.category, p.title
           FROM spins s JOIN playlists p ON p.id = s.playlist_id
           WHERE substr(s.ts, 1, 10) BETWEEN ? AND ? ORDER BY s.ts"""
    cats = set(view.get("categories") or [])
    hours = set(view.get("hours") or [])
    weekdays = set(view.get("weekdays") or [])
    shows = {t.lower() for t in view.get("shows") or []}
    counts, shows_of, first = {}, {}, OrderedDict()
    for row in db.execute(q, (semester.start.isoformat(), semester.end.isoformat())):
        ts, isrc, artist, song, local, category, title = row
        if not artist or not song or NOT_MUSIC.match(artist):
            continue
        if cats and category not in cats:
            continue
        if shows and (title or "").lower() not in shows:
            continue
        if view.get("local_only") and not local:
            continue
        dt = datetime.fromisoformat(ts)
        if hours and dt.hour not in hours:
            continue
        if weekdays and dt.weekday() not in weekdays:
            continue
        k = track_key(isrc, artist, song)
        counts[k] = counts.get(k, 0) + 1
        if category != "Automation":   # every automation hour is its own playlist
            shows_of.setdefault(k, set()).add((title or "").lower())
        first.setdefault(k, (isrc, artist, song))
    min_spins, min_shows = view.get("min_spins", 1), view.get("min_shows", 0)
    return OrderedDict((k, v) for k, v in first.items()
                       if counts[k] >= min_spins and len(shows_of.get(k, ())) >= min_shows)


def match_tracks(db, am, tracks, retry_days=30):
    """Resolve track keys to Apple Music catalog ids, using and filling the match cache."""
    now = datetime.now()
    cached = {}
    for k in tracks:
        row = db.execute("SELECT song_id, checked_at FROM am_matches WHERE key=?", (k,)).fetchone()
        if row and (row[0] or (now - datetime.fromisoformat(row[1])).days < retry_days):
            cached[k] = row[0]
    todo = [k for k in tracks if k not in cached]

    isrc_keys = [k for k in todo if tracks[k][0]]
    for i in range(0, len(isrc_keys), 25):
        batch = isrc_keys[i:i + 25]
        found = am.songs_by_isrc([tracks[k][0] for k in batch])
        for k in batch:
            if tracks[k][0] in found:
                cached[k] = found[tracks[k][0]]
                db.execute("INSERT OR REPLACE INTO am_matches VALUES (?,?,?,?)", (k, cached[k], "isrc", now.isoformat()))
        db.commit()

    failures = 0
    for k in [k for k in todo if k not in cached]:
        if getattr(am, "search_limited", False):
            break
        _, artist, song = tracks[k]
        try:
            cached[k] = am.search_song(artist, song)
        except SearchLimited:
            log.info("catalog search throttled; %d songs left for the next run",
                     sum(1 for x in todo if x not in cached))
            am.search_limited = True
            break
        except RuntimeError as e:
            # Leave it uncached so the next run retries; stop early if Apple keeps refusing.
            log.warning("search failed for %s – %s: %s", artist, song, e)
            failures += 1
            if failures >= 3:
                log.warning("too many search failures; finishing this run with what matched")
                break
            continue
        failures = 0
        db.execute("INSERT OR REPLACE INTO am_matches VALUES (?,?,?,?)",
                   (k, cached[k], "search" if cached[k] else "none", now.isoformat()))
        db.commit()
    return {k: v for k, v in cached.items()}


def sync_semester(db, am, semester, views, cfg, frozen_after=False):
    db.executescript(SCHEMA)
    max_tracks = cfg.get("max_tracks_per_playlist") or 10**9
    summary = {}
    for view in views:
        tracks = view_tracks(db, semester, view)
        ids = match_tracks(db, am, tracks)
        wanted = list(OrderedDict.fromkeys(i for k, i in ids.items() if i))

        vols = db.execute("SELECT volume, playlist_id FROM am_playlists WHERE view=? AND semester=? ORDER BY volume",
                          (view["key"], semester.name)).fetchall()
        added = {r[0] for v in vols for r in db.execute("SELECT song_id FROM am_items WHERE playlist_id=?", (v[1],))}
        new = [i for i in wanted if i not in added]

        while new:
            if vols:
                vol, pid = vols[-1]
                room = max_tracks - db.execute("SELECT count(*) FROM am_items WHERE playlist_id=?", (pid,)).fetchone()[0]
            else:
                vol, pid, room = 0, None, 0
            if room <= 0 or pid is None:
                vol += 1
                fmt = {"semester": semester.name,
                       "start": semester.start.strftime("%b %-d"), "end": semester.end.strftime("%b %-d, %Y")}
                name = view["name"].format(**fmt) + (f" (Vol. {vol})" if vol > 1 else "")
                folder = None
                if cfg.get("folder"):
                    try:
                        folder = am.ensure_folder(cfg["folder"])
                    except Exception as e:   # a folder is nice to have; never block the playlist on it
                        log.warning("couldn't use folder %r: %s", cfg["folder"], e)
                pid = am.create_playlist(name, view.get("description", "").format(**fmt), folder_id=folder)
                db.execute("INSERT INTO am_playlists VALUES (?,?,?,?,?,?,NULL)",
                           (view["key"], semester.name, vol, pid, name, datetime.now().isoformat()))
                vols.append((vol, pid))
                room = max_tracks
                log.info("created %s", name)
            chunk, new = new[:room], new[room:]
            am.add_tracks(pid, chunk)
            db.executemany("INSERT OR IGNORE INTO am_items VALUES (?,?,?)",
                           [(pid, s, datetime.now().isoformat()) for s in chunk])
            db.commit()
            log.info("%s / %s: +%d tracks", semester.name, view["key"], len(chunk))

        summary[view["key"]] = {"tracks": len(tracks), "matched": len(wanted),
                                "added_now": len(wanted) - len([i for i in wanted if i in added])}
    if frozen_after:
        db.execute("UPDATE am_playlists SET frozen_at=? WHERE semester=? AND frozen_at IS NULL",
                   (datetime.now().isoformat(), semester.name))
        db.commit()
        log.info("%s frozen", semester.name)
    return summary


def run_sync(db, am, calendar, cfg, today=None):
    db.executescript(SCHEMA)
    today = today or date.today()
    grace = cfg.get("freeze_grace_days", 3)
    # Semesters that started before this are left alone (they're already archived on Apple Music).
    first = date.fromisoformat(str(cfg.get("sync_from", "2000-01-01")))
    results = {}
    for sem in calendar.for_year(today.year - 1) + calendar.for_year(today.year):
        if sem.start > today:
            continue
        if sem.start < first:
            continue
        if db.execute("SELECT 1 FROM am_playlists WHERE semester=? AND frozen_at IS NOT NULL", (sem.name,)).fetchone():
            continue
        past_due = today > sem.freezes_on(grace)
        if past_due and not db.execute("SELECT 1 FROM am_playlists WHERE semester=?", (sem.name,)).fetchone():
            continue  # never synced and long over: leave it alone
        views = [v for v in cfg["views"] if v.get("breaks")] if sem.is_break else cfg["views"]
        results[sem.name] = sync_semester(db, am, sem, views, cfg, frozen_after=past_due)
    return results
