"""Read a bank statement CSV and turn it into clean Charge records."""

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import config

# Different banks name the same column differently.
COLUMN_ALIASES = {
    "date": ["date", "transaction date", "txn date", "posting date", "value date"],
    "merchant": ["merchant", "description", "details", "narration", "payee", "name"],
    "amount": ["amount", "debit", "amount (rs)", "amount (pkr)", "value"],
}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%m/%d/%Y"]


@dataclass
class Charge:
    date: date
    merchant: str          # clean name, e.g. "Netflix"
    raw_merchant: str      # text exactly as it appeared on the statement
    amount: float

    @property
    def cycle(self) -> str:
        return self.date.strftime("%Y-%m")


@dataclass
class Statement:
    path: Path
    cycle: str
    charges: list[Charge]
    warnings: list[str] = field(default_factory=list)


def _find_column(headers: list[str], wanted: str) -> str | None:
    lowered = {h.strip().lower(): h for h in headers}
    for alias in COLUMN_ALIASES[wanted]:
        if alias in lowered:
            return lowered[alias]
    return None


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def parse_amount(text: str) -> float:
    cleaned = re.sub(r"(?i)rs\.?|pkr|,|\s", "", text)
    if not cleaned:
        raise ValueError(f"empty amount {text!r}")
    return abs(float(cleaned))


def normalize_merchant(raw: str) -> str:
    """Map a messy bank description to a stable merchant name.

    Known merchants use the alias table. Anything else is cleaned up: reference
    codes after '*', '#' or long digit runs are dropped and the rest is title-cased.
    """
    lowered = raw.lower()
    for needle, clean in config.MERCHANT_ALIASES.items():
        if needle in lowered:
            return clean
    text = re.split(r"[*#]", raw)[-1] if "*" in raw or "#" in raw else raw
    text = re.sub(r"\b[A-Za-z]*\d[\w-]*\b", " ", text)        # reference codes like P2F4, I04-1234
    text = re.sub(r"\.(com|net|pk|io)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -.")
    return text.title() if text else raw.strip()


def load_statement(path: str | Path) -> Statement:
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        cols = {name: _find_column(headers, name) for name in COLUMN_ALIASES}
        missing = [name for name, col in cols.items() if col is None]
        if missing:
            raise ValueError(
                f"{path.name}: could not find column(s) {missing}; headers are {headers}"
            )

        charges, warnings = [], []
        for line_no, row in enumerate(reader, start=2):
            try:
                raw = (row[cols["merchant"]] or "").strip()
                charges.append(Charge(
                    date=parse_date(row[cols["date"]] or ""),
                    merchant=normalize_merchant(raw),
                    raw_merchant=raw,
                    amount=parse_amount(row[cols["amount"]] or ""),
                ))
            except (ValueError, KeyError) as exc:
                warnings.append(f"line {line_no} skipped: {exc}")

    if not charges:
        raise ValueError(f"{path.name}: no usable rows")
    # A statement covers one month; use the month most rows fall in.
    cycle = Counter(c.cycle for c in charges).most_common(1)[0][0]
    charges.sort(key=lambda c: (c.date, c.merchant))
    return Statement(path=path, cycle=cycle, charges=charges, warnings=warnings)
