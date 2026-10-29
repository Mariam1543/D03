"""Deterministic checks. Python decides what is suspicious; the LLM only explains it.

Every rule here is a plain comparison against the thresholds in config.py, so
the same statement always produces the same flags.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from . import config
from .loader import Charge
from .memory import Memory

NEW_SUBSCRIPTION = "NEW_SUBSCRIPTION"
DUPLICATE = "DUPLICATE"
DATE_SHIFT = "DATE_SHIFT"
AMOUNT_CHANGE = "AMOUNT_CHANGE"
CHARGED_AFTER_CANCEL = "CHARGED_AFTER_CANCEL"


@dataclass
class Flag:
    merchant: str
    kind: str
    message: str
    data: dict


@dataclass
class MerchantStatus:
    merchant: str
    charges: list[Charge]
    is_subscription: bool
    reason: str                          # why it counts as a subscription
    previous_decision: dict | None       # latest decision from an earlier cycle
    past_flags: list[dict]               # flags raised in earlier cycles
    flags: list[Flag] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(c.amount for c in self.charges)

    @property
    def needs_decision(self) -> bool:
        """Ask the user only when something is new, wrong, or still undecided."""
        if self.flags:
            return True
        if not self.is_subscription:
            return False
        return self.previous_decision is None or self.previous_decision["decision"] == "later"


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * max(a, b)


def looks_like_subscription(merchant: str, raw: str) -> bool:
    text = f"{merchant} {raw}".lower()
    return any(word in text for word in config.SUBSCRIPTION_KEYWORDS)


def find_duplicates(charges: list[Charge]) -> list[tuple[Charge, Charge]]:
    pairs = []
    for i, first in enumerate(charges):
        for second in charges[i + 1:]:
            if (_close(first.amount, second.amount, config.DUPLICATE_AMOUNT_TOLERANCE)
                    and abs((second.date - first.date).days) <= config.DUPLICATE_MAX_DAYS_APART):
                pairs.append((first, second))
    return pairs


def analyse_cycle(memory: Memory, cycle: str) -> list[MerchantStatus]:
    by_merchant: dict[str, list[Charge]] = defaultdict(list)
    for charge in memory.charges(cycle):
        by_merchant[charge.merchant].append(charge)

    statuses = []
    for merchant, charges in sorted(by_merchant.items()):
        previous = memory.previous_charges(merchant, before_cycle=cycle)
        decision = memory.latest_decision(merchant, before_cycle=cycle)
        current, last = charges[0], previous[0] if previous else None

        if decision:
            reason = f"you decided '{decision['decision']}' in {decision['cycle']}"
        elif last and _close(current.amount, last.amount, config.RECURRING_AMOUNT_TOLERANCE):
            reason = f"same amount as in {last.cycle}"
        elif looks_like_subscription(merchant, current.raw_merchant):
            reason = "name matches a known subscription service"
        else:
            reason = ""

        status = MerchantStatus(
            merchant=merchant, charges=charges, is_subscription=bool(reason), reason=reason,
            previous_decision=decision,
            past_flags=memory.flags(merchant=merchant, before_cycle=cycle),
        )
        status.flags = _flags_for(status, last)
        statuses.append(status)
    return statuses


def _flags_for(s: MerchantStatus, last: Charge | None) -> list[Flag]:
    flags = []
    current = s.charges[0]
    money = lambda x: f"{config.CURRENCY} {x:,.0f}"

    for first, second in find_duplicates(s.charges):
        flags.append(Flag(s.merchant, DUPLICATE,
            f"Charged {money(first.amount)} twice: on {first.date} and {second.date}.",
            {"dates": [first.date.isoformat(), second.date.isoformat()],
             "amount": first.amount,
             "seen_before_in": sorted({f["cycle"] for f in s.past_flags if f["kind"] == DUPLICATE})}))

    if not s.is_subscription:
        return flags

    if s.previous_decision and s.previous_decision["decision"] == "cancel":
        flags.append(Flag(s.merchant, CHARGED_AFTER_CANCEL,
            f"You chose to cancel in {s.previous_decision['cycle']}, "
            f"but were charged {money(current.amount)} on {current.date}.",
            {"cancelled_in": s.previous_decision["cycle"], "amount": current.amount,
             "date": current.date.isoformat()}))

    if last is None:
        if s.previous_decision is None:
            flags.append(Flag(s.merchant, NEW_SUBSCRIPTION,
                f"First time we see this subscription: {money(current.amount)} on {current.date}.",
                {"amount": current.amount, "date": current.date.isoformat()}))
        return flags

    shift = current.date.day - last.date.day
    if abs(shift) > config.DATE_SHIFT_DAYS:
        flags.append(Flag(s.merchant, DATE_SHIFT,
            f"Billing day moved from day {last.date.day} to day {current.date.day} of the month.",
            {"previous_date": last.date.isoformat(), "date": current.date.isoformat(),
             "days_moved": shift}))

    if not _close(current.amount, last.amount, config.AMOUNT_CHANGE_TOLERANCE):
        change = (current.amount - last.amount) / last.amount
        flags.append(Flag(s.merchant, AMOUNT_CHANGE,
            f"Amount changed from {money(last.amount)} to {money(current.amount)} ({change:+.0%}).",
            {"previous_amount": last.amount, "amount": current.amount,
             "change_pct": round(change * 100, 1)}))
    return flags
