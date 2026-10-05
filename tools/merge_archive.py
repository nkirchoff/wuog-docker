"""One-off: merge the v2 "WUOG Light Side <sem>" / "WUOG Dark Side <sem>" Apple Music
playlists into a single "WUOG <sem> · Automation" playlist per semester.

The pairs were near-duplicates (day and night automation drew from the same pool),
and their tracks are already matched, so this copies tracks instead of re-searching.
The old playlists are left alone: the API can't delete them, so do that by hand.

usage (inside the container):  python tools/merge_archive.py [--dry-run]
"""
import re
import sys

sys.path.insert(0, ".")
import app  # noqa: E402

PAIR = re.compile(r"^WUOG (Light|Dark) Side (Spring|Fall) (\d{4})$")


def tracks(am, playlist_id):
    out, path = [], f"/v1/me/library/playlists/{playlist_id}/tracks?limit=100"
    while path:
        res = am._req("GET", path)
        for t in res.get("data", []):
            catalog = (t["attributes"].get("playParams") or {}).get("catalogId")
            out.append((catalog, "songs") if catalog else (t["id"], "library-songs"))
        path = res.get("next")
    return out


def main(dry_run):
    am = app.apple_music()
    if not am:
        sys.exit("Apple Music isn't configured")
    existing = {p["attributes"]["name"]: p["id"] for p in am.library_playlists()}
    pairs = {}
    for name, pid in existing.items():
        if m := PAIR.match(name):
            pairs.setdefault((int(m[3]), m[2]), {})[m[1]] = pid

    folder = None if dry_run else am.ensure_folder(app.CFG.get("folder") or "WUOG")
    for (year, season), sides in sorted(pairs.items(), key=lambda kv: (kv[0][0], kv[0][1] == "Fall")):
        name = f"WUOG {season} {year} · Automation"
        if name in existing:
            print(f"{name}: already exists, skipping")
            continue
        merged, seen = [], set()
        for side in ("Light", "Dark"):
            for item in tracks(am, sides[side]) if side in sides else []:
                if item[0] not in seen:
                    seen.add(item[0])
                    merged.append(item)
        print(f"{name}: {len(merged)} tracks from {', '.join(sorted(sides))}")
        if dry_run or not merged:
            continue
        pid = am.create_playlist(name, f"WUOG 90.5FM automation, {season} {year}. Merged from the old Light Side / Dark Side "
                                       "playlists, which drew from the same song pool.", folder_id=folder)
        for i in range(0, len(merged), 100):
            am._req("POST", f"/v1/me/library/playlists/{pid}/tracks",
                    json={"data": [{"id": t, "type": typ} for t, typ in merged[i:i + 100]]})


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
