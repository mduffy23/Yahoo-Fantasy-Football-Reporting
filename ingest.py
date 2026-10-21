import yahoo_fantasy_api as yfa
from yahoo_oauth import OAuth2
from sqlalchemy import create_engine, text
from sqlalchemy.types import Integer, String, Float, Boolean, Date, BigInteger, DateTime
import pandas as pd
from getParlays import get_parlays
import os
from datetime import datetime, timezone
import tempfile
import atexit

# Set up
## Leagues
idMap = {2023: '423.l.927065', 2024: '449.l.978032', 2025: '461.l.1390291', 2026: '470.l.628639'}

## Creds
oauth_json = os.environ.get("YAHOO_OAUTH_JSON")
oauth_file = "oauth2.json"
if oauth_json:
    # GitHub Actions receives the complete Yahoo OAuth token file as a secret.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as token_file:
        token_file.write(oauth_json)
        oauth_file = token_file.name
    atexit.register(lambda: os.unlink(oauth_file) if os.path.exists(oauth_file) else None)
elif os.environ.get("GITHUB_ACTIONS") == "true":
    raise RuntimeError("Set the YAHOO_OAUTH_JSON GitHub Actions secret")

oauth = OAuth2(None, None, from_file=oauth_file)
if not oauth.token_is_valid():
    oauth.refresh_access_token()
gm = yfa.Game(oauth, "nfl")

## Database connection
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("Set DATABASE_URL to the PostgreSQL connection URL")
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg2://" + database_url[len("postgres://"):]
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg2://" + database_url[len("postgresql://"):]
engine = create_engine(database_url)

# Weekly run
currentSeason = max(list(idMap.keys()))
lg = gm.to_league(idMap[currentSeason])
settings = lg.settings()
current_week = lg.current_week()
league_id = idMap[currentSeason]
## Current matchup
rows = []
matchup = lg.matchups(current_week)["fantasy_content"]["league"][1]['scoreboard']

for key, value in matchup['0']['matchups'].items():
    if key != 'count':
        match = value['matchup']
        week = match['week']
        week_start = match['week_start']
        week_end = match['week_end']
        isPlayoff = match['is_playoffs']
        teams = match['0']['teams']
        
        team1 = teams['0']['team'][0][2]['name']
        team2 = teams['1']['team'][0][2]['name']

        # Each matchup has exactly two teams: '0' and '1'
        for side in ['0', '1']:
            team = teams[side]['team']
            team_data = team[0]   # long nested metadata list
            scoring = team[1]     # dict with points and projections

            # --- Extract basic info ---
            team_key = team_data[0]['team_key']
            team_id = team_data[1]['team_id']
            team_name = team_data[2]['name']
            proj_points = float(scoring['team_projected_points']['total'])

            manager_info = None
            for item in team_data:
                if isinstance(item, dict) and 'managers' in item:
                    manager_info = item['managers'][0]['manager']
                    break

            manager_id = manager_info.get('manager_id') if manager_info else None
            nickname = manager_info.get('nickname') if manager_info else None
            guid = team_key

            # --- Add a flattened record ---
            rows.append({
                "season": currentSeason,
                "week": week,
                "week_start": week_start,
                "week_end": week_end,
                "is_playoff": isPlayoff,
                "matchup_id": key,
                "team_id": team_id,
                "team_name": team_name,
                "team_key": team_key,
                "manager_id": manager_id,
                "manager_nickname": nickname,
                "manager_guid": guid,
                "projected_points": proj_points,
            })

currentMatchup = pd.DataFrame(rows)
with engine.begin() as conn:
    conn.execute(text("TRUNCATE TABLE manager_info.currentmatchup RESTART IDENTITY CASCADE;"))

currentMatchup.to_sql('currentmatchup', engine, schema='manager_info', if_exists='append', index=False, dtype={
    "season": Integer(),            # Season
    "week": Integer(),              # week number (1–18)
    "week_start": Date(),           # start date of the week
    "week_end": Date(),             # end date of the week
    "is_playoff": Integer(),        # True if this week is in playoffs
    "matchup_id": Integer(),        # Yahoo matchup ID (numeric)
    "team_id": Integer(),           # numeric team ID
    "team_name": String(100),       # e.g., "Hail Mary john"
    "team_key": String(50),         # Yahoo team key (e.g., "449.l.12345.t.1")
    "manager_id": Integer(),        # numeric manager ID (if available)
    "manager_nickname": String(50), # e.g., "Matthew"
    "manager_guid": String(50),     # e.g., "GOBJY4A3RDGQYERM2ETTMRC7YY"
    "projected_points": Float()    # projected points for the matchup
})

