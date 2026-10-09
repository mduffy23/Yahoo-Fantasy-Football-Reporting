# MercyFantasy notebook — environment setup

## What the notebook needs
Scanned all 59 cells. Actual dependencies:
- Python 3.11 (matches the notebook's saved kernel)
- `pandas`
- `sqlalchemy` (+ `psycopg2` as the Postgres driver — used via `postgresql://...` connection string, even though `psycopg2` isn't imported directly)
- `yahoo_fantasy_api`
- `yahoo_oauth`

The notebook also expects:
- A local **PostgreSQL server** running (`localhost:5432`, database `mercyfantasy`) — Postgres itself isn't a Python package, so you'll need it installed/running separately (e.g. `brew install postgresql` or Postgres.app on Mac, or a Docker container).
- An `oauth2.json` file in the same directory as the notebook (used by `yahoo_oauth.OAuth2(..., from_file="oauth2.json")`) with your Yahoo API credentials.

## Setup (conda)
```bash
conda env create -f environment.yml
conda activate mercy_fantasy
python -m ipykernel install --user --name mercy_fantasy --display-name "mercy_fantasy"
```
Then open the notebook and select the "mercy_fantasy" kernel — it'll match what's already saved in the notebook's metadata.

## If you'd rather not use conda
A plain `requirements.txt` is included too:
```bash
python3.11 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m ipykernel install --user --name mercy_fantasy --display-name "mercy_fantasy"
```

## One thing worth flagging
Cell 4 has the Postgres username/password hardcoded in plain text in the notebook. That's not an environment issue, but since you're about to share/copy this — worth pulling that into an environment variable or a `.env` file (e.g. via `python-dotenv`) before this notebook goes anywhere else. Happy to do that refactor if you want.
