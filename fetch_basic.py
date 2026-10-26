"""Current-season Premier League basics from football-data.org's free tier -> site/live.json

Free tier gives: league table, results (slightly delayed) and, where available, top scorers.
It does not include lineups, player stats or shots, so no xG for the current season.

Usage:  FOOTBALL_DATA_TOKEN=your_free_key python pipeline/fetch_basic.py site/live.json
Get a free key at https://www.football-data.org/client/register
"""
import os, sys, json, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "site/live.json")
TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")
BASE = "https://api.football-data.org/v4/competitions/PL"
FIXTURE_DIR = os.environ.get("FD_FIXTURES")  # for testing: read saved responses instead of calling the API


def get(path):
    if FIXTURE_DIR:
        return json.load(open(Path(FIXTURE_DIR) / f"{path.strip('/').split('?')[0] or 'root'}.json"))
    req = urllib.request.Request(BASE + path, headers={"X-Auth-Token": TOKEN})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:      # free tier: 10 requests per minute
                time.sleep(65)
                continue
            raise


def main():
    if not TOKEN and not FIXTURE_DIR:
        sys.exit("Set FOOTBALL_DATA_TOKEN to your free football-data.org key.")

    st = get("/standings")
    start = st["season"]["startDate"][:4]
    label = f"{start}/{str(int(start) + 1)[-2:]}"
    total = next(s for s in st["standings"] if s["type"] == "TOTAL")["table"]
    table = [{
        "pos": t["position"], "team": t["team"]["name"], "short": t["team"].get("shortName") or t["team"]["name"],
        "p": t["playedGames"], "w": t["won"], "d": t["draw"], "l": t["lost"],
        "gf": t["goalsFor"], "ga": t["goalsAgainst"], "pts": t["points"],
        "form": (t.get("form") or "").replace(",", ""),
    } for t in total]

    ms = get("/matches?status=FINISHED")["matches"]
    matches = [{
        "id": m["id"], "date": m["utcDate"][:10], "wk": m.get("matchday"),
        "h": m["homeTeam"]["name"], "a": m["awayTeam"]["name"],
        "hs": m["homeTeam"].get("shortName") or m["homeTeam"]["name"],
        "as": m["awayTeam"].get("shortName") or m["awayTeam"]["name"],
        "hg": m["score"]["fullTime"]["home"], "ag": m["score"]["fullTime"]["away"],
    } for m in ms if m["score"]["fullTime"]["home"] is not None]
    matches.sort(key=lambda m: (m["date"], m["id"]))

    # form isn't always filled on the free tier; rebuild last five from results if missing
    if not any(t["form"] for t in table):
        res = {}
        for m in matches:
            hr = "W" if m["hg"] > m["ag"] else "D" if m["hg"] == m["ag"] else "L"
            ar = {"W": "L", "L": "W", "D": "D"}[hr]
            res.setdefault(m["h"], []).append(hr); res.setdefault(m["a"], []).append(ar)
        for t in table:
            t["form"] = "".join(res.get(t["team"], [])[-5:])

    scorers = []
    try:
        for s in get("/scorers?limit=40")["scorers"]:
            scorers.append({"name": s["player"]["name"], "team": s["team"]["name"],
                            "short": s["team"].get("shortName") or s["team"]["name"],
                            "mp": s.get("playedMatches"), "g": s.get("goals") or 0,
                            "a": s.get("assists") or 0, "pen": s.get("penalties") or 0})
    except Exception as e:  # not every plan includes scorers; the site hides that table if empty
        print("scorers unavailable:", e)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"season": label, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "source": "football-data.org", "table": table, "matches": matches, "scorers": scorers},
              open(OUT, "w"), separators=(",", ":"))
    print(f"{label}: {len(table)} teams, {len(matches)} results, {len(scorers)} scorers -> {OUT}")


if __name__ == "__main__":
    main()
