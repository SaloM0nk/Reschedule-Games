from pathlib import Path

from loguru import logger
from tqdm import tqdm
import typer
import polars as pl
import datetime

from reschedule_games.config import (
    CONSIDER_DAYS, FIRST_DATE_TO_CONSIDER, PROCESSED_DATA_DIR, RAW_DATA_DIR, INTERIM_DATA_DIR, 
    DATA_MY_TT_PATH, DATA_YEAR, DATA_YEAR_STR, DATA_MY_TT,
    OWN_TEAM, OPP_TEAM, LAST_DATE_TO_CONSIDER
)
app = typer.Typer()


def normalize_opponent_teams(opponent_teams) -> list[str]:
    if isinstance(opponent_teams, str):
        return [opponent_teams]
    return opponent_teams


def slugify_team_name(team_name: str) -> str:
    return team_name.replace(" ", "_")


DAY_NAMES_DE = {
    "Monday": "Montag",
    "Tuesday": "Dienstag",
    "Wednesday": "Mittwoch",
    "Thursday": "Donnerstag",
    "Friday": "Freitag",
    "Saturday": "Samstag",
    "Sunday": "Sonntag",
}


def to_german_weekday_name(day_name: str) -> str:
    return DAY_NAMES_DE[day_name]

def ensure_day_format(days: list[str]) -> set[str]:
    """Convert the days of the week to the full English names if they are in German long or short form or in English short form. If the day is already in full English name, it will be kept as is."""
    day_map = {
        "Mo": "Monday",
        "Mon": "Monday",
        "Di": "Tuesday",
        "Tu": "Tuesday",
        "Tue": "Tuesday",
        "Mi": "Wednesday",
        "We": "Wednesday",
        "Wed": "Wednesday",
        "Do": "Thursday",
        "Th": "Thursday",
        "Thu": "Thursday",
        "Fr": "Friday",
        "Fri": "Friday",
        "Sa": "Saturday",
        "Sat": "Saturday",
        "So": "Sunday",
        "Su": "Sunday",
        "Sun": "Sunday",
        "Montag": "Monday",
        "Dienstag": "Tuesday",
        "Mittwoch": "Wednesday",
        "Donnerstag": "Thursday",
        "Freitag": "Friday",
        "Samstag": "Saturday",
        "Sonntag": "Sunday"
    }
    converted_days = []
    for day in days:
        if day in day_map:
            converted_days.append(day_map[day])
        else:
            converted_days.append(day)  # keep as is if not found
    return set(converted_days) # return as a set to avoid duplicates

def preprocess_dataset(
    input_path: Path,
    interim_path: Path,
    
):
    """Preprocess the dataset from the myTT data file and save it as a CSV file in the interim directory."""

    with open(input_path, "r") as f:
        data = f.read()
    # get first line to find element structure from "Datum	Zeit	Halle	Heimmannschaft	Gastmannschaft	Spiele"
    header = data.splitlines()[0]
    idx_date = header.split("\t").index("Datum")
    idx_time = header.split("\t").index("Zeit")
    idx_home = header.split("\t").index("Heimmannschaft")
    idx_guest = header.split("\t").index("Gastmannschaft")
    with open(interim_path, "w") as f:
        f.write("date,time,home_team,guest_team\n")
    prev_date = None
    for line in tqdm(data.splitlines(), desc="Processing lines"):
        if line.strip() == "" or line.startswith("Datum"):
            continue
        fields = line.split("\t")
        date = fields[idx_date]
        # date may be empty as it is the same as the previous line
        if date == "":
            date = prev_date
        else:
            date = date.split(",")[1].strip() # get date from "Mi., 09.09.2026"
            prev_date = date
        time = fields[idx_time]
        home_team = fields[idx_home]
        guest_team = fields[idx_guest]
        # create interim csv file with columns: date, time, home_team, guest_team
        with open(interim_path, "a") as f:
            f.write(f"{date},{time},{home_team},{guest_team}\n")

def get_matches_for_teams(df, own_team, opp_team):
    """Get all matches for the own team and the opponent team from the dataframe."""
    df_match = df.filter(
        ((pl.col("home_team") == own_team) & (pl.col("guest_team") == opp_team))
        | ((pl.col("home_team") == opp_team) & (pl.col("guest_team") == own_team))
    )
    return df_match

def get_matches_for_team(df, team):
    """Get all matches for the team from the dataframe."""
    df_match = df.filter(
        (pl.col("home_team") == team) | (pl.col("guest_team") == team)
    )
    return df_match

