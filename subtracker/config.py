"""Settings for the subscription tracker.

All thresholds used by the Python rules live here, so they can be changed
in one place and quoted in the report.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "memory.db"
DEFAULT_OUT_DIR = PROJECT_ROOT / "out"

# --- Rule thresholds -------------------------------------------------------

# Two charges from the same merchant in one cycle are a possible duplicate if
# their amounts differ by at most this fraction and they are this close in time.
DUPLICATE_AMOUNT_TOLERANCE = 0.01
DUPLICATE_MAX_DAYS_APART = 5

# A recurring bill whose day of the month moves by more than this many days
# is flagged as a billing-date change.
DATE_SHIFT_DAYS = 3

# A recurring bill whose amount changes by more than this fraction is flagged.
AMOUNT_CHANGE_TOLERANCE = 0.10

# A merchant seen last cycle at a similar amount counts as recurring.
RECURRING_AMOUNT_TOLERANCE = 0.10

# Words that mark a merchant as a likely subscription the first time we see it.
# The deterministic rules can only recognise merchants on this list; the agent
# mode lets the LLM recognise ones that are missing (for example "Notion").
SUBSCRIPTION_KEYWORDS = [
    "netflix", "spotify", "youtube", "prime", "disney", "hulu", "apple",
    "icloud", "google one", "canva", "adobe", "microsoft", "office 365",
    "chatgpt", "openai", "claude", "gym", "fitness", "internet", "ptcl",
    "nayatel", "stormfiber", "jazz", "zong", "telenor", "ufone", "dropbox",
]

# Raw bank descriptions -> clean merchant names. Matched as substrings of the
# lower-cased description, first match wins.
MERCHANT_ALIASES = {
    "netflix": "Netflix",
    "spotify": "Spotify",
    "ptcl": "PTCL Internet",
    "gold's gym": "Gold's Gym",
    "golds gym": "Gold's Gym",
    "canva": "Canva",
    "foodpanda": "Foodpanda",
    "daraz": "Daraz",
    "youtube": "YouTube Premium",
}

# --- Decisions -------------------------------------------------------------

DECISIONS = ("keep", "cancel", "later", "dispute")
DECISION_HELP = {
    "keep": "keep the subscription",
    "cancel": "cancel it (a cancellation letter is drafted)",
    "later": "decide later (you will be asked again next cycle)",
    "dispute": "the charge looks wrong (a refund request letter is drafted)",
}

# --- LLM -------------------------------------------------------------------

MODEL = os.environ.get("SUBTRACKER_MODEL", "claude-opus-5-5")
CURRENCY = "Rs."
