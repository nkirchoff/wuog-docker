import sqlite3, re, collections
from datetime import datetime
db = sqlite3.connect("data/wuog_history.db")
rows = db.execute("""select p.date_str, p.time_str, p.show_title, lower(trim(s.artist)), lower(trim(s.song))
                     from songs s join playlists p on p.url=s.playlist_url""").fetchall()
def sem(dt):
    if (dt.month, dt.day) >= (8, 15) and dt.month <= 12: return f"Fall {dt.year}"
    if dt.month <= 5 and not (dt.month == 5 and dt.day > 10) and (dt.month, dt.day) >= (1, 8): return f"Spring {dt.year}"
    return f"Break {dt.year}"
hour_pl = collections.defaultdict(set)   # semester -> set((date,hour))
pool = collections.defaultdict(lambda: {"day": set(), "night": set()})
spins_per_pl = collections.defaultdict(list)
perpl = collections.Counter()
for d, t, title, a, s in rows:
    dt = datetime.strptime(re.sub(r"(\d+)(st|nd|rd|th)", r"\1", d) + " " + t, "%b %d %Y %I:%M %p")
    k = sem(dt)
    hour_pl[k].add((dt.date(), dt.hour))
    pool[k]["day" if 7 <= dt.hour < 22 else "night"].add((a, s))
    perpl[(dt.date(), dt.hour)] += 1
print(f"{'semester':12} {'day':>6} {'night':>6} {'both':>6} {'jacc':>5}  automation-hours/week by hour (0..23)")
for k in sorted(pool, key=lambda k: (k.split()[1], {'Spring':0,'Break':1,'Fall':2}[k.split()[0]])):
    if k.startswith("Break"): continue
    dset, nset = pool[k]["day"], pool[k]["night"]
    j = len(dset & nset) / max(1, len(dset | nset))
    days = len({d for d, h in hour_pl[k]})
    byh = collections.Counter(h for d, h in hour_pl[k])
    prof = "".join(" .:-=+*#%@"[min(9, int(9 * byh[h] / max(1, days)))] for h in range(24))
    print(f"{k:12} {len(dset):6} {len(nset):6} {len(dset&nset):6} {j:5.2f}  |{prof}|  days={days}")
print("\nmedian songs per automation hour:", sorted(perpl.values())[len(perpl)//2])