def validate_dates(first_date_str: str, last_date_str: str) -> tuple[datetime.date, datetime.date]:
    """Validate the first and last dates to consider for rescheduling. If the first date is in the past, use today as the first date. If the last date is before the first date, raise an error.
    """
    today = datetime.date.today()
    last_date_to_consider = datetime.date.fromisoformat(last_date_str)
    first_date_to_consider = datetime.date.fromisoformat(first_date_str)
    if today > first_date_to_consider:
        logger.warning(f"Today ({today}) is after the first date to consider ({first_date_to_consider}). Using today as the first date to consider.")
        first_date_to_consider = today
    if last_date_to_consider < first_date_to_consider:
        logger.error(f"Last date to consider ({last_date_to_consider}) is before the first date to consider ({first_date_to_consider}). Exiting.")
        raise typer.Exit(code=1)
    return first_date_to_consider, last_date_to_consider

def get_possible_dates(first_date: datetime.date, last_date: datetime.date, consider_days: set[str]) -> list[datetime.date]:
    """Get all possible dates between the first and last dates to consider for rescheduling, considering only the specified days of the week."""
    possible_dates = []
    for i in range((last_date - first_date).days + 1):
        date = first_date + datetime.timedelta(days=i)
        if date.strftime("%A") in consider_days:
            possible_dates.append(date)
    return possible_dates

def find_matches_in_week(df_matches: pl.DataFrame, week_start: datetime.date, week_end: datetime.date) -> list[datetime.date]:
    """Find all matches in the given week (from week_start to week_end) in the dataframe of matches."""
    matches_in_week = df_matches.filter(
        (pl.col("date") >= week_start) & (pl.col("date") <= week_end)
    ).select(pl.col("date")).to_series().to_list()
    return matches_in_week

def date_time_str_ger (date: datetime.date) -> str:
    day = date.strftime("%A")
    day_de = to_german_weekday_name(day)
    return f"{day_de}, {date.strftime('%d.%m.%Y')}"

def find_available_dates_for_opponent(opp_team: str, possible_dates: list[datetime.date], df_own_matches: pl.DataFrame, df_opp_matches: pl.DataFrame, opp_original_day: str, consider_same_days: bool) -> pl.DataFrame:
    # if consider_same_days is True, filter available_dates to only include dates that are on the same day of the week as the original match for this opponent team
    filters = []
    if consider_same_days:
        filters.append(pl.col("date").dt.strftime("%A") == opp_original_day)
    # filter own matches
    df_own_matches_dates = df_own_matches.select(pl.col("date")).to_series().to_list()
    filters.append(~pl.col("date").is_in(df_own_matches_dates))
    # eliminate dates where the opponent team has matches
    df_opp_matches_dates = df_opp_matches.select(pl.col("date")).to_series().to_list()
    filters.append(~pl.col("date").is_in(df_opp_matches_dates))
    # available_dates = available_dates.filter(~pl.col("date").is_in(df_opp_matches_dates))

    available_dates = pl.DataFrame(strict=False, data={
        "date": possible_dates, 
        "own_match": "None", 
        "opp_match": "None"
        }).filter(pl.all_horizontal(filters) if filters else pl.lit(True))

    # add other play days in the same week as notes in own_match and opp_match columns
    for date in available_dates.select(pl.col("date")).to_series().to_list():
        week_start = date - datetime.timedelta(days=date.weekday()) # Monday
        week_end = week_start + datetime.timedelta(days=6) # Sunday

        own_matches_in_week = find_matches_in_week(df_own_matches, week_start, week_end)
        if own_matches_in_week:
            available_dates = available_dates.with_columns(
                pl.when(pl.col("date") == date).then(
                    pl.lit(", ".join([date_time_str_ger(d) for d in own_matches_in_week]))
                ).otherwise(pl.col("own_match")).alias("own_match")
            )
        opp_matches_in_week = find_matches_in_week(df_opp_matches, week_start, week_end)
        if opp_matches_in_week:
            available_dates = available_dates.with_columns(
                pl.when(pl.col("date") == date).then(
                    pl.lit(", ".join([date_time_str_ger(d) for d in opp_matches_in_week]))
                ).otherwise(pl.col("opp_match")).alias("opp_match")
            )
    return available_dates

