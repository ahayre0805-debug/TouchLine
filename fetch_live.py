"""Fetch the current season from a licensed data provider and write the same tidy tables
that extract.py produces from StatsBomb data:

  data/matches.csv, data/players.csv, data/player_matches.csv, data/shots.csv

Everything downstream (score_xg.py, build_stats.py, the website) works unchanged.

Before you pay for a plan, confirm in writing with the provider that:
  1. you may display the data publicly on a free website, and
  2. you may publish stats you derive from it (your own xG).
Shot-level x/y locations are required for xG. Many cheap plans only have shot counts;
check that shot coordinates are included before choosing a provider.

Usage:  DATA_API_KEY=... python pipeline/fetch_live.py data
"""
import os, sys, json, math, time
from pathlib import Path
import urllib.request
import pandas as pd

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
OUT.mkdir(exist_ok=True)
API_KEY = os.environ.get("DATA_API_KEY")
BASE_URL = os.environ.get("DATA_API_BASE", "")          # your provider's base URL
SEASON = os.environ.get("SEASON", "2026")
CACHE = Path("cache"); CACHE.mkdir(exist_ok=True)

GOAL_X, GOAL_Y, POST_L, POST_R = 120.0, 40.0, 36.0, 44.0


def get(path, params=None):
    """GET with a disk cache: finished matches never change, so each is downloaded once."""
    q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    key = CACHE / (path.strip("/").replace("/", "_") + ("_" + q.replace("&", "_").replace("=", "-") if q else "") + ".json")
    if key.exists():
        return json.loads(key.read_text())
    req = urllib.request.Request(f"{BASE_URL}{path}?{q}", headers={"Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    key.write_text(json.dumps(data))
    time.sleep(0.5)  # stay well inside rate limits
    return data


def to_statsbomb_coords(x_pct, y_pct):
    """Most providers give 0-100 coordinates with the attacked goal at x=100.
    Convert to the 120x80 pitch the xG model was trained on."""
    return x_pct * 1.2, y_pct * 0.8


def geometry(x, y):
    dist = math.hypot(GOAL_X - x, GOAL_Y - y)
    angle = abs(math.atan2(POST_R - y, GOAL_X - x) - math.atan2(POST_L - y, GOAL_X - x))
    return dist, angle


def main():
    if not API_KEY or not BASE_URL:
        sys.exit("Set DATA_API_KEY and DATA_API_BASE (your provider's API URL) first.")

    # ---- Adapt the endpoint names and field paths below to your provider's docs. ----
    fixtures = get("/fixtures", {"league": "premier-league", "season": SEASON, "status": "finished"})
    matches, players, pms, shots = [], {}, [], []
    for f in fixtures["data"]:
        mid = f["id"]
        matches.append(dict(match_id=mid, date=f["date"][:10], week=int("".join(ch for ch in str(f.get("round", "")) if ch.isdigit()) or 0),
                            home=f["home"]["name"], away=f["away"]["name"],
                            hg=f["score"]["home"], ag=f["score"]["away"]))

        for p in get(f"/fixtures/{mid}/players")["data"]:
            players[p["id"]] = p["name"]
            s = p.get("stats", {})
            pms.append(dict(match_id=mid, player_id=p["id"], team=p["team"], position=p.get("position", "Midfield"),
                            start=int(p.get("starting", False)), minutes=s.get("minutes", 0),
                            passes=s.get("passes", 0), passes_cmp=s.get("passes_completed", 0),
                            prog_passes=s.get("progressive_passes", 0), prog_carries=s.get("progressive_carries", 0),
                            key_passes=s.get("key_passes", 0), assists=s.get("assists", 0),
                            dribbles=s.get("dribbles_attempted", 0), dribbles_won=s.get("dribbles_completed", 0),
                            tackles_won=s.get("tackles_won", 0), interceptions=s.get("interceptions", 0),
                            recoveries=s.get("recoveries", 0)))

        for sh in get(f"/fixtures/{mid}/shots")["data"]:
            x, y = to_statsbomb_coords(sh["x"], sh["y"])
            dist, angle = geometry(x, y)
            outcome = {"goal": "Goal", "saved": "Saved", "blocked": "Blocked"}.get(sh.get("result"), "Off T")
            shots.append(dict(
                match_id=mid, shot_id=sh["id"], minute=sh["minute"], team=sh["team"], player_id=sh["player_id"],
                x=x, y=y, dist=dist, angle=angle,
                body="head" if sh.get("body_part") == "head" else "foot" if sh.get("body_part") in ("left_foot", "right_foot") else "other",
                shot_type="Penalty" if sh.get("situation") == "penalty" else "Free Kick" if sh.get("situation") == "direct_free_kick" else "Open Play",
                technique="Normal", pattern=sh.get("play_pattern", "Regular Play"),
                first_time=int(bool(sh.get("first_time"))), under_pressure=0, one_on_one=int(bool(sh.get("one_on_one"))),
                # providers without freeze frames: leave these at neutral values; the model still uses location & context
                blockers=sh.get("defenders_in_cone", 1), gk_dist=sh.get("keeper_distance", dist),
                assist_type=sh.get("assist_type", "pass" if sh.get("assist_player_id") else "none"),
                assister_id=sh.get("assist_player_id"),
                outcome=outcome, goal=int(outcome == "Goal"), on_target=int(outcome in ("Goal", "Saved")), sb_xg=None))
    # ---- end of provider-specific section ----

    pd.DataFrame(matches).to_csv(OUT / "matches.csv", index=False)
    pd.DataFrame(pms).fillna(0).to_csv(OUT / "player_matches.csv", index=False)
    pd.DataFrame(shots).to_csv(OUT / "shots.csv", index=False)
    pd.DataFrame([dict(player_id=k, full_name=v, name=v) for k, v in players.items()]).to_csv(OUT / "players.csv", index=False)
    print(f"{len(matches)} matches, {len(shots)} shots")


if __name__ == "__main__":
    main()
