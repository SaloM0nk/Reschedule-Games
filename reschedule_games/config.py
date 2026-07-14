from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Load environment variables from .env file if it exists
load_dotenv()

# Paths
PROJ_ROOT = Path(__file__).resolve().parents[1]
logger.info(f"PROJ_ROOT path is: {PROJ_ROOT}")

DATA_DIR = PROJ_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EXTERNAL_DATA_DIR = DATA_DIR / "external"

MODELS_DIR = PROJ_ROOT / "models"

REPORTS_DIR = PROJ_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

DATA_YEAR = 2026  # year of the data to use
DATA_YEAR_STR = str(DATA_YEAR) 
DATA_MY_TT = "260714_mytt_excerpt.txt" # myTT data file name
DATA_MY_TT_PATH = RAW_DATA_DIR / DATA_YEAR_STR / DATA_MY_TT # myTT data file path

OWN_TEAM = "TuS Berne"
OPP_TEAM = "TTG Hamburg-Nord III" # "SC Condor Hamburg" # "SC Poppenbüttel V" 
CONSIDER_DAYS = ["SAME"] # days of the week to consider for rescheduling, e.g., one of [Mo, Di, Mi, Do, Fr, Sa, So]. "SAME" can be used to indicate that the same day of the week as the original match should be considered.
FIRST_DATE_TO_CONSIDER = "2026-09-01" # first date to consider for rescheduling, in YYYY-MM-DD format
LAST_DATE_TO_CONSIDER = "2026-12-15" # last date to consider for rescheduling, in YYYY-MM-DD format

# If tqdm is installed, configure loguru with tqdm.write
# https://github.com/Delgan/loguru/issues/135
try:
    from tqdm import tqdm

    logger.remove(0)
    logger.add(lambda msg: tqdm.write(msg, end=""), colorize=True)
except ModuleNotFoundError:
    pass
