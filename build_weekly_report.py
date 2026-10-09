"""
build_weekly_report.py - run the report queries and write a static site into ./site

Pages written:
    site/index.html    matchup history for the current week
    site/parlays.html  parlay hits and misses for the current season

Usage:
    export DATABASE_URL="postgresql://user:pass@host:5432/postgres"
    python build_weekly_report.py

Requires: pandas, sqlalchemy, psycopg2-binary
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

LEAGUE = "Mercy Fantasy"

MATCHUP_SQL = text('''
Select S.*,
HS.Season as Season_S, HS.Week as Week_S, HS.winningmanager as WinningManager_S, HS.winningpoints as WinningPoints_S,
HS.losingmanager as LosingManager_S, HS.Losingpoints as LosingPoints_S,
HL.Season as Season_L, HL.Week as Week_L, HL.winningmanager as WinningManager_L, HL.winningpoints as WinningPoints_L,
HL.losingmanager as LosingManager_L, HL.Losingpoints as LosingPoints_L
From (
Select M.Season, M.Week, M.projectedwinningmanager, M.projectedlosingmanager, COALESCE(R.Wins, RFallBack.Losses, 0) as LifetimeWins, COALESCE(R.Losses, RFallBack.Wins, 0) as LifetimeLosses, COALESCE(Min(H.pointdiff), 0) as SmallestPointDifferential, COALESCE(Max(H.pointdiff), 0) as LargestPointDifferential
from vw_currentmatchup M
Left Join lifetimerecord R On M.projectedwinningmanager = R.winningmanager and M.projectedlosingmanager = R.losingmanager
Left Join lifetimerecord RFallBack On M.projectedwinningmanager = RFallBack.losingmanager and M.projectedlosingmanager = RFallBack.winningmanager
Left Join matchuphistory H On (M.projectedwinningmanager = H.winningmanager or M.projectedwinningmanager = H.losingmanager) and (M.projectedlosingmanager = H.losingmanager or M.projectedlosingmanager = H.winningmanager)
Group By M.Season, M.Week, M.projectedwinningmanager, M.projectedlosingmanager, COALESCE(R.Wins, RFallBack.Losses, 0), COALESCE(R.Losses, RFallBack.Wins, 0)
) S
Left Join matchuphistory HL On S.LargestPointDifferential = HL.pointdiff and (S.projectedwinningmanager = HL.winningmanager or S.projectedwinningmanager = HL.losingmanager) and (S.projectedlosingmanager = HL.losingmanager or s.projectedlosingmanager = HL.winningmanager)
Left Join matchuphistory HS On S.SmallestPointDifferential = HS.pointdiff and (S.projectedwinningmanager = HS.winningmanager or S.projectedwinningmanager = HS.losingmanager) and (S.projectedlosingmanager = HS.losingmanager or s.projectedlosingmanager = HS.winningmanager)
''')

PARLAY_SQL = text('''
Select manager,
sum(case when hit = 'Y' then 1 else 0 end) as parlay_hits,
sum(case when hit = 'N' then 1 else 0 end) as parlay_misses
From transactions.parlays
Where season = (Select season from vw_current_season)
Group By manager
Order By parlay_hits desc
''')


def to_records(df):
    # to_json turns NaN into null, which is what the pages check for.
    return json.loads(df.to_json(orient="records"))


def fetch_matchups(conn):
    df = pd.read_sql(MATCHUP_SQL, con=conn)
    # Two past games with the same point differential would duplicate a matchup.
    df = df.drop_duplicates(subset=["projectedwinningmanager", "projectedlosingmanager"])
    return to_records(df)


def fetch_parlays(conn):
    return to_records(pd.read_sql(PARLAY_SQL, con=conn))


# ---------------------------------------------------------------- page shell

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --paper: #eef1f4; --ink: #14213d; --muted: #5b6679; --rule: #cfd6df;
  --turf: #2e6b4f; --gold: #d9a21b;
  --display: "Barlow Condensed", "Arial Narrow", sans-serif;
  --body: "Barlow", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root { --paper: #0f1726; --ink: #e8edf4; --muted: #94a1b6; --rule: #26324a; --turf: #4c9b76; --gold: #e8b73a; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 17px/1.5 var(--body); }
main { max-width: 760px; margin: 0 auto; padding: 48px 20px 72px; }
header { border-bottom: 4px solid var(--gold); padding-bottom: 16px; margin-bottom: 8px; }
h1 { margin: 0; font: 700 clamp(44px, 11vw, 84px)/0.95 var(--display); letter-spacing: -0.01em; }
header p { margin: 8px 0 0; color: var(--muted); }
nav { display: flex; gap: 20px; margin-top: 16px; font-weight: 500; }
nav a { color: var(--muted); text-decoration: none; padding-bottom: 2px; border-bottom: 2px solid transparent; }
nav a:hover { color: var(--ink); }
nav a[aria-current] { color: var(--ink); border-bottom-color: var(--turf); }
.matchup { padding: 32px 0; border-bottom: 1px solid var(--rule); }
.teams { display: grid; grid-template-columns: 1fr auto 1fr; gap: 16px; align-items: baseline; }
.name { font: 700 clamp(28px, 6vw, 40px)/1.05 var(--display); overflow-wrap: anywhere; }
.teams .b { text-align: right; }
.vs { color: var(--muted); font-size: 15px; }
.tag { display: block; font: 400 14px/1.4 var(--body); color: var(--turf); margin-top: 2px; }
.series { margin: 20px 0 4px; }
.bar { display: flex; height: 10px; gap: 2px; }
.bar span { display: block; min-width: 3px; }
.bar .a { background: var(--turf); }
.bar .b { background: var(--ink); opacity: 0.8; }
.bar .none { background: var(--rule); flex: 1; }
.series p { margin: 8px 0 0; font-weight: 500; }
.ledger { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 20px; }
.game h4 { margin: 0; font: 500 15px/1.3 var(--body); color: var(--muted); }
.margin { font: 700 56px/1 var(--display); color: var(--gold); margin: 2px 0 4px; }
.game p { margin: 0; font-size: 15px; }
.game .when { color: var(--muted); }
.first, .empty { margin: 16px 0 0; color: var(--muted); }
.prow { display: grid; grid-template-columns: 56px 1fr; gap: 12px; padding: 22px 0; border-bottom: 1px solid var(--rule); }
.rank { font: 700 44px/1 var(--display); color: var(--gold); }
.prow .name { font-size: clamp(26px, 5vw, 34px); }
.track { margin: 8px 0 6px; }
.prow p { margin: 0; font-size: 15px; color: var(--muted); }
footer { margin-top: 24px; color: var(--muted); font-size: 14px; }
@media (max-width: 560px) {
  .teams { grid-template-columns: 1fr; gap: 4px; }
  .teams .b { text-align: left; }
  .ledger { grid-template-columns: 1fr; gap: 20px; }
}
</style>
</head>
<body>
<main>
  <header>
    <h1>__H1__</h1>
    <p>__SUB__</p>
    <nav aria-label="Pages">__NAV__</nav>
  </header>
  <div id="app"></div>
  <footer>Updated __UPDATED__</footer>
</main>
<script>
const D = __DATA__;
const $ = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};
const pts = n => String(Number(Number(n).toFixed(2)));
const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
const app = document.getElementById("app");
__SCRIPT__
</script>
</body>
</html>
"""

