name: Update stats

on:
  schedule:
    # 06:17 UTC daily: picks up every weekend and midweek round the morning after
    - cron: "17 6 * * *"
  workflow_dispatch: {}

permissions:
  contents: write
  pages: write
  id-token: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Find project folder
        id: dir
        run: |
          f=$(find . -path '*/pipeline/fetch_basic.py' -not -path './.git/*' | head -1)
          if [ -z "$f" ]; then
            echo "::error::Couldn't find pipeline/fetch_basic.py in this repository. Upload the project files first."
            ls -R | head -50
            exit 1
          fi
          d=$(dirname "$(dirname "$f")")
          echo "Project folder: $d"
          echo "path=$d" >> "$GITHUB_OUTPUT"

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install packages
        working-directory: ${{ steps.dir.outputs.path }}
        run: pip install pandas numpy scikit-learn joblib

      - uses: actions/cache@v4
        with:
          path: ${{ steps.dir.outputs.path }}/cache
          key: provider-cache-${{ github.run_id }}
          restore-keys: provider-cache-

      - name: Fetch this season's table, results and scorers (free plan)
        working-directory: ${{ steps.dir.outputs.path }}
        env:
          FOOTBALL_DATA_TOKEN: ${{ secrets.FOOTBALL_DATA_TOKEN }}
        run: python pipeline/fetch_basic.py site/live.json

      # The steps below only run once you add a paid provider (set the DATA_API_BASE variable).
      - name: Fetch new matches with shot data (paid plan)
        if: ${{ vars.DATA_API_BASE != '' }}
        working-directory: ${{ steps.dir.outputs.path }}
        env:
          DATA_API_KEY: ${{ secrets.DATA_API_KEY }}
          DATA_API_BASE: ${{ vars.DATA_API_BASE }}
          SEASON: ${{ vars.SEASON }}
        run: python pipeline/fetch_live.py data

      - name: Score shots with the Touchline xG model
        if: ${{ vars.DATA_API_BASE != '' }}
        working-directory: ${{ steps.dir.outputs.path }}
        run: python pipeline/score_xg.py data model/xg_model.joblib

      - name: Build full stats
        if: ${{ vars.DATA_API_BASE != '' }}
        working-directory: ${{ steps.dir.outputs.path }}
        run: python pipeline/build_stats.py data site/data.json "${{ vars.SEASON_LABEL }}"

      - name: Commit updated stats
        working-directory: ${{ steps.dir.outputs.path }}
        run: |
          git config user.name "touchline-bot"
          git config user.email "touchline-bot@users.noreply.github.com"
          git add site/data.json site/live.json
          git diff --cached --quiet || git commit -m "Update stats $(date -u +%F)"
          git push

      - name: Package site
        working-directory: ${{ steps.dir.outputs.path }}
        run: python pipeline/package_site.py dist

      - uses: actions/upload-pages-artifact@v3
        with:
          path: ${{ steps.dir.outputs.path }}/dist

  deploy:
    needs: update
    runs-on: ubuntu-latest
    environment:
      name: github-pages
    steps:
      - uses: actions/deploy-pages@v4
