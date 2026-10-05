"""Minimal Apple Music API client: catalog lookup + library playlist create/append.

Auth needs two tokens:
  * a developer token (JWT). Either paste one, or give a MusicKit key
    (team id, key id, .p8 file) and it is minted here.
  * a Music User Token for your account (from MusicKit JS authorize()).

The Apple Music API can create library playlists and add tracks to them, but it
cannot rename, reorder or remove tracks, so the sync is strictly append-only.
"""
import logging
import re
import time
import unicodedata
from difflib import SequenceMatcher

import requests

API = "https://api.music.apple.com"
log = logging.getLogger("wuog.applemusic")


class AuthError(Exception):
    pass


def mint_developer_token(team_id, key_id, p8_path, days=180):
    import jwt  # PyJWT, only needed for this path

    now = int(time.time())
    with open(p8_path) as f:
        key = f.read()
    return jwt.encode({"iss": team_id, "iat": now, "exp": now + days * 86400},
                      key, algorithm="ES256", headers={"kid": key_id})


class AppleMusic:
    SEARCH_INTERVAL = 1.0   # Apple rate-limits bursts of catalog searches

    def __init__(self, developer_token, user_token, storefront="us"):
        self.storefront = storefront
        self._last_search = 0.0
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {developer_token}",
            "Music-User-Token": user_token,
            "Origin": "https://music.apple.com",
        })

    def _req(self, method, path, **kw):
        status = None
        for attempt in range(6):
            try:
                r = self.s.request(method, API + path, timeout=30, **kw)
            except requests.RequestException as e:
                status = str(e)
                time.sleep(10 * (attempt + 1))
                continue
            status = r.status_code
            if r.status_code == 429 or r.status_code >= 500:
                wait = int(r.headers.get("Retry-After") or 0) or min(120, 10 * 2 ** attempt)
                log.warning("Apple Music %s %s -> %s; waiting %ss", method, path, r.status_code, wait)
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                raise AuthError(f"{r.status_code} from Apple Music — token expired or invalid")
            r.raise_for_status()
            return r.json() if r.content else {}
        raise RuntimeError(f"Apple Music {method} {path} kept failing ({status})")

    def check(self):
        self._req("GET", "/v1/me/storefront")

    # --- catalog -------------------------------------------------------
    def songs_by_isrc(self, isrcs):
        """{isrc: catalog song id} for up to 25 ISRCs."""
        out = {}
        data = self._req("GET", f"/v1/catalog/{self.storefront}/songs",
                         params={"filter[isrc]": ",".join(isrcs)}).get("data", [])
        for song in data:
            isrc = song["attributes"].get("isrc")
            if isrc and isrc not in out:
                out[isrc] = song["id"]
        return out

    def search_song(self, artist, title):
        """Best catalog match for artist/title, or None if nothing is a confident match."""
        term = f"{artist} {_strip(title)}"[:200]
        wait = self._last_search + self.SEARCH_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_search = time.monotonic()
        res = self._req("GET", f"/v1/catalog/{self.storefront}/search",
                        params={"term": term, "types": "songs", "limit": 10})
        best, best_score = None, 0.0
        for song in res.get("results", {}).get("songs", {}).get("data", []):
            a = song["attributes"]
            score = _similar(title, a["name"]) * 0.6 + _artist_match(artist, a["artistName"]) * 0.4
            if score > best_score:
                best, best_score = song["id"], score
        return best if best_score >= 0.8 else None

    # --- library -------------------------------------------------------
    def library_playlists(self):
        out, path = [], "/v1/me/library/playlists?limit=100"
        while path:
            res = self._req("GET", path)
            out += res.get("data", [])
            path = res.get("next")
        return out

    def ensure_folder(self, name):
        """Id of the top-level library folder called `name`, creating it if needed."""
        res = self._req("GET", "/v1/me/library/playlist-folders/p.playlistsroot/children?limit=100")
        while True:
            for item in res.get("data", []):
                if item["type"] == "library-playlist-folders" and item["attributes"].get("name") == name:
                    return item["id"]
            if not res.get("next"):
                break
            res = self._req("GET", res["next"])
        return self._req("POST", "/v1/me/library/playlist-folders",
                         json={"attributes": {"name": name}})["data"][0]["id"]

    def create_playlist(self, name, description, song_ids=(), folder_id=None):
        body = {"attributes": {"name": name, "description": description}}
        rel = {}
        if song_ids:
            rel["tracks"] = {"data": [{"id": i, "type": "songs"} for i in song_ids]}
        if folder_id:
            rel["parent"] = {"data": [{"id": folder_id, "type": "library-playlist-folders"}]}
        if rel:
            body["relationships"] = rel
        return self._req("POST", "/v1/me/library/playlists", json=body)["data"][0]["id"]

    def add_tracks(self, playlist_id, song_ids):
        for i in range(0, len(song_ids), 100):
            chunk = song_ids[i:i + 100]
            self._req("POST", f"/v1/me/library/playlists/{playlist_id}/tracks",
                      json={"data": [{"id": s, "type": "songs"} for s in chunk]})
            time.sleep(0.5)


# --- fuzzy matching helpers -------------------------------------------------
def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(feat|ft|featuring|with)\b.*", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _strip(title):
    # "Song (2019 Remaster)" / "Song - Radio Edit" -> "Song"
    return re.sub(r"\s*[\(\[].*?[\)\]]|\s+-\s+.*$", "", title or "").strip() or title


def _similar(a, b):
    a, b = _norm(_strip(a)), _norm(_strip(b))
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def _artist_match(spun, catalog):
    spun_n, cat_n = _norm(spun), _norm(catalog)
    if spun_n and (spun_n in cat_n or cat_n in spun_n):
        return 1.0
    return SequenceMatcher(None, spun_n, cat_n).ratio()