## Last weeks data
previousWeek = max(1, current_week - 1)

rows = []
managers = []
matchup = lg.matchups(previousWeek)["fantasy_content"]["league"][1]['scoreboard']

for key, value in matchup['0']['matchups'].items():
    if key != 'count':
        match = value['matchup']
        if match['is_matchup_recap_available'] != 0:
            week = match['week']
            week_start = match['week_start']
            week_end = match['week_end']
            isPlayoff = match['is_playoffs']
            teams = match['0']['teams']
            
            team1 = teams['0']['team'][0][2]['name']
            team2 = teams['1']['team'][0][2]['name']

            points1 = float(teams['0']['team'][1]['team_points']['total'])
            points2 = float(teams['1']['team'][1]['team_points']['total'])

            # Chat
            recap_url = match['matchup_recap_url']
            week = int(match['week'])
            winner_key = match['winner_team_key']

            # Each matchup has exactly two teams: '0' and '1'
            for side in ['0', '1']:
                team = teams[side]['team']
                team_data = team[0]   # long nested metadata list
                scoring = team[1]     # dict with points and projections

                # --- Extract basic info ---
                team_key = team_data[0]['team_key']
                team_id = team_data[1]['team_id']
                team_name = team_data[2]['name']
                points = float(scoring['team_points']['total'])
                proj_points = float(scoring['team_projected_points']['total'])

                # --- Winner flag ---
                winner = team_key == winner_key

                # --- Extract manager info ---
                manager_info = None
                for item in team_data:
                    if isinstance(item, dict) and 'managers' in item:
                        manager_info = item['managers'][0]['manager']
                        break

                manager_id = manager_info.get('manager_id') if manager_info else None
                nickname = manager_info.get('nickname') if manager_info else None
            guid = manager_info.get('guid') if manager_info else None
            if guid == '--hidden--':
                guid = team_key

                if previousWeek == 1:
                    num_moves, num_trades = None, None
                    for item in team_data:
                        if isinstance(item, dict):
                            if 'number_of_moves' in item:
                                num_moves = int(item['number_of_moves'])
                            elif 'number_of_trades' in item:
                                try:
                                    num_trades = int(item['number_of_trades'])
                                except ValueError:
                                    num_trades = None
                    managers.append({
                        "manager_guid": guid,
                        "season": currentSeason,
                        "league_id": league_id,
                        "manager_id": manager_id,
                        "manager_nickname": nickname,
                        "team_id": team_id,
                        "team_key": team_key,
                        "number_of_moves": num_moves,
                        "number_of_trades": num_trades
                    })

                # --- Add a flattened record ---
                rows.append({
                    "season": currentSeason,
                    "week": week,
                    "week_start": week_start,
                    "week_end": week_end,
                    "is_playoff": isPlayoff,
                    "matchup_id": key,
                    "team_id": team_id,
                    "team_name": team_name,
                    "team_key": team_key,
                    "manager_id": manager_id,
                    "manager_nickname": nickname,
                    "manager_guid": guid,
                    "points": points,
                    "projected_points": proj_points,
                    "winner": winner,
                    "recap_url": recap_url
                })

lastWeekMatchup = pd.DataFrame(rows)
lastWeekMatchup['game_quality'] = pd.cut(lastWeekMatchup['points'], bins =[0, 120, 150, float('inf')], labels = ['poor', 'average', 'strong'])

## Update managers and manager_seasons tables
if previousWeek == 1:
    manager_seasons_df = pd.DataFrame(managers)
    managers_df = manager_seasons_df[['manager_guid', 'manager_nickname']].drop_duplicates()
    manager_seasons_df = manager_seasons_df.drop(columns=['manager_nickname', 'manager_id'])

    # Existing managers
    manager_current = pd.read_sql("SELECT * FROM manager_info.managers", engine)

    # Get any new managers
    managers_new = managers_df[
        ~managers_df['manager_guid'].isin(manager_current['manager_guid'])
    ]
    managers_new.to_sql("managers", engine, schema='manager_info', if_exists="append", index=False)
    manager_seasons_df.to_sql("manager_seasons", engine, schema='manager_info', if_exists="append", index=False)

