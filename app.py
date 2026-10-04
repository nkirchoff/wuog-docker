"""WUOG semester playlists: Spinitron collector + Apple Music sync + dashboard (port 1785)."""
import base64
import csv
import io
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import schedule
import yaml
from flask import Flask, Response, jsonify, redirect, render_template, request

import collector
from applemusic import AppleMusic, AuthError, mint_developer_token
from semesters import Calendar
from sync import SCHEMA as SYNC_SCHEMA, run_sync, view_tracks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("wuog")
logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no per-request lines from the uptime monitor

CONFIG_PATH = os.environ.get("WUOG_CONFIG", "config.yaml")
AUTH_PATH = "data/applemusic.json"

with open(CONFIG_PATH) as f:
    CFG = yaml.safe_load(f)
TZ = ZoneInfo(CFG.get("timezone", "America/New_York"))
CAL = Calendar(CFG.get("semesters"), CFG.get("include_breaks", False))
LOCK = threading.Lock()          # one collect/sync at a time; SQLite + Spinitron politeness
STATUS = {"collect": {}, "sync": {}}

app = Flask(__name__)


def db():
    conn = collector.connect(CFG["database_path"])
    conn.executescript(SYNC_SCHEMA)
    return conn


def today():
    return datetime.now(TZ).date()


# --- Apple Music auth ---------------------------------------------------------
def load_auth():
    if not os.path.exists(AUTH_PATH):
        return None
    with open(AUTH_PATH) as f:
        return json.load(f)


def save_auth(auth):
    os.makedirs("data", exist_ok=True)
    with open(AUTH_PATH, "w") as f:
        json.dump(auth, f)
    os.chmod(AUTH_PATH, 0o600)


def token_expiry(jwt_token):
    """Expiry date of a JWT (read without verifying), or None."""
    try:
        payload = jwt_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return datetime.fromtimestamp(json.loads(base64.urlsafe_b64decode(payload))["exp"]).date()
    except Exception:
        return None


def developer_token(auth):
    if auth.get("key_id") and auth.get("team_id") and os.path.exists("data/musickit.p8"):
        return mint_developer_token(auth["team_id"], auth["key_id"], "data/musickit.p8")
    return auth.get("developer_token")


def apple_music():
    auth = load_auth()
    if not auth or not auth.get("user_token") or not developer_token(auth):
        return None
    return AppleMusic(developer_token(auth), auth["user_token"], CFG.get("storefront", "us"))


# --- jobs ---------------------------------------------------------------------
def _job(name, fn):
    if not LOCK.acquire(blocking=False):
        log.info("%s skipped: another job is running", name)
        return
    STATUS[name] = {"state": "running", "started": datetime.now().isoformat(timespec="seconds")}
    try:
        STATUS[name]["result"] = fn()
        STATUS[name]["state"] = "ok"
    except AuthError as e:
        STATUS[name].update(state="auth", error=str(e))
        log.error("%s: %s", name, e)
    except Exception as e:
        STATUS[name].update(state="error", error=str(e))
        log.exception("%s failed", name)
    finally:
        STATUS[name]["finished"] = datetime.now().isoformat(timespec="seconds")
        LOCK.release()


def collect(since=None):
    conn = db()
    api = collector.Spinitron(CFG["station"], CFG.get("request_interval_s", 10))
    if since is None:
        newest = conn.execute("SELECT max(start) FROM playlists").fetchone()[0]
        if newest:
            since = datetime.fromisoformat(newest).date() - timedelta(days=7)
        else:  # first run: start of the current (or most recent) semester
            open_ = CAL.open_semesters(today(), CFG.get("freeze_grace_days", 3))
            since = open_[0].start if open_ else today() - timedelta(days=7)
    collector.collect_feed(conn, api, since, today() + timedelta(days=1))
    # Spins: anything still unfetched in an open semester (finishes an interrupted backfill).
    open_ = CAL.open_semesters(today(), CFG.get("freeze_grace_days", 3))
    spins_since = min([s.start for s in open_] + [since - timedelta(days=7)])
    collector.collect_spins(conn, api, TZ, since=spins_since)
    n = conn.execute("SELECT count(*) FROM spins").fetchone()[0]
    return f"{n} spins in database"


def sync():
    am = apple_music()
    if not am:
        return "Apple Music not configured"
    return run_sync(db(), am, CAL, CFG, today())


