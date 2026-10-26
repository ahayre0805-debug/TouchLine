"""Train the site's own expected-goals model and score every shot.

Gradient-boosted classifier on shot geometry, body part, situation, assist type and
defender positions. Each shot is scored by a model that never saw it (5-fold
out-of-fold predictions), so a player's xG isn't inflated by the model memorising
his own goals. Penalties use a fixed conversion rate.
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd, joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
PEN_XG = 0.76

NUM = ["dist", "angle", "first_time", "under_pressure", "one_on_one", "blockers", "gk_dist"]
CAT = ["body", "shot_type", "technique", "pattern", "assist_type"]


def features(df, cats=None):
    X = df[NUM].astype(float).copy()
    for c in CAT:
        X[c] = df[c].astype("category") if cats is None else pd.Categorical(df[c], categories=cats[c])
    return X


def model():
    return HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=40,
        l2_regularization=1.0, categorical_features="from_dtype", random_state=7)


shots = pd.read_csv(DATA / "shots.csv")
is_pen = shots.shot_type.eq("Penalty")
train = shots[~is_pen].reset_index()
X, y = features(train), train.goal.values
cats = {c: list(X[c].cat.categories) for c in CAT}

oof = np.zeros(len(train))
for tr, te in StratifiedKFold(5, shuffle=True, random_state=7).split(X, y):
    oof[te] = model().fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]

final = model().fit(X, y)
Path("model").mkdir(exist_ok=True)
joblib.dump({"model": final, "cats": cats, "pen_xg": PEN_XG}, Path("model") / "xg_model.joblib")

shots["xg"] = PEN_XG
shots.loc[train["index"], "xg"] = oof
shots.to_csv(DATA / "shots.csv", index=False)

ref = train.sb_xg.notna()
report = {
    "shots": int(len(train)),
    "log_loss": round(log_loss(y, oof), 4),
    "baseline_log_loss": round(log_loss(y, np.full(len(y), y.mean())), 4),
    "auc": round(roc_auc_score(y, oof), 4),
    "brier": round(brier_score_loss(y, oof), 4),
    "total_xg_vs_goals": [round(float(oof.sum()), 1), int(y.sum())],
    "corr_with_statsbomb_xg": round(float(np.corrcoef(oof[ref], train.sb_xg[ref])[0, 1]), 3),
    "statsbomb_auc_same_shots": round(roc_auc_score(y[ref], train.sb_xg[ref]), 4),
}
json.dump(report, open(DATA / "xg_report.json", "w"), indent=2)
json.dump(report, open(Path("model") / "xg_report.json", "w"), indent=2)
print(json.dumps(report, indent=2))
