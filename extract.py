"""Turn raw StatsBomb event/lineup JSON into tidy tables.

Outputs (in data/):
  shots.csv          one row per shot, with model features
  player_matches.csv one row per player per match (minutes + counting stats)
  matches.csv        results
"""
import json, math, sys
from pathlib import Path
from collections import defaultdict
import pandas as pd

RAW = Path(sys.argv[1] if len(sys.argv) > 1 else "raw")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "data")
OUT.mkdir(exist_ok=True)

GOAL_X, GOAL_Y = 120.0, 40.0
POST_L, POST_R = 36.0, 44.0


def clock(t):
    m, s = t.split(":")
    return int(m) + int(s) / 60


def shot_geometry(x, y):
    dist = math.hypot(GOAL_X - x, GOAL_Y - y)
    a1 = math.atan2(POST_L - y, GOAL_X - x)
    a2 = math.atan2(POST_R - y, GOAL_X - x)
    angle = abs(a2 - a1)
    return dist, angle


def in_triangle(p, a, b, c):
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def is_progressive(start, end):
    """Moves the ball at least 25% closer to goal centre, ending in the attacking 60%."""
    d0 = math.hypot(GOAL_X - start[0], GOAL_Y - start[1])
    d1 = math.hypot(GOAL_X - end[0], GOAL_Y - end[1])
    return end[0] >= 48 and d1 <= 0.75 * d0 and start[0] < end[0]


matches = json.load(open(RAW / "matches.json"))
names, nicks = {}, {}
shots, pm_rows, match_rows = [], [], []

for m in matches:
    mid = m["match_id"]
    home, away = m["home_team"]["home_team_name"], m["away_team"]["away_team_name"]
    match_rows.append(dict(match_id=mid, date=m["match_date"], week=m.get("match_week"),
                           home=home, away=away, hg=m["home_score"], ag=m["away_score"]))
    events = json.load(open(RAW / "events" / f"{mid}.json"))
    lineups = json.load(open(RAW / "lineups" / f"{mid}.json"))
    by_id = {e["id"]: e for e in events}
    end_clock = max(e["minute"] + e["second"] / 60 for e in events if e["period"] <= 2)

    # minutes played from lineup position spells
    pstats = {}
    for team in lineups:
        for p in team["lineup"]:
            names[p["player_id"]] = p["player_name"]
            if p.get("player_nickname"):
                nicks[p["player_id"]] = p["player_nickname"]
            if not p["positions"]:
                continue
            start = min(clock(s["from"]) for s in p["positions"])
            ends = [end_clock if s["to"] is None else clock(s["to"]) for s in p["positions"]]
            # count to a 90-minute clock (stoppage time not credited), as most stats sites do
            mins = max(1.0, min(max(ends), 90.0) - min(start, 89.0))
            pos = p["positions"][0]["position"]
            pstats[p["player_id"]] = defaultdict(float, dict(
                match_id=mid, player_id=p["player_id"], team=team["team_name"], position=pos,
                start=1.0 if p["positions"][0]["start_reason"] == "Starting XI" else 0.0,
                minutes=round(mins, 1)))

    def bump(e, key, n=1):
        pid = e.get("player", {}).get("id")
        if pid in pstats:
            pstats[pid][key] += n

    for e in events:
        t = e["type"]["name"]
        if t == "Pass":
            p = e["pass"]
            ok = "outcome" not in p
            bump(e, "passes")
            if ok:
                bump(e, "passes_cmp")
                if p.get("type", {}).get("name") not in ("Corner", "Throw-in", "Free Kick", "Goal Kick", "Kick Off") \
                        and is_progressive(e["location"], p["end_location"]):
                    bump(e, "prog_passes")
            if p.get("shot_assist") or p.get("goal_assist"):
                bump(e, "key_passes")
            if p.get("goal_assist"):
                bump(e, "assists")
        elif t == "Carry":
            c = e["carry"]
            if is_progressive(e["location"], c["end_location"]) and \
                    math.hypot(c["end_location"][0] - e["location"][0], c["end_location"][1] - e["location"][1]) >= 5:
                bump(e, "prog_carries")
        elif t == "Dribble":
            bump(e, "dribbles")
            if e["dribble"].get("outcome", {}).get("name") == "Complete":
                bump(e, "dribbles_won")
        elif t == "Duel" and e.get("duel", {}).get("type", {}).get("name") == "Tackle":
            if e["duel"].get("outcome", {}).get("name") in ("Won", "Success", "Success In Play", "Success Out"):
                bump(e, "tackles_won")
        elif t == "Interception":
            if e["interception"].get("outcome", {}).get("name") in ("Won", "Success", "Success In Play", "Success Out"):
                bump(e, "interceptions")
        elif t == "Ball Recovery" and not e.get("ball_recovery", {}).get("recovery_failure"):
            bump(e, "recoveries")
        elif t == "Shot":
            s = e["shot"]
            x, y = e["location"]
            dist, angle = shot_geometry(x, y)
            # defenders (incl. keeper) inside the shooting triangle, and keeper distance from goal
            blockers, gk_dist = 0, None
            for f in s.get("freeze_frame", []):
                if f["teammate"]:
                    continue
                if f["position"]["name"] == "Goalkeeper":
                    gk_dist = math.hypot(GOAL_X - f["location"][0], GOAL_Y - f["location"][1])
                elif in_triangle(f["location"], (x, y), (GOAL_X, POST_L), (GOAL_X, POST_R)):
                    blockers += 1
            kp = by_id.get(s.get("key_pass_id")) if s.get("key_pass_id") else None
            assist_type = "none"
            if kp:
                kpp = kp["pass"]
                if kpp.get("cross"):
                    assist_type = "cross"
                elif kpp.get("through_ball") or kpp.get("technique", {}).get("name") == "Through Ball":
                    assist_type = "through"
                elif kpp.get("cut_back"):
                    assist_type = "cutback"
                else:
                    assist_type = "pass"
            shots.append(dict(
                match_id=mid, shot_id=e["id"], minute=e["minute"], team=e["team"]["name"],
                player_id=e["player"]["id"], x=x, y=y, dist=dist, angle=angle,
                body=("head" if s["body_part"]["name"] == "Head" else "foot" if "Foot" in s["body_part"]["name"] else "other"),
                shot_type=s["type"]["name"], technique=s.get("technique", {}).get("name", "Normal"),
                pattern=e["play_pattern"]["name"], first_time=int(bool(s.get("first_time"))),
                under_pressure=int(bool(e.get("under_pressure"))), one_on_one=int(bool(s.get("one_on_one"))),
                blockers=blockers, gk_dist=gk_dist if gk_dist is not None else dist,
                assist_type=assist_type, assister_id=kp["player"]["id"] if kp else None,
                outcome=s["outcome"]["name"], goal=int(s["outcome"]["name"] == "Goal"),
                on_target=int(s["outcome"]["name"] in ("Goal", "Saved", "Saved To Post")),
                sb_xg=s.get("statsbomb_xg"),
            ))
    pm_rows.extend(dict(v) for v in pstats.values())

pd.DataFrame(shots).to_csv(OUT / "shots.csv", index=False)
pd.DataFrame(pm_rows).fillna(0).to_csv(OUT / "player_matches.csv", index=False)
pd.DataFrame(match_rows).to_csv(OUT / "matches.csv", index=False)
pd.DataFrame([dict(player_id=k, full_name=v, name=nicks.get(k, v)) for k, v in names.items()]) \
    .to_csv(OUT / "players.csv", index=False)
print(f"{len(shots)} shots, {len(pm_rows)} player-matches, {len(match_rows)} matches")