def scheduler():
    schedule.every(CFG.get("collect_every_minutes", 60)).minutes.do(lambda: _job("collect", collect))
    schedule.every().day.at(CFG.get("sync_at", "05:00")).do(lambda: _job("sync", sync))
    _job("collect", collect)
    while True:
        schedule.run_pending()
        time.sleep(5)


# --- dashboard ----------------------------------------------------------------
def semester_rows(conn):
    t = today()
    grace = CFG.get("freeze_grace_days", 3)
    rows = []
    for sem in CAL.for_year(t.year - 1) + CAL.for_year(t.year) + CAL.for_year(t.year + 1):
        n = conn.execute("SELECT count(*) FROM spins WHERE substr(ts,1,10) BETWEEN ? AND ?",
                         (sem.start.isoformat(), sem.end.isoformat())).fetchone()[0]
        pls = conn.execute("""SELECT p.view, p.volume, p.name, p.frozen_at,
                                     (SELECT count(*) FROM am_items i WHERE i.playlist_id = p.playlist_id) AS n
                              FROM am_playlists p WHERE semester=? ORDER BY view, volume""", (sem.name,)).fetchall()
        if sem.start > t:
            state = "upcoming"
        elif any(p["frozen_at"] for p in pls):
            state = "frozen"
        elif t <= sem.freezes_on(grace):
            state = "open"
        else:
            state = "ended"
        if n or pls or state in ("open", "upcoming"):
            rows.append({"sem": sem, "spins": n, "playlists": pls, "state": state,
                         "freezes": sem.freezes_on(grace)})
    return rows


@app.route("/")
def index():
    conn = db()
    auth = load_auth() or {}
    expires = token_expiry(developer_token(auth) or "") if auth else None
    return render_template("index.html", semesters=semester_rows(conn), views=CFG["views"],
                           status=STATUS, am_ready=apple_music() is not None, auth=auth,
                           token_expires=expires, today=today())


@app.route("/api/status")
def api_status():
    return jsonify({"status": STATUS, "apple_music": apple_music() is not None})


@app.post("/collect")
def collect_now():
    threading.Thread(target=_job, args=("collect", collect), daemon=True).start()
    return redirect("/")


@app.post("/sync")
def sync_now():
    threading.Thread(target=_job, args=("sync", sync), daemon=True).start()
    return redirect("/")


@app.post("/applemusic")
def applemusic_auth():
    auth = load_auth() or {}
    bundle = request.form.get("bundle", "").strip()
    if bundle:   # {"developer_token": ..., "user_token": ...} copied from music.apple.com
        try:
            auth.update({k: v for k, v in json.loads(bundle).items() if k in ("developer_token", "user_token") and v})
            auth["user_token_saved"] = date.today().isoformat()
        except ValueError:
            STATUS["auth"] = "That wasn't valid JSON — copy it again from the console."
            return redirect("/")
    for field in ("developer_token", "user_token", "team_id", "key_id"):
        if request.form.get(field, "").strip():
            auth[field] = request.form[field].strip()
    if "p8" in request.files and request.files["p8"].filename:
        request.files["p8"].save("data/musickit.p8")
        os.chmod("data/musickit.p8", 0o600)
    save_auth(auth)
    am = apple_music()
    try:
        if am:
            am.check()
            STATUS["auth"] = "Apple Music connected"
    except AuthError as e:
        STATUS["auth"] = str(e)
    return redirect("/")


@app.route("/applemusic/authorize")
def applemusic_authorize():
    """MusicKit JS page that signs in to Apple Music and hands back a Music User Token."""
    auth = load_auth() or {}
    return render_template("authorize.html", developer_token=developer_token(auth) or "")


@app.post("/applemusic/user-token")
def applemusic_user_token():
    auth = load_auth() or {}
    auth["user_token"] = request.json["token"]
    auth["user_token_saved"] = date.today().isoformat()
    save_auth(auth)
    return jsonify(ok=True)


@app.route("/csv/<semester>/<view>")
def export_csv(semester, view):
    sem = next((s for y in range(today().year - 10, today().year + 2) for s in CAL.for_year(y) if s.name == semester), None)
    v = next((v for v in CFG["views"] if v["key"] == view), None)
    if not sem or not v:
        return "unknown semester or view", 404
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Artist", "Song", "ISRC"])
    for isrc, artist, song in view_tracks(db(), sem, v).values():
        w.writerow([artist, song, isrc or ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="WUOG {semester} {view}.csv"'})


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    threading.Thread(target=scheduler, daemon=True).start()
    from waitress import serve
    log.info("dashboard on :1785")
    serve(app, host="0.0.0.0", port=1785)
