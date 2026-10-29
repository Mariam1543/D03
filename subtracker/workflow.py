"""Fixed pipeline: load -> remember -> check -> explain -> ask -> save -> report.

This is the "workflow" mode: the steps always run in the same order. The
agent mode (agent.py) uses the same building blocks as tools and lets the LLM
choose the order.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config
from .llm import Writer
from .loader import load_statement
from .memory import Memory
from .report import save_letter, write_report
from .rules import NEW_SUBSCRIPTION, MerchantStatus, analyse_cycle

# ask(status, explanations) -> (decision, note)
AskFn = Callable[[MerchantStatus, list[str]], tuple[str, str]]


@dataclass
class CycleResult:
    cycle: str
    statuses: list[MerchantStatus]
    decisions: dict[str, str] = field(default_factory=dict)
    letters: list[Path] = field(default_factory=list)
    reports: list[Path] = field(default_factory=list)


def money(x: float) -> str:
    return f"{config.CURRENCY} {x:,.0f}"


def describe(status: MerchantStatus, explanations: list[str]) -> str:
    lines = [f"\n== {status.merchant}: {len(status.charges)} charge(s), {money(status.total)}"]
    if status.reason:
        lines.append(f"   subscription because: {status.reason}")
    for past in notable_past_flags(status):
        lines.append(f"   memory: {past['kind']} in {past['cycle']} - {past['message']}")
    for flag, text in zip(status.flags, explanations):
        lines.append(f"   FLAG {flag.kind}: {flag.message}")
        lines.append(f"     why: {text}")
    return "\n".join(lines)


def notable_past_flags(status: MerchantStatus) -> list[dict]:
    """Earlier flags worth repeating (a past NEW_SUBSCRIPTION is not news)."""
    return [f for f in status.past_flags if f["kind"] != NEW_SUBSCRIPTION]


def interactive_ask(status: MerchantStatus, explanations: list[str]) -> tuple[str, str]:
    print(describe(status, explanations))
    options = "/".join(f"[{d[0]}]{d[1:]}" for d in config.DECISIONS)
    while True:
        answer = input(f"   Decision for {status.merchant}? {options}: ").strip().lower()
        for decision in config.DECISIONS:
            if answer and decision.startswith(answer):
                note = input("   Note (optional): ").strip()
                return decision, note
        print("   Please type k, c, l or d.")


def scripted_ask(script: dict[str, dict[str, str]]) -> AskFn:
    """Answers from a dict {cycle: {merchant: decision}}; anything missing is 'later'."""
    def ask(status: MerchantStatus, explanations: list[str]) -> tuple[str, str]:
        print(describe(status, explanations))
        decision = script.get(status.charges[0].cycle, {}).get(status.merchant, "later")
        print(f"   Decision for {status.merchant}: {decision} (scripted)")
        return decision, "scripted demo answer"
    return ask


def letter_facts(status: MerchantStatus) -> str:
    lines = [f"- {c.date}: {money(c.amount)} (statement text: {c.raw_merchant})"
             for c in status.charges]
    lines += [f"- {f.message}" for f in status.flags]
    return "\n".join(lines)


def run_cycle(statement_path: str | Path, memory: Memory, writer: Writer,
              ask: AskFn, out_dir: Path) -> CycleResult:
    stmt = load_statement(statement_path)
    for warning in stmt.warnings:
        print(f"[load] {warning}")
    memory.import_statement(stmt)
    print(f"\n### Cycle {stmt.cycle}: {len(stmt.charges)} charges from {stmt.path.name}")

    statuses = analyse_cycle(memory, stmt.cycle)
    flag_ids: dict[str, list[int]] = {}
    for status in statuses:
        flag_ids[status.merchant] = [
            memory.save_flag(stmt.cycle, f.merchant, f.kind, f.message, f.data)
            for f in status.flags
        ]

    explanations = writer.explain(memory.flags(cycle=stmt.cycle), memory)
    for flag_id, text in explanations.items():
        memory.set_explanation(flag_id, text)

    result = CycleResult(cycle=stmt.cycle, statuses=statuses)
    others = []  # charges not treated as subscriptions
    for status in statuses:
        if not status.needs_decision:
            if status.previous_decision:
                earlier = "".join(f"; earlier {f['kind']} in {f['cycle']}"
                                  for f in notable_past_flags(status))
                print(f"\n== {status.merchant}: {money(status.total)}, no new issues - your last "
                      f"decision was '{status.previous_decision['decision']}' "
                      f"({status.previous_decision['cycle']}){earlier}")
            else:
                others.append(f"{status.merchant} ({money(status.total)})")
            continue
        texts = [explanations[i] for i in flag_ids[status.merchant]]
        decision, note = ask(status, texts)
        memory.save_decision(stmt.cycle, status.merchant, decision, note)
        result.decisions[status.merchant] = decision
        if decision in ("cancel", "dispute"):
            text = writer.letter(decision, status.merchant, letter_facts(status))
            path = save_letter(out_dir, stmt.cycle, decision, status.merchant, text)
            result.letters.append(path)
            print(f"   letter draft saved (not sent): {path}")

    if others:
        print(f"\nOther charges (not treated as subscriptions): {', '.join(others)}")
    result.reports = write_report(memory, stmt.cycle, out_dir)
    print(f"\nReport: {', '.join(str(p) for p in result.reports)}")
    return result