MATCHUPS_JS = """
function game(label, diff, winner, loser, wp, lp, wk, season) {
  const g = $("div", "game");
  g.append(
    $("h4", null, label),
    $("div", "margin", pts(diff)),
    $("p", null, winner + " beat " + loser + " " + pts(wp) + " to " + pts(lp)),
    $("p", "when", "Week " + wk + ", " + season + " season")
  );
  return g;
}

function matchup(m) {
  const A = m.projectedwinningmanager, B = m.projectedlosingmanager;
  const el = $("article", "matchup");

  const teams = $("div", "teams");
  const a = $("div", "name", A);
  a.append($("span", "tag", "Projected winner"));
  teams.append(a, $("div", "vs", "vs"), $("div", "name b", B));
  el.append(teams);

  if (m.season_s == null) {
    el.append($("p", "first", "First meeting. These two have not played each other before."));
    return el;
  }

  const w = m.lifetimewins, l = m.lifetimelosses;
  const series = $("div", "series");
  const bar = $("div", "bar");
  if (w + l === 0) {
    bar.append($("span", "none"));
  } else {
    const sa = $("span", "a"); sa.style.flex = w;
    const sb = $("span", "b"); sb.style.flex = l;
    bar.append(sa, sb);
  }
  const line = w > l ? A + " leads the series " + w + "\\u2013" + l
             : l > w ? B + " leads the series " + l + "\\u2013" + w
             : "Series tied " + w + "\\u2013" + l;
  series.append(bar, $("p", null, line));
  el.append(series);

  const ledger = $("div", "ledger");
  ledger.append(
    game("Closest finish", m.smallestpointdifferential, m.winningmanager_s, m.losingmanager_s,
         m.winningpoints_s, m.losingpoints_s, m.week_s, m.season_s),
    game("Biggest blowout", m.largestpointdifferential, m.winningmanager_l, m.losingmanager_l,
         m.winningpoints_l, m.losingpoints_l, m.week_l, m.season_l)
  );
  el.append(ledger);
  return el;
}

if (D.matchups.length === 0) {
  app.append($("p", "empty", "No matchups yet. This page fills in once the current week's matchups are in the database."));
} else {
  D.matchups.forEach(m => app.append(matchup(m)));
}
"""

