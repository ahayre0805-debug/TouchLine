"""Aggregate tidy tables + xG into the JSON the website reads."""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "site/data.json")
SEASON = sys.argv[3] if len(sys.argv) > 3 else "2015/16"

shots = pd.read_csv(DATA / "shots.csv")
pm = pd.read_csv(DATA / "player_matches.csv")
matches = pd.read_csv(DATA / "matches.csv")
players = pd.read_csv(DATA / "players.csv").set_index("player_id")


def pos_group(p):
    if p == "Goalkeeper": return "GK"
    if "Back" in p: return "DF"
    if "Forward" in p or "Striker" in p or "Wing" in p and "Back" not in p: return "FW"
    return "MF"


shots["pen"] = shots.shot_type.eq("Penalty")
g = shots.groupby("player_id")
shot_agg = pd.DataFrame({
    "shots": g.size(), "sot": g.on_target.sum(), "goals": g.goal.sum(),
    "pk_goals": shots[shots.pen].groupby("player_id").goal.sum(),
    "pk_att": shots[shots.pen].groupby("player_id").size(),
    "xg": g.xg.sum(), "npxg": shots[~shots.pen].groupby("player_id").xg.sum(),
    "np_shots": shots[~shots.pen].groupby("player_id").size(),
}).fillna(0)
xa = shots.dropna(subset=["assister_id"]).groupby("assister_id").xg.sum().rename("xa")
xa.index = xa.index.astype(int)

cnt = ["minutes", "start", "passes", "passes_cmp", "prog_passes", "prog_carries", "key_passes",
       "assists", "dribbles", "dribbles_won", "tackles_won", "interceptions", "recoveries"]
for c in cnt:
    if c not in pm: pm[c] = 0
agg = pm.groupby("player_id")[cnt].sum()
agg["apps"] = pm.groupby("player_id").size()
# a player's team = the club he played most minutes for (a few moved in January)
main = pm.sort_values("minutes").groupby("player_id").tail(1).set_index("player_id")
pos_minutes = pm.assign(pg=pm.position.map(pos_group)).groupby(["player_id", "pg"]).minutes.sum()
agg["pos"] = pos_minutes.groupby(level=0).idxmax().map(lambda t: t[1])
agg["team"] = pm.groupby(["player_id", "team"]).minutes.sum().groupby(level=0).idxmax().map(lambda t: t[1])
agg["teams"] = pm.groupby("player_id").team.nunique()
df = agg.join(shot_agg).join(xa).fillna(0)
df["name"] = players.name.reindex(df.index)
df["np_goals"] = df.goals - df.pk_goals
df = df[df.minutes > 0]

rows = []
for pid, r in df.sort_values("xg", ascending=False).iterrows():
    rows.append({
        "id": int(pid), "name": r["name"], "team": r.team, "pos": r.pos, "multi": int(r.teams > 1),
        "apps": int(r.apps), "starts": int(r.start), "min": int(round(r.minutes)),
        "g": int(r.goals), "npg": int(r.np_goals), "a": int(r.assists),
        "sh": int(r.shots), "sot": int(r.sot), "pkg": int(r.pk_goals), "pka": int(r.pk_att),
        "xg": round(r.xg, 2), "npxg": round(r.npxg, 2), "xa": round(r.xa, 2), "kp": int(r.key_passes),
        "nps": int(r.np_shots),
        "pas": int(r.passes), "pcmp": int(r.passes_cmp), "prgp": int(r.prog_passes), "prgc": int(r.prog_carries),
        "drb": int(r.dribbles), "drbw": int(r.dribbles_won), "tkl": int(r.tackles_won),
        "int": int(r.interceptions), "rec": int(r.recoveries),
    })

# shots per player for shot maps: [x, y, xg, outcome code, body, minute, match_id]
OC = {"Goal": 0, "Saved": 1, "Saved To Post": 1, "Blocked": 2, "Off T": 3, "Wayward": 3, "Post": 3, "Saved Off Target": 3}
shot_map = {}
for r in shots.itertuples():
    shot_map.setdefault(int(r.player_id), []).append(
        [round(r.x, 1), round(r.y, 1), round(r.xg, 3), OC.get(r.outcome, 3), r.body[0], int(r.minute), int(r.match_id),
         r.team, int(r.shot_type == "Penalty")])

# match results + xG
mx = shots.groupby(["match_id", "team"]).xg.sum()
match_list, table = [], {}
for m in matches.sort_values(["date", "match_id"]).itertuples():
    hx, ax = float(mx.get((m.match_id, m.home), 0)), float(mx.get((m.match_id, m.away), 0))
    match_list.append({"id": int(m.match_id), "date": m.date, "wk": int(m.week) if pd.notna(m.week) else None,
                       "h": m.home, "a": m.away, "hg": int(m.hg), "ag": int(m.ag),
                       "hxg": round(hx, 2), "axg": round(ax, 2)})
    for team, gf, ga, xf, xa_ in ((m.home, m.hg, m.ag, hx, ax), (m.away, m.ag, m.hg, ax, hx)):
        t = table.setdefault(team, dict(team=team, p=0, w=0, d=0, l=0, gf=0, ga=0, xgf=0.0, xga=0.0, xpts=0.0, form=[]))
        t["p"] += 1; t["gf"] += int(gf); t["ga"] += int(ga); t["xgf"] += xf; t["xga"] += xa_
        res = "W" if gf > ga else "D" if gf == ga else "L"
        t[{"W": "w", "D": "d", "L": "l"}[res]] += 1
        t["form"].append(res)

# expected points: simulate each match from its shots (each shot an independent goal chance)
rng = np.random.default_rng(1)
team_shots = {k: v.xg.values for k, v in shots.groupby(["match_id", "team"])}
for m in match_list:
    hs = team_shots.get((m["id"], m["h"]), np.array([]))
    as_ = team_shots.get((m["id"], m["a"]), np.array([]))
    n = 4000
    hgs = (rng.random((n, len(hs))) < hs).sum(1) if len(hs) else np.zeros(n)
    ags = (rng.random((n, len(as_))) < as_).sum(1) if len(as_) else np.zeros(n)
    hw, dr = (hgs > ags).mean(), (hgs == ags).mean()
    table[m["h"]]["xpts"] += 3 * hw + dr
    table[m["a"]]["xpts"] += 3 * (1 - hw - dr) + dr

tab = sorted(table.values(), key=lambda t: (-(3 * t["w"] + t["d"]), -(t["gf"] - t["ga"]), -t["gf"]))
for t in tab:
    t["pts"] = 3 * t["w"] + t["d"]
    t["xgf"], t["xga"], t["xpts"] = round(t["xgf"], 1), round(t["xga"], 1), round(t["xpts"], 1)
    t["form"] = "".join(t["form"][-5:])

OUT.parent.mkdir(parents=True, exist_ok=True)
rp = DATA / "xg_report.json"
report = json.load(open(rp if rp.exists() else Path("model/xg_report.json")))
json.dump({"season": SEASON, "updated": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
           "source": "StatsBomb Open Data", "model": report,
           "players": rows, "shots": shot_map, "table": tab, "matches": match_list},
          open(OUT, "w"), separators=(",", ":"))
print(f"{len(rows)} players, {len(tab)} teams -> {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