@app.command()
def main(
    # ---- REPLACE DEFAULT PATHS AS APPROPRIATE ----
    input_path: Path = DATA_MY_TT_PATH,
    interim_path: Path = INTERIM_DATA_DIR / DATA_YEAR_STR / DATA_MY_TT.replace(".txt", ".csv"),
    own_team: str = OWN_TEAM,
    opp_team: list[str] = OPP_TEAM,
    consider_days: list[str] = CONSIDER_DAYS,
    last_date_to_consider_str: str = LAST_DATE_TO_CONSIDER,
    first_date_to_consider_str: str = FIRST_DATE_TO_CONSIDER,
    output_path: Path = None, # will be set to PROCESSED_DATA_DIR / DATA_YEAR_STR / f"{DATA_YEAR_STR}_{own_team}_rescheduling.md" if None
    # ----------------------------------------------
):
    opp_teams = normalize_opponent_teams(opp_team)
    if output_path is None:
        output_path = PROCESSED_DATA_DIR / DATA_YEAR_STR / f"{DATA_YEAR_STR}_{slugify_team_name(own_team)}_rescheduling.md"
    # ensure input and output directories exist
    if not input_path.exists():
        logger.error(f"Input path {input_path} does not exist.")
        raise typer.Exit(code=1)
    if not interim_path.parent.exists():
        logger.info(f"Creating interim directory {interim_path.parent}...")
        interim_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.parent.exists():
        logger.info(f"Creating output directory {output_path.parent}...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

    if not interim_path.exists():
        logger.info(f"Pre-processing dataset from {input_path}...")
        preprocess_dataset(
            input_path=input_path,
            interim_path=interim_path,
        )
        logger.success(f"Interim dataset saved to {interim_path}.")

    # read interim csv file
    df = pl.read_csv(interim_path, schema_overrides={"date": pl.Date})

    # prepare matches for own team and opponent teams
    orig_matches = dict()
    for opp_team in opp_teams:
        orig_matches[opp_team] = get_matches_for_teams(df, own_team, opp_team)
    logger.info(f"Found {sum([orig_matches[opp_team].shape[0] for opp_team in opp_teams])} original matches for {own_team} vs {', '.join(opp_teams)}.")
    df_own_matches = get_matches_for_team(df, own_team)
    logger.info(f"Found {df_own_matches.shape[0]} matches for {own_team}.")
    df_opponent_matches_by_team = {}
    for team in opp_teams:
        team_matches = get_matches_for_team(df, team)
        df_opponent_matches_by_team[team] = team_matches
        logger.info(f"Found {team_matches.shape[0]} matches for {team}.")

    first_date_to_consider, last_date_to_consider = validate_dates(first_date_to_consider_str, last_date_to_consider_str)
    
    # dict with original match days
    opponent_original_days = {}
    for team in opp_teams:
        opponent_original_days[team] = orig_matches[team].select(pl.col("date")).to_series().to_list()[0].strftime("%A")
    consider_same_days = False
    if consider_days == ["SAME"]:
        consider_same_days = True
        # use the weekday(s) of the original matchup(s)
        consider_days = set(opponent_original_days.values())
        logger.info(
            f"Considering only the same day(s) of the week as the original match(es): {', '.join(consider_days)}."
        )
    consider_days = ensure_day_format(consider_days)

    logger.info(f"Looking for rescheduling options after {first_date_to_consider} and before {last_date_to_consider}, considering only the following days of the week: {consider_days}.")
    possible_dates = get_possible_dates(first_date_to_consider, last_date_to_consider, consider_days)
    logger.info(f"Found {len(possible_dates)} possible dates for rescheduling.")
    
    logger.info(f"Checking if {own_team} and {', '.join(opp_teams)} have matches on these dates...")
    available_dates = dict()
    for team in opp_teams:
        available_dates[team] = find_available_dates_for_opponent(team, possible_dates, df_own_matches, df_opponent_matches_by_team[team], opponent_original_days[team], consider_same_days)

    # create a full textual report of the rescheduling.
    with open(output_path, "w") as f:
        f.write(f"# Ausweichtermine für das Match {own_team} vs {', '.join(opp_teams)}:\n")
        f.write(f"Es werden Daten zwischen dem {first_date_to_consider} und {last_date_to_consider} an den folgenden Wochentagen berücksichtig: {', '.join([to_german_weekday_name(day) for day in consider_days])}\n")
        original_match_dates = []
        for opp_team in opp_teams:
            original_match_dates.extend(orig_matches[opp_team].select(pl.col('date')).to_series().to_list())
        original_match_dates_str = ", ".join(
            date.strftime(f"{to_german_weekday_name(date.strftime('%A'))}, %d.%m.%Y")
            for date in original_match_dates
        )
        for team in opp_teams:
            f.write(f"\n## Gegner: {team}\n")
            f.write(f"Originalspieltermin: {original_match_dates_str}\n")
            f.write(f"Verfügbare Ausweichtermine:\n")
            if available_dates[team].shape[0] == 0:
                f.write("Keine verfügbaren Termine gefunden.\n")
            else:
                for row in available_dates[team].iter_rows(named=True):
                    date_str = date_time_str_ger(row["date"])
                    own_match_notes = "wir spielen am" + row["own_match"] if row["own_match"] != "None" else "wir haben Spielfrei"
                    opp_match_notes = f"{team} spielt am " + row["opp_match"] if row["opp_match"] != "None" else f"{team} hat Spielfrei"
                    if "Spielfrei" in own_match_notes and "Spielfrei" in opp_match_notes:
                        f.write(f"{date_str}: Beide Teams haben Spielfrei\n")
                    else:
                        f.write(f"{date_str}: {own_match_notes}, {opp_match_notes}\n")
    logger.info(f"Available dates for rescheduling saved to {output_path}.")

    logger.success("Processing dataset complete.")
    # -----------------------------------------


if __name__ == "__main__":
    app()
