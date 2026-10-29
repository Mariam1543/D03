"""Write the cycle report (CSV + Excel) and letter drafts to disk."""

import csv
import re
from pathlib import Path

from .memory import Memory
from .rules import NEW_SUBSCRIPTION, analyse_cycle

COLUMNS = ["cycle", "date", "merchant", "statement_text", "amount", "subscription",
           "flags", "decision", "explanation", "memory_note"]


def build_rows(memory: Memory, cycle: str) -> list[dict]:
    decisions_now = {d["merchant"]: d for d in memory.decisions(cycle)}
    rows = []
    for status in analyse_cycle(memory, cycle):
        flags = memory.flags(cycle=cycle, merchant=status.merchant)
        decision = decisions_now.get(status.merchant)
        if decision:
            decision_text = decision["decision"]
        elif status.previous_decision:
            decision_text = (f"{status.previous_decision['decision']} "
                             f"(from {status.previous_decision['cycle']})")
        else:
            decision_text = ""

        notes = []
        if status.previous_decision:
            notes.append(f"earlier decision: {status.previous_decision['decision']} "
                         f"in {status.previous_decision['cycle']}")
        for past in status.past_flags:
            if past["kind"] != NEW_SUBSCRIPTION:
                notes.append(f"{past['kind']} in {past['cycle']}")

        for charge in status.charges:
            rows.append({
                "cycle": cycle,
                "date": charge.date.isoformat(),
                "merchant": status.merchant,
                "statement_text": charge.raw_merchant,
                "amount": charge.amount,
                "subscription": "yes" if status.is_subscription else "no",
                "flags": ", ".join(f["kind"] for f in flags),
                "decision": decision_text,
                "explanation": " | ".join(f["explanation"] or f["message"] for f in flags),
                "memory_note": "; ".join(notes),
            })
    return rows


def write_report(memory: Memory, cycle: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = build_rows(memory, cycle)

    csv_path = out_dir / f"report_{cycle}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    paths = [csv_path]

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        return paths  # Excel is optional; the CSV has the same data

    wb = Workbook()
    sheets = {
        "Charges": (COLUMNS, [[r[c] for c in COLUMNS] for r in rows]),
        "Flags": (["cycle", "merchant", "kind", "finding", "explanation"],
                  [[f["cycle"], f["merchant"], f["kind"], f["message"], f["explanation"] or ""]
                   for f in memory.flags(cycle=cycle)]),
        "Decisions": (["cycle", "merchant", "decision", "note", "decided_at"],
                      [[d["cycle"], d["merchant"], d["decision"], d["note"], d["decided_at"]]
                       for d in memory.decisions()]),
        "Spending": (["merchant", "charges", "total"],
                     [[s["merchant"], s["charges"], s["total"]] for s in memory.spending(cycle)]),
    }
    wb.remove(wb.active)
    for title, (header, data) in sheets.items():
        ws = wb.create_sheet(title)
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in data:
            ws.append(row)
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 80)
    xlsx_path = out_dir / f"report_{cycle}.xlsx"
    wb.save(xlsx_path)
    paths.append(xlsx_path)
    return paths


def save_letter(out_dir: Path, cycle: str, kind: str, merchant: str, text: str) -> Path:
    """Save a letter draft. Letters are never sent by this program."""
    folder = out_dir / "letters"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", merchant.lower()).strip("_")
    path = folder / f"{cycle}_{kind}_{slug}.txt"
    path.write_text(text, encoding="utf-8")
    return path
