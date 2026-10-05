import sqlite3, collections
from datetime import datetime, timedelta
db = sqlite3.connect("data/wuog.db")
S, E = "2026-08-17", "2026-10-04"
rows = db.execute("select 'pl', title, dj, category, start, end, duplicate from playlists where start>=? and start<?", (S,E)).fetchall()
rows += db.execute("select 'slot', title, dj, category, start, end, 0 from slots where start>=? and start<?", (S,E)).fetchall()
# per hour-of-week, minutes per category (logged playlists), and slots with no playlist
cat_min = collections.defaultdict(collections.Counter)
logged = set()
for kind, title, dj, cat, st, en, dup in rows:
    st, en = datetime.fromisoformat(st), datetime.fromisoformat(en)
    if kind == 'pl': logged.add((title, st))
weeks = 7
grid = collections.defaultdict(collections.Counter)  # (wd,hour) -> cat -> count of weeks
for kind, title, dj, cat, st, en, dup in rows:
    st, en = datetime.fromisoformat(st), datetime.fromisoformat(en)
    if kind == 'slot' and (title, st) in logged: continue
    if kind == 'pl' and dup: continue
    c = cat or 'unset'
    if kind == 'slot': c = 'AUTOMATION' if title.upper()=='AUTOMATION' else f'(no log) {c}'
    t = st
    while t < en:
        grid[(t.weekday(), t.hour)][c] += 1
        t += timedelta(minutes=30)
cats = collections.Counter()
for k,v in grid.items(): cats.update(v)
print("half-hours by category over 7 weeks:", cats.most_common())
abbr = {'Rotation':'R','Specialty Show':'S','Talk':'T','Sport':'P','News':'N','Live Music':'L','unset':'u','AUTOMATION':'·'}
print("\nDominant programming, hour x weekday (R=Rotation S=Specialty T=Talk P=Sport N=News L=Live u=unset ·=automation x=scheduled but never logged)")
print("hr  " + "  ".join("Mon Tue Wed Thu Fri Sat Sun".split()))
for h in range(24):
    line=[]
    for wd in range(7):
        c = grid[(wd,h)]
        if not c: line.append(' -  '); continue
        top, n = c.most_common(1)[0]
        a = abbr.get(top, 'x' if top.startswith('(no log)') else '?')
        line.append(f"{a}{min(99,round(100*n/sum(c.values()))):>3}")
    print(f"{h:02d}  " + " ".join(line))