if previousWeek != 0:
    
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM manager_info.matchups WHERE season = :season AND week = :week"),
                     {"season": currentSeason, "week": previousWeek})
    lastWeekMatchup.to_sql('matchups', engine, schema='manager_info', if_exists='append', index=False, dtype={
        "season": Integer(),            # Season year
        "week": Integer(),              # week number (1–18)
        "week_start": Date(),           # start date of the week
        "week_end": Date(),             # end date of the week
        "is_playoff": Integer(),        # True if this week is in playoffs
        "matchup_id": Integer(),        # Yahoo matchup ID (numeric)
        "team_id": Integer(),           # numeric team ID
        "team_name": String(100),       # e.g., "Hail Mary john"
        "team_key": String(50),         # Yahoo team key (e.g., "449.l.12345.t.1")
        "manager_id": Integer(),        # numeric manager ID (if available)
        "manager_nickname": String(50), # e.g., "Matthew"
        "manager_guid": String(50),     # e.g., "GOBJY4A3RDGQYERM2ETTMRC7YY"
        "points": Float(),              # actual fantasy points scored
        "projected_points": Float(),    # projected points for the matchup
        "winner": String(10),           # 'win', 'loss', 'tie', or None
        "recap_url": String(255),       # URL to Yahoo recap (can be long)
        "game_quality": String(10)      # Designation of strong, average, or poor game
    })

    previousWeekPlayers = []
    teams = lg.teams()

    for team_name, team in teams.items():
        roster = lg.to_team(team_name).roster(week=previousWeek)
        playerIds = [player["player_id"] for player in roster]
        stats = lg.player_stats(playerIds, req_type='week', week=previousWeek)            
        for player, stat in zip(roster, stats):
            previousWeekPlayers.append({
                        "season": currentSeason,
                        "week": previousWeek,
                        "team_key": team_name,
                        "team_name": team['name'],
                        "manager_guid": team_name,
                        "manager_name": team['managers'][0]['manager']['nickname'],
                        "player_id": player["player_id"],
                        "player_name": player["name"],
                        "played_position": player['selected_position'],
                        "position_type": stat['position_type'],
                        "pass_yds": stat['Pass Yds'] if 'Pass Yds' in stat else 0,
                        "pass_td": stat['Pass TD'] if 'Pass TD' in stat else 0,
                        "pass_int": stat['Int'] if 'Int' in stat and player['position_type'] == 'O' else 0,
                        "rush_att": stat['Rush Att'] if 'Rush Att' in stat else 0,
                        "rush_yds": stat['Rush Yds'] if 'Rush Yds' in stat else 0,
                        "rush_td": stat['Rush TD'] if 'Rush TD' in stat else 0,
                        "targets": stat['Targets'] if 'Targets' in stat else 0,
                        "rec": stat['Rec'] if 'Rec' in stat else 0,
                        "rec_yds": stat['Rec Yds'] if 'Rec Yds' in stat else 0,
                        "rec_td": stat['Rec TD'] if 'Rec TD' in stat else 0,
                        "offensive_ret_td": stat['Ret TD'] if 'Ret TD' in stat and player['position_type'] == 'O' else 0,
                        "two_pt_conversion": stat['2-PT'] if '2-PT' in stat else 0,
                        "fum_lost": stat['Fum Lost'] if 'Fum Lost' in stat else 0,
                        "fum_ret_td": stat['Fum Ret TD'] if 'Fum Ret TD' in stat else 0,
                        'fg_0_19': stat['FG 0-19'] if 'FG 0-19' in stat else 0,
                        'fg_20_29': stat['FG 20-29'] if 'FG 20-29' in stat else 0,
                        'fg_30_39': stat['FG 30-39'] if 'FG 30-39' in stat else 0,
                        'fg_40_49': stat['FG 40-49'] if 'FG 40-49' in stat else 0,
                        'fg_50_plus': stat['FG 50+'] if 'FG 50+' in stat else 0,
                        'pat_made': stat['PAT Made'] if 'PAT Made' in stat else 0,
                        'pts_allow': stat['Pts Allow'] if 'Pts Allow' in stat else 0,
                        'sack': stat['Sack'] if 'Sack' in stat else 0,
                        'dt_int': stat['Int'] if 'Int' in stat and player['position_type'] == 'DT' else 0,
                        'fum_rec': stat['Fum Rec'] if 'Fum Rec' in stat else 0,
                        'dt_td': stat['TD'] if 'TD' in stat and player['position_type'] == 'DT' else 0,
                        'safe': stat['Safe'] if 'Safe' in stat else 0,
                        'blk_kick': stat['Blk Kick'] if 'Blk Kick' in stat else 0,
                        'dt_ret_td': stat['Ret TD'] if 'Ret TD' in stat and player['position_type'] == 'DT' else 0,
                        'pts_allow_0': stat['Pts Allow 0'] if 'Pts Allow 0' in stat else 0,
                        'pts_allow_1_6': stat['Pts Allow 1-6'] if 'Pts Allow 1-6' in stat else 0,
                        'pts_allow_7_13': stat['Pts Allow 7-13'] if 'Pts Allow 7-13' in stat else 0,
                        'pts_allow_14_20': stat['Pts Allow 14-20'] if 'Pts Allow 14-20' in stat else 0,
                        'pts_allow_21_27': stat['Pts Allow 21-27'] if 'Pts Allow 21-27' in stat else 0,
                        'pts_allow_28_34': stat['Pts Allow 28-34'] if 'Pts Allow 28-34' in stat else 0,
                        'pts_allow_35_plus': stat['Pts Allow 35+'] if 'Pts Allow 35+' in stat else 0,
                        'xpr': stat['XPR'] if 'XPR' in stat else 0,
                        "points": stat['total_points'] if 'total_points' in stat else 0,
                    })

    previousWeekRoster = pd.DataFrame(previousWeekPlayers)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_info.detailed_roster WHERE season = :season AND week = :week"),
                     {"season": currentSeason, "week": previousWeek})
    previousWeekRoster.to_sql('detailed_roster', engine, schema='player_info', if_exists='append', index=False, chunksize=200, dtype={
            "season": Integer(),
            "week": Integer(),
            "team_key": String(100),
            "team_name": String(100),
            "manager_guid": String(50),
            "manager_name": String(50),
            "player_id": Integer(),
            "player_name": String(100),
            "played_position": String(10),
            "position_type": String(5),

            # Passing
            "pass_yds": Integer(),
            "pass_td": Integer(),
            "pass_int": Integer(),

            # Rushing
            "rush_att": Integer(),
            "rush_yds": Integer(),
            "rush_td": Integer(),

            # Receiving
            "targets": Integer(),
            "rec": Integer(),
            "rec_yds": Integer(),
            "rec_td": Integer(),

            # Misc offensive
            "offensive_ret_td": Integer(),
            "two_pt_conversion": Integer(),
            "fum_lost": Integer(),
            "fum_ret_td": Integer(),

            # Kicker
            "fg_0_19": Integer(),
            "fg_20_29": Integer(),
            "fg_30_39": Integer(),
            "fg_40_49": Integer(),
            "fg_50_plus": Integer(),
            "pat_made": Integer(),
            "xpr": Integer(),

            # Defense
            "pts_allow": Integer(),
            "sack": Integer(),
            "dt_int": Integer(),
            "fum_rec": Integer(),
            "dt_td": Integer(),
            "safe": Integer(),
            "blk_kick": Integer(),
            "dt_ret_td": Integer(),

            # Defense point tiers
            "pts_allow_0": Integer(),
            "pts_allow_1_6": Integer(),
            "pts_allow_7_13": Integer(),
            "pts_allow_14_20": Integer(),
            "pts_allow_21_27": Integer(),
            "pts_allow_28_34": Integer(),
            "pts_allow_35_plus": Integer(),

            # Final fantasy points
            "points": Float()
        }
    )

