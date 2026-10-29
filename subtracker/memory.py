"""SQLite memory: the agent's diary of past charges, flags and decisions."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .loader import Charge, Statement, parse_date

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle        TEXT PRIMARY KEY,          -- 'YYYY-MM'
    source_file  TEXT NOT NULL,
    imported_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS charges (
    id           INTEGER PRIMARY KEY,
    cycle        TEXT NOT NULL REFERENCES cycles(cycle),
    date         TEXT NOT NULL,
    merchant     TEXT NOT NULL,
    raw_merchant TEXT NOT NULL,
    amount       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS flags (
    id           INTEGER PRIMARY KEY,
    cycle        TEXT NOT NULL,
    merchant     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    message      TEXT NOT NULL,              -- what the Python rule found
    data         TEXT NOT NULL,              -- rule details as JSON
    explanation  TEXT                        -- plain-language text from the LLM
);
CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY,
    cycle        TEXT NOT NULL,
    merchant     TEXT NOT NULL,
    decision     TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    decided_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS charges_merchant ON charges(merchant, cycle);
CREATE INDEX IF NOT EXISTS decisions_merchant ON decisions(merchant, cycle);
"""


class Memory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- writing -----------------------------------------------------------

    def import_statement(self, stmt: Statement) -> None:
        """Store a statement. Re-importing a cycle replaces everything stored for it."""
        with self.conn:
            for table in ("charges", "flags", "decisions"):
                self.conn.execute(f"DELETE FROM {table} WHERE cycle = ?", (stmt.cycle,))
            self.conn.execute(
                "INSERT OR REPLACE INTO cycles VALUES (?, ?, ?)",
                (stmt.cycle, stmt.path.name, _now()),
            )
            self.conn.executemany(
                "INSERT INTO charges (cycle, date, merchant, raw_merchant, amount) VALUES (?, ?, ?, ?, ?)",
                [(stmt.cycle, c.date.isoformat(), c.merchant, c.raw_merchant, c.amount)
                 for c in stmt.charges],
            )

    def save_flag(self, cycle: str, merchant: str, kind: str, message: str, data: dict) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO flags (cycle, merchant, kind, message, data) VALUES (?, ?, ?, ?, ?)",
                (cycle, merchant, kind, message, json.dumps(data)),
            )
        return cur.lastrowid

    def clear_flags(self, cycle: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM flags WHERE cycle = ?", (cycle,))

    def set_explanation(self, flag_id: int, text: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE flags SET explanation = ? WHERE id = ?", (text, flag_id))

    def save_decision(self, cycle: str, merchant: str, decision: str, note: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO decisions (cycle, merchant, decision, note, decided_at) VALUES (?, ?, ?, ?, ?)",
                (cycle, merchant, decision, note, _now()),
            )

    # --- reading -----------------------------------------------------------

    def cycles(self) -> list[str]:
        return [r["cycle"] for r in self.conn.execute("SELECT cycle FROM cycles ORDER BY cycle")]

    def charges(self, cycle: str) -> list[Charge]:
        rows = self.conn.execute(
            "SELECT * FROM charges WHERE cycle = ? ORDER BY date, merchant", (cycle,)
        )
        return [_charge(r) for r in rows]

    def previous_charges(self, merchant: str, before_cycle: str) -> list[Charge]:
        """Charges for `merchant` in the latest earlier cycle where it appeared."""
        row = self.conn.execute(
            "SELECT MAX(cycle) AS c FROM charges WHERE merchant = ? AND cycle < ?",
            (merchant, before_cycle),
        ).fetchone()
        if row["c"] is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM charges WHERE merchant = ? AND cycle = ? ORDER BY date",
            (merchant, row["c"]),
        )
        return [_charge(r) for r in rows]

    def latest_decision(self, merchant: str, before_cycle: str | None = None) -> dict | None:
        sql = "SELECT * FROM decisions WHERE merchant = ?"
        args: list = [merchant]
        if before_cycle:
            sql += " AND cycle < ?"
            args.append(before_cycle)
        row = self.conn.execute(sql + " ORDER BY cycle DESC, id DESC LIMIT 1", args).fetchone()
        return dict(row) if row else None

    def flags(self, cycle: str | None = None, merchant: str | None = None,
              before_cycle: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM flags WHERE 1=1", []
        for column, op, value in (("cycle", "=", cycle), ("merchant", "=", merchant),
                                  ("cycle", "<", before_cycle)):
            if value is not None:
                sql += f" AND {column} {op} ?"
                args.append(value)
        rows = self.conn.execute(sql + " ORDER BY cycle, id", args)
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def decisions(self, cycle: str | None = None) -> list[dict]:
        if cycle:
            rows = self.conn.execute("SELECT * FROM decisions WHERE cycle = ? ORDER BY id", (cycle,))
        else:
            rows = self.conn.execute("SELECT * FROM decisions ORDER BY cycle, id")
        return [dict(r) for r in rows]

    def history(self, merchant: str) -> dict:
        """Everything remembered about one merchant, oldest first."""
        charges = self.conn.execute(
            "SELECT cycle, date, amount, raw_merchant FROM charges WHERE merchant = ? ORDER BY date",
            (merchant,),
        )
        decisions = self.conn.execute(
            "SELECT cycle, decision, note FROM decisions WHERE merchant = ? ORDER BY cycle, id",
            (merchant,),
        )
        return {
            "merchant": merchant,
            "charges": [dict(r) for r in charges],
            "flags": [{"cycle": f["cycle"], "kind": f["kind"], "message": f["message"]}
                      for f in self.flags(merchant=merchant)],
            "decisions": [dict(r) for r in decisions],
        }

    def merchants(self) -> list[str]:
        return [r["merchant"] for r in
                self.conn.execute("SELECT DISTINCT merchant FROM charges ORDER BY merchant")]

    def spending(self, cycle: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT merchant, COUNT(*) AS charges, SUM(amount) AS total FROM charges "
            "WHERE cycle = ? GROUP BY merchant ORDER BY total DESC",
            (cycle,),
        )
        return [dict(r) for r in rows]


def _charge(row: sqlite3.Row) -> Charge:
    return Charge(date=parse_date(row["date"]), merchant=row["merchant"],
                  raw_merchant=row["raw_merchant"], amount=row["amount"])


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
