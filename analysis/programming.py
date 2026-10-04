"""Programming-by-hour analysis for one semester. Prints tables and writes a JSON summary.

usage: python analysis/programming.py data/wuog.db 2026-08-17 2026-10-04 [out.json]
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from sync import NOT_MUSIC, track_key  # noqa: E402

db_path, start, end = sys.argv[1:4]
out_path = sys.argv[4] if len(sys.argv) > 4 else None
db = sqlite3.connect(db_path)

CATS = ["Rotation", "Specialty Show", "Talk", "Sport", "Live Music", "News", "unset", "Automation"]
DAYS = "Mon Tue Wed Thu Fri Sat Sun".split()

pls = db.execute("""SELECT id, title, dj, coalesce(category,'unset'), start, end, n_spins, duplicate, description
                    FROM playlists WHERE start >= ? AND start < ? AND fetched_at IS NOT NULL""",
                 (start, end + "T99")).fetchall()
pl_by_id = {p[0]: p for p in pls}
spins = [s for s in db.execute("""SELECT playlist_id, ts, artist, song, isrc, local, released, label
                                  FROM spins WHERE substr(ts,1,10) BETWEEN ? AND ?""", (start, end))
         if s[0] in pl_by_id and s[2] and s[3] and not NOT_MUSIC.match(s[2])]

# de-duplicate "playlist-duplicate" pairs: same airtime, same song
seen, uniq = set(), []
for s in spins:
    k = (s[1], s[2].lower(), s[3].lower())
    if k not in seen:
        seen.add(k)
        uniq.append(s)
spins = uniq
cat_of = lambda s: pl_by_id[s[0]][3]

print(f"{len(pls)} playlists, {len(spins)} music spins, {start} → {end}\n")

# 1. hours on air and songs per hour by category
hours = Counter()
for p in pls:
    if p[7]:
        continue
    hours[p[3]] += (datetime.fromisoformat(p[5]) - datetime.fromisoformat(p[4])).total_seconds() / 3600
per_cat = Counter(cat_of(s) for s in spins)
tracks_by_cat = defaultdict(set)
artists_by_cat = defaultdict(set)
for s in spins:
    tracks_by_cat[cat_of(s)].add(track_key(s[4], s[2], s[3]))
    artists_by_cat[cat_of(s)].add(s[2].lower())
print(f"{'category':15} {'hours':>6} {'spins':>6} {'/hr':>5} {'tracks':>6} {'artists':>7} {'repeat':>6} {'isrc%':>5} {'local%':>6} {'new%':>5}")
summary = {}
yr = int(start[:4])
for c in CATS:
    ss = [s for s in spins if cat_of(s) == c]
    if not ss:
        continue
    isrc = sum(1 for s in ss if s[4]) / len(ss)
    local = sum(s[5] for s in ss) / len(ss)
    years = [int(s[6]) for s in ss if s[6] and s[6].isdigit()]
    new = sum(1 for y in years if y >= yr - 1) / max(1, len(years))
    rep = len(ss) / len(tracks_by_cat[c])
    summary[c] = dict(hours=round(hours[c], 1), spins=len(ss), per_hour=round(len(ss) / max(1, hours[c]), 1),
                      tracks=len(tracks_by_cat[c]), artists=len(artists_by_cat[c]), repeat=round(rep, 2),
                      isrc=round(isrc, 3), local=round(local, 3), new=round(new, 3),
                      median_year=sorted(years)[len(years) // 2] if years else None)
    print(f"{c:15} {hours[c]:6.0f} {len(ss):6} {summary[c]['per_hour']:5} {len(tracks_by_cat[c]):6} "
          f"{len(artists_by_cat[c]):7} {rep:6.2f} {100*isrc:5.0f} {100*local:6.1f} {100*new:5.0f}")

# 2. overlap between categories (share of A's tracks also played in B)
print("\ntrack overlap (row's tracks that also aired in column)")
main = [c for c in ["Rotation", "Specialty Show", "Talk", "Sport", "Automation"] if c in tracks_by_cat]
print(" " * 15 + "".join(f"{c[:10]:>11}" for c in main))
overlap = {}
for a in main:
    row = []
    for b in main:
        v = len(tracks_by_cat[a] & tracks_by_cat[b]) / len(tracks_by_cat[a])
        overlap.setdefault(a, {})[b] = round(v, 3)
        row.append(f"{100*v:10.0f}%")
    print(f"{a:15}" + "".join(row))

# 3. heavy rotation: tracks played by >= 3 different shows
shows_per_track = defaultdict(set)
name_of = {}
for s in spins:
    if cat_of(s) == "Automation":   # every automation hour is its own "show"
        continue
    k = track_key(s[4], s[2], s[3])
    shows_per_track[k].add(pl_by_id[s[0]][1])
    name_of[k] = f"{s[2]} – {s[3]}"
heavy = sorted(((len(v), name_of[k]) for k, v in shows_per_track.items() if len(v) >= 3), reverse=True)
print(f"\n{len(heavy)} tracks aired on 3+ different shows; top 15:")
for n, name in heavy[:15]:
    print(f"  {n:2} shows  {name}")

# 4. hour-of-week grid: spins per category, plus songs/hour
grid = defaultdict(Counter)
for s in spins:
    t = datetime.fromisoformat(s[1])
    grid[(t.weekday(), t.hour)][cat_of(s)] += 1
weeks = max(1, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days / 7)
print("\nspins/hour (avg per week-hour) and dominant category")
print("hr  " + "".join(f"{d:>8}" for d in DAYS))
abbr = {"Rotation": "R", "Specialty Show": "S", "Talk": "T", "Sport": "P", "Live Music": "L", "News": "N", "unset": "u", "Automation": "A"}
grid_out = []
for h in range(24):
    cells = []
    for d in range(7):
        c = grid[(d, h)]
        n = sum(c.values())
        if n:
            top = c.most_common(1)[0][0]
            cells.append(f"{abbr[top]}{n/weeks:6.1f} ")
            grid_out.append({"day": d, "hour": h, "spins_per_week": round(n / weeks, 1), "top": top,
                             "mix": {k: v for k, v in c.items()}})
        else:
            cells.append("      - ")
    print(f"{h:02d}  " + "".join(cells))

# 5. dayparts
parts = {"Morning 8–12": range(8, 12), "Afternoon 12–17": range(12, 17), "Evening 17–24": range(17, 24), "Overnight 0–8": range(0, 8)}
print("\ndaypart profile")
dayparts = {}
for name, hrs in parts.items():
    ss = [s for s in spins if datetime.fromisoformat(s[1]).hour in hrs]
    if not ss:
        continue
    mix = Counter(cat_of(s) for s in ss)
    years = sorted(int(s[6]) for s in ss if s[6] and s[6].isdigit())
    dayparts[name] = {"spins": len(ss), "mix": dict(mix), "median_year": years[len(years) // 2] if years else None,
                      "local": round(sum(s[5] for s in ss) / len(ss), 3),
                      "tracks": len({track_key(s[4], s[2], s[3]) for s in ss})}
    print(f"  {name:16} {len(ss):6} spins  {dayparts[name]['tracks']:5} tracks  median yr {dayparts[name]['median_year']}  "
          f"local {100*dayparts[name]['local']:.1f}%  " + ", ".join(f"{k} {100*v/len(ss):.0f}%" for k, v in mix.most_common(4)))

# 6. specialty shows
print("\nspecialty shows")
shows = defaultdict(lambda: {"spins": 0, "tracks": set(), "slots": set(), "desc": None, "dj": None})
for s in spins:
    p = pl_by_id[s[0]]
    if p[3] != "Specialty Show":
        continue
    sh = shows[p[1]]
    sh["spins"] += 1
    sh["tracks"].add(track_key(s[4], s[2], s[3]))
    t = datetime.fromisoformat(p[4])
    sh["slots"].add(f"{DAYS[t.weekday()]} {t.strftime('%-I%p').lower()}")
    sh["desc"] = sh["desc"] or p[8]
    sh["dj"] = p[2]
show_out = []
for title, sh in sorted(shows.items(), key=lambda kv: -kv[1]["spins"]):
    show_out.append({"title": title, "dj": sh["dj"], "spins": sh["spins"], "tracks": len(sh["tracks"]),
                     "slots": sorted(sh["slots"]), "description": (sh["desc"] or "")[:200]})
    print(f"  {title[:28]:28} {', '.join(sorted(sh['slots']))[:22]:22} {sh['spins']:4} spins  {(sh['desc'] or '')[:70]}")

if out_path:
    with open(out_path, "w") as f:
        json.dump({"range": [start, end], "playlists": len(pls), "spins": len(spins), "categories": summary,
                   "overlap": overlap, "heavy": [{"shows": n, "track": t} for n, t in heavy[:40]],
                   "heavy_count": len(heavy), "grid": grid_out, "dayparts": dayparts, "shows": show_out}, f, indent=1)
