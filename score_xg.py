"""Score new shots with the already-trained xG model (used for live updates).

Training happens once (xg_model.py on StatsBomb data). Each matchday we only need to
apply that model to the new shots, so player xG never shifts because of a retrain.
"""
import sys
from pathlib import Path
import pandas as pd, joblib

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
MODEL = Path(sys.argv[2] if len(sys.argv) > 2 else "model/xg_model.joblib")

bundle = joblib.load(MODEL)
model, cats, pen = bundle["model"], bundle["cats"], bundle["pen_xg"]
NUM = ["dist", "angle", "first_time", "under_pressure", "one_on_one", "blockers", "gk_dist"]

shots = pd.read_csv(DATA / "shots.csv")
X = shots[NUM].astype(float).copy()
for c, levels in cats.items():
    v = shots[c].where(shots[c].isin(levels))  # values the model never saw become missing, which it handles
    X[c] = pd.Categorical(v, categories=levels)
shots["xg"] = model.predict_proba(X)[:, 1]
shots.loc[shots.shot_type.eq("Penalty"), "xg"] = pen
shots.to_csv(DATA / "shots.csv", index=False)
print(f"scored {len(shots)} shots, total xG {shots.xg.sum():.1f}, goals {shots.goal.sum()}")
