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

@app.command()
def main(
    # ---- REPLACE DEFAULT PATHS AS APPROPRIATE ----
    input_path: Path = DATA_MY_TT_PATH,
    interim_path: Path = INTERIM_DATA_DIR / DATA_YEAR_STR / DATA_MY_TT.replace(".txt", ".csv"),
    own_team: str = OWN_TEAM,
    opp_team: str = OPP_TEAM,
    consider_days: list[str] = CONSIDER_DAYS,
    last_date_to_consider_str: str = LAST_DATE_TO_CONSIDER,
    first_date_to_consider_str: str = FIRST_DATE_TO_CONSIDER,
    output_path: Path = None, # will be set to PROCESSED_DATA_DIR / DATA_YEAR_STR / f"{own_team.replace(' ', '_')}_vs_{opp_team.replace(' ', '_')}_available_dates.csv" if None
    # ----------------------------------------------
):
    if output_path is None:
        output_path = PROCESSED_DATA_DIR / DATA_YEAR_STR / f"{own_team.replace(' ', '_')}_vs_{opp_team.replace(' ', '_')}_available_dates.csv"
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

    logger.info(f"Pre-processing dataset from {input_path}...")
    if not interim_path.exists():
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
        logger.success(f"Interim dataset saved to {interim_path}.")

    # read interim csv file
    # ensure "date" is parsed as a date from "09.09.2026"
    df = pl.read_csv(interim_path, schema_overrides={"date": pl.Date})
    # filter for own_team and opp_team
    df_match = df.filter(
        ((pl.col("home_team") == own_team) & (pl.col("guest_team") == opp_team))
        | ((pl.col("home_team") == opp_team) & (pl.col("guest_team") == own_team))
    )
    logger.info(f"Found {df_match.shape[0]} matches between {own_team} and {opp_team}.")
    df_own_matches = df.filter(
        (pl.col("home_team") == own_team) | (pl.col("guest_team") == own_team)
    )
    logger.info(f"Found {df_own_matches.shape[0]} matches for {own_team}.")
    df_opp_matches = df.filter(
        (pl.col("home_team") == opp_team) | (pl.col("guest_team") == opp_team)
    )
    logger.info(f"Found {df_opp_matches.shape[0]} matches for {opp_team}.")
    today = datetime.date.today()
    last_date_to_consider = datetime.date.fromisoformat(last_date_to_consider_str)
    first_date_to_consider = datetime.date.fromisoformat(first_date_to_consider_str)
    if today > first_date_to_consider:
        logger.warning(f"Today ({today}) is after the first date to consider ({first_date_to_consider}). Using today as the first date to consider.")
        first_date_to_consider = today
    if last_date_to_consider < first_date_to_consider:
        logger.error(f"Last date to consider ({last_date_to_consider}) is before the first date to consider ({first_date_to_consider}). Exiting.")
        raise typer.Exit(code=1)
    if consider_days == ["SAME"]:
        # get the day of the week of the original match
        original_match_date = df_match.select(pl.col("date")).to_series().to_list()[0]
        original_match_day = original_match_date.strftime("%A") # e.g., "Wednesday"
        consider_days = [original_match_day]
        logger.info(f"Considering only the same day of the week as the original match: {original_match_day}.")
    consider_days = ensure_day_format(consider_days)
    logger.info(f"Looking for rescheduling options after {first_date_to_consider} and before {last_date_to_consider}, considering only the following days of the week: {consider_days}.")
    # get all dates between first_date_to_consider and last_date_to_consider that are in consider_days
    possible_dates = []
    for i in range((last_date_to_consider - first_date_to_consider).days + 1):
        date = first_date_to_consider + datetime.timedelta(days=i)
        if date.strftime("%A") in consider_days:
            possible_dates.append(date)
    logger.info(f"Found {len(possible_dates)} possible dates for rescheduling.")
    logger.info(f"Checking if {own_team} and {opp_team} have matches on these dates...")
    # check if own_team and opp_team have matches on these dates
    df_own_matches_dates = df_own_matches.select(pl.col("date")).to_series().to_list()
    df_opp_matches_dates = df_opp_matches.select(pl.col("date")).to_series().to_list()
    available_dates = pl.DataFrame(strict=False, data={"date": possible_dates, "own_match": "None", "opp_match": "None"}).filter(
        ~pl.col("date").is_in(df_own_matches_dates) & ~pl.col("date").is_in(df_opp_matches_dates)
    )
    logger.info(f"Found {len(available_dates)} available dates for rescheduling.")
    # create a dataframe with the available dates 
    # for both teams, check if they have a match in the same week as the available dates, if so, store them in the "own_match" and "opp_match" columns
    for date in available_dates.select(pl.col("date")).to_series().to_list():
        week_start = date - datetime.timedelta(days=date.weekday()) # Monday
        week_end = week_start + datetime.timedelta(days=6) # Sunday
        # check for own_team and opp_team matches in the same week, there may be multiple matches in the same week, so we will store them as a list
        # store the date as a string in format "DAY, DD.MM.YYYY" in the "own_match" and "opp_match" columns
        own_matches_in_week = df_own_matches.filter(
            (pl.col("date") >= week_start) & (pl.col("date") <= week_end)
        ).select(pl.col("date")).to_series().to_list()
        opp_matches_in_week = df_opp_matches.filter(
            (pl.col("date") >= week_start) & (pl.col("date") <= week_end)
        ).select(pl.col("date")).to_series().to_list()
        if own_matches_in_week:
            available_dates = available_dates.with_columns(
                pl.when(pl.col("date") == date).then(
                    pl.lit(", ".join([d.strftime("%A, %d.%m.%Y") for d in own_matches_in_week]))
                ).otherwise(pl.col("own_match")).alias("own_match")
            )
        if opp_matches_in_week:
            available_dates = available_dates.with_columns(
                pl.when(pl.col("date") == date).then(
                    pl.lit(", ".join([d.strftime("%A, %d.%m.%Y") for d in opp_matches_in_week]))
                ).otherwise(pl.col("opp_match")).alias("opp_match")
            )
    # save the available dates to output_path
    available_dates.write_csv(output_path)
    logger.info(f"Available dates for rescheduling saved to {output_path}.")

    logger.success("Processing dataset complete.")
    # -----------------------------------------


if __name__ == "__main__":
    app()