sheet_week = f'Week {previousWeek} - {currentSeason}'
parlays = get_parlays(sheet_week)
parlays['season'] = currentSeason
parlays['week'] = previousWeek
parlays.columns = parlays.columns.str.strip()  # Remove leading/trailing whitespace from column names
parlays = parlays[['season', 'week', 'Manager', 'Bet', 'Hit']]
parlays.rename(columns={'Manager': 'manager', 'Bet': 'bet', 'Hit': 'hit'}, inplace=True)

with engine.begin() as conn:
    conn.execute(text("DELETE FROM transactions.parlays WHERE season = :season AND week = :week"),
                 {"season": currentSeason, "week": previousWeek})
parlays.to_sql('parlays', engine, schema='transactions', if_exists='append', index=False, dtype={
    "season": Integer(),            # Season year
    "week": Integer(),              # week number (1–18)
    "manager": String(50),          # manager nickname
    "bet": String(100),             # bet description
    "hit": String(20),              # 'Yes' or 'No'
})


def transaction_player_entries(transaction):
    players = transaction.get("players", {})
    return [value for key, value in players.items() if key != "count"]


def transaction_metadata(player_entry):
    player_block = player_entry["player"]
    player_info = player_block[0]
    raw = player_block[1]["transaction_data"]
    info = raw[0] if isinstance(raw, list) else raw
    return player_info, info


