# Touchline

A free Premier League stats site with its own expected goals (xG) model, in the spirit of FBref.

Live prototype: Premier League 2015/16, built from StatsBomb Open Data.

## What's here

```
pipeline/
  extract.py      StatsBomb JSON  -> tidy tables (shots, player-matches, matches, players)
  xg_model.py     trains the xG model, scores every shot out-of-fold, saves model/xg_model.joblib
  fetch_live.py   licensed provider API -> the same tidy tables (adapt to your provider)
  score_xg.py     applies the saved model to new shots (used for live updates)
  build_stats.py  tidy tables -> site/data.json (players, shots, league table, matches)
model/            trained xG model + accuracy report
site/             index.html + data.json: the whole website, static files only
.github/workflows/update.yml   daily scheduled update + deploy to GitHub Pages
```

## Rebuild the 2015/16 site locally

```bash
pip install -r requirements.txt
mkdir -p raw/events raw/lineups
curl -s https://raw.githubusercontent.com/statsbomb/open-data/master/data/matches/2/27.json -o raw/matches.json
python -c "import json;print('\n'.join(str(m['match_id']) for m in json.load(open('raw/matches.json'))))" > raw/ids.txt
cat raw/ids.txt | xargs -P 16 -I{} curl -s -o raw/events/{}.json  https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/{}.json
cat raw/ids.txt | xargs -P 16 -I{} curl -s -o raw/lineups/{}.json https://raw.githubusercontent.com/statsbomb/open-data/master/data/lineups/{}.json

python pipeline/extract.py raw data
python pipeline/xg_model.py data
python pipeline/build_stats.py data site/data.json "2015/16"
cd site && python -m http.server 8000      # open http://localhost:8000
```

## Going live with the current season

1. **Pick a data provider whose plan includes shot locations (x/y)** for the Premier League. Without
   locations you can show goals, assists and shot counts, but not xG.
2. **Get two answers in writing before paying:** can you display the data on a free public website,
   and can you publish stats you calculate from it (your xG)?
3. **Adapt `pipeline/fetch_live.py`.** Only the block marked "provider-specific" changes: endpoint
   names and field paths. Its output columns must stay the same.
4. **Push to GitHub**, then in the repo settings:
   - Secrets: `DATA_API_KEY`
   - Variables: `DATA_API_BASE` (provider URL), `SEASON` (e.g. `2026`), `SEASON_LABEL` (e.g. `2026/27`)
   - Pages: source = GitHub Actions
5. The workflow runs every morning, downloads only new matches (finished games are cached), scores
   their shots with the saved model and redeploys. Run it by hand from the Actions tab any time.

The xG model is trained once on StatsBomb data and then only applied, so numbers stay stable
week to week. Retrain occasionally if you add more training data.

## Rules to keep

- **Credit StatsBomb** on any page using their data, with their logo from the StatsBomb media pack
  (required by the Open Data user agreement). Add the logo before you share the site publicly.
- **Don't scrape** FBref, Opta Analyst, FotMob, WhoScored or Understat, and don't republish their xG.
- **No Premier League or club logos.** They're trademarks.
- Read your provider's terms on raw-data downloads. Many allow display but forbid redistribution,
  so think before adding a "download CSV" button.

## Model accuracy (2015/16, out-of-fold)

See `model/xg_report.json`. AUC ≈ 0.76, total xG within 2% of actual non-penalty goals,
correlation with StatsBomb's own xG ≈ 0.82. Easy wins for later: train on more seasons from
StatsBomb Open Data, and add the distance to the nearest defender as a feature.