PARLAYS_JS = """
const rows = D.parlays;
if (rows.length === 0) {
  app.append($("p", "empty", "No parlays recorded this season yet."));
} else {
  const most = Math.max(1, ...rows.map(r => r.parlay_hits + r.parlay_misses));
  let rank = 0, prev = null;
  rows.forEach((r, i) => {
    if (r.parlay_hits !== prev) { rank = i + 1; prev = r.parlay_hits; }
    const h = r.parlay_hits, m = r.parlay_misses, total = h + m;

    const row = $("article", "prow");
    const who = $("div", "who");
    who.append($("div", "name", r.manager));

    const track = $("div", "track");
    track.style.width = Math.max(8, 100 * total / most) + "%";
    const bar = $("div", "bar");
    if (total === 0) {
      bar.append($("span", "none"));
    } else {
      if (h > 0) { const s = $("span", "a"); s.style.flex = h; bar.append(s); }
      if (m > 0) { const s = $("span", "b"); s.style.flex = m; bar.append(s); }
    }
    track.append(bar);

    const summary = total === 0
      ? "No settled parlays"
      : plural(h, "hit", "hits") + ", " + plural(m, "miss", "misses") + " (" + Math.round(100 * h / total) + "% hit rate)";
    who.append(track, $("p", null, summary));

    row.append($("div", "rank", rank), who);
    app.append(row);
  });
}
"""

PAGES = [("index.html", "Matchups"), ("parlays.html", "Parlays")]


def nav(active):
    return "".join(
        f'<a href="{href}"' + (' aria-current="page"' if href == active else "") + f">{label}</a>"
        for href, label in PAGES
    )


def render(filename, title, desc, sub, script, data, updated):
    payload = json.dumps(data).replace("</", "<\\/")
    html = (
        TEMPLATE.replace("__SCRIPT__", script)
        .replace("__TITLE__", title)
        .replace("__DESC__", desc)
        .replace("__H1__", title)
        .replace("__SUB__", sub)
        .replace("__NAV__", nav(filename))
        .replace("__UPDATED__", updated)
        .replace("__DATA__", payload)
    )
    return html


def whole(n):
    return int(n) if n is not None else None


def main():
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        matchups = fetch_matchups(conn)
        parlays = fetch_parlays(conn)

    season = whole(matchups[0]["season"]) if matchups else None
    week = whole(matchups[0]["week"]) if matchups else None
    updated = datetime.now(timezone.utc).strftime("%b %d, %Y")
    season_label = f"{season} season" if season else "This season"

    out = Path("site")
    out.mkdir(exist_ok=True)

    (out / "index.html").write_text(
        render(
            "index.html",
            f"{LEAGUE} - Week {week}" if week else f"{LEAGUE} - Matchups",
            "Fantasy football matchups with head-to-head history: all-time series, closest finish, and biggest blowout.",
            f"{season_label}: head-to-head history for every matchup",
            MATCHUPS_JS,
            {"matchups": matchups},
            updated,
        ),
        encoding="utf-8",
    )
    (out / "parlays.html").write_text(
        render(
            "parlays.html",
            f"{LEAGUE} - Parlays",
            "Parlay hits and misses for each manager this fantasy football season.",
            f"{season_label}: hits and misses by manager",
            PARLAYS_JS,
            {"parlays": parlays},
            updated,
        ),
        encoding="utf-8",
    )
    print(f"Wrote site/index.html ({len(matchups)} matchups) and site/parlays.html ({len(parlays)} managers)")


if __name__ == "__main__":
    main()