def yahoo_transaction_rows(league, season, league_key):
    """Return all normalized player-level trade and add/drop rows."""
    trades, waivers = [], []
    for transaction in league.transactions("trade", ""):
        for entry in transaction_player_entries(transaction):
            player, details = transaction_metadata(entry)
            name = player[2]["name"]["full"]
            trades.append({
                "season": season, "league_id": league_key,
                "trade_id": int(transaction["transaction_id"]),
                "timestamp": int(transaction["timestamp"]),
                "status": transaction.get("status"),
                "from_team": details.get("source_team_name"),
                "from_team_key": details.get("source_team_key"),
                "to_team": details.get("destination_team_name"),
                "to_team_key": details.get("destination_team_key"),
                "player": name, "player_id": int(player[1]["player_id"]),
                "pos": player[4].get("display_position"),
                "team_abbr": player[3].get("editorial_team_abbr"),
            })
    for transaction in league.transactions("add", ""):
        for entry in transaction_player_entries(transaction):
            player, details = transaction_metadata(entry)
            action = details.get("type")
            team_role = "destination" if action == "add" else "source"
            waivers.append({
                "season": season, "league_id": league_key,
                "trade_id": str(transaction["transaction_id"]),
                "timestamp": datetime.fromtimestamp(int(transaction["timestamp"]), timezone.utc).replace(tzinfo=None),
                "status": transaction.get("status"), "type": action,
                "team": details.get(f"{team_role}_team_name"),
                "team_key": details.get(f"{team_role}_team_key"),
                "player": player[2]["name"]["full"],
                "player_id": int(player[1]["player_id"]),
                "pos": player[4].get("display_position"),
                "team_abbr": player[3].get("editorial_team_abbr"),
            })
    return trades, waivers


# Refresh the complete current-season transaction history on every run.
trade_rows, waiver_rows = yahoo_transaction_rows(
    lg, currentSeason, league_id
)

trade_columns = [
    "season", "league_id", "trade_id", "timestamp", "status", "from_team",
    "from_team_key", "to_team", "to_team_key", "player", "player_id", "pos", "team_abbr",
]
waiver_columns = [
    "season", "league_id", "trade_id", "timestamp", "status", "type", "team",
    "team_key", "player", "player_id", "pos", "team_abbr",
]

def replace_transaction_rows(conn, table, rows, columns, keys):
    if not rows:
        return
    values = ", ".join(f":{column}" for column in columns)
    column_names = ", ".join(columns)
    conflict_keys = ", ".join(keys)
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in columns if column not in keys
    )
    query = text(
        f"INSERT INTO transactions.{table} ({column_names}) VALUES ({values}) "
        f"ON CONFLICT ({conflict_keys}) DO UPDATE SET {updates}"
    )
    conn.execute(query, rows)

with engine.begin() as conn:
    params = {"season": currentSeason, "league": league_id}
    conn.execute(
        text("DELETE FROM transactions.trades WHERE season = :season AND league_id = :league"),
        params,
    )
    conn.execute(
        text("DELETE FROM transactions.waivers WHERE season = :season AND league_id = :league"),
        params,
    )
    replace_transaction_rows(
        conn, "trades", trade_rows, trade_columns, ["league_id", "trade_id", "player_id"]
    )
    replace_transaction_rows(
        conn, "waivers", waiver_rows, waiver_columns, ["league_id", "trade_id", "player_id"]
    )
