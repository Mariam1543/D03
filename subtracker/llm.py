"""The LLM's two jobs in the workflow: explain flags and draft letters.

The LLM never decides whether something is a flag; it only receives flags the
Python rules already raised. If no API credentials are available (or a call
fails), template text is used instead so the project still runs offline.
"""

import json

from . import config
from . import rules

FALLBACK_BETA = "server-side-fallback-2026-07-01"

EXPLAIN_SYSTEM = """You help a person review their monthly bank statement for subscriptions.
Python rules have already flagged some charges. For each flag, explain in 2-3 short,
plain sentences why it was flagged and what the person could check. Mention a harmless
explanation when one is plausible (a company can change its billing date, a price can rise);
a flag is a reason to look, not proof of fraud. Do not change or second-guess the flag
itself, and do not invent facts that are not in the data. Amounts are in {currency}.
Write in {language}."""

LETTER_SYSTEM = """You draft short, polite letters a customer can send to a company.
Use only the facts given. Leave placeholders in square brackets for anything you do not
know (name, account number, email). Output only the letter text, no commentary.
Write in {language}."""

EXPLANATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "flag_id": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["flag_id", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["explanations"],
    "additionalProperties": False,
}


def make_client(offline: bool = False):
    """Return an Anthropic client, or None to run with templates only."""
    if offline:
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception as exc:  # SDK missing or no credentials configured
        print(f"[llm] running offline ({exc.__class__.__name__}); using template text")
        return None


def create_message(client, **kwargs):
    """messages.create with refusal fallback enabled: if the model declines, the API
    retries on a fallback model inside the same call."""
    return client.beta.messages.create(
        model=config.MODEL, betas=[FALLBACK_BETA], fallbacks="default", **kwargs
    )


def response_text(response) -> str | None:
    if response.stop_reason == "refusal":
        return None
    return "".join(b.text for b in response.content if b.type == "text").strip() or None


class Writer:
    """Explains flags and drafts letters, with Claude or with templates."""

    def __init__(self, client=None, language: str = "English"):
        self.client = client
        self.language = language

    @property
    def online(self) -> bool:
        return self.client is not None

    def _call(self, **kwargs):
        try:
            return response_text(create_message(self.client, **kwargs))
        except Exception as exc:
            print(f"[llm] call failed ({exc.__class__.__name__}: {exc}); using template text")
            self.client = None
            return None

    def explain(self, flags: list[dict], memory) -> dict[int, str]:
        """flags: rows from Memory.flags(). Returns {flag_id: explanation}."""
        if not flags:
            return {}
        result = {f["id"]: template_explanation(f) for f in flags}
        if not self.online:
            return result
        payload = [
            {"flag_id": f["id"], "merchant": f["merchant"], "kind": f["kind"],
             "finding": f["message"], "details": f["data"],
             "history": memory.history(f["merchant"])}
            for f in flags
        ]
        text = self._call(
            max_tokens=8000,
            system=EXPLAIN_SYSTEM.format(currency=config.CURRENCY, language=self.language),
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": EXPLANATIONS_SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(payload, default=str, indent=1)}],
        )
        if text:
            for item in json.loads(text)["explanations"]:
                if item["flag_id"] in result:
                    result[item["flag_id"]] = item["explanation"]
        return result

    def letter(self, kind: str, merchant: str, facts: str) -> str:
        """kind is 'cancel' or 'dispute'."""
        if self.online:
            goal = ("cancel the subscription and stop future charges" if kind == "cancel"
                    else "refund a charge that looks wrong")
            text = self._call(
                max_tokens=4000,
                system=LETTER_SYSTEM.format(language=self.language),
                output_config={"effort": "low"},
                messages=[{"role": "user", "content":
                           f"Company: {merchant}\nGoal: {goal}\nFacts:\n{facts}"}],
            )
            if text:
                return text
        return template_letter(kind, merchant, facts)


# --- templates used when the LLM is not available ----------------------------

def template_explanation(flag: dict) -> str:
    d, m, money = flag["data"], flag["merchant"], lambda x: f"{config.CURRENCY} {x:,.0f}"
    kind = flag["kind"]
    if kind == rules.DUPLICATE:
        text = (f"{m} took {money(d['amount'])} twice within a few days ({' and '.join(d['dates'])}). "
                "This is often a billing error or a retried payment, but it can also be two "
                "separate accounts. Check whether both payments went through and ask for a refund if so.")
        if d.get("seen_before_in"):
            text += f" The same thing happened in {', '.join(d['seen_before_in'])}."
        return text
    if kind == rules.DATE_SHIFT:
        return (f"{m} usually bills on day {int(d['previous_date'][-2:])} of the month, this "
                f"time on day {int(d['date'][-2:])}. Companies sometimes change billing cycles, so this may be "
                "harmless; check that you were not billed twice for the same period.")
    if kind == rules.AMOUNT_CHANGE:
        return (f"{m} charged {money(d['amount'])} instead of {money(d['previous_amount'])} "
                f"({d['change_pct']:+.1f}%). This can be a price increase, a plan change or "
                "extra tax; check your plan or the company's price notice.")
    if kind == rules.CHARGED_AFTER_CANCEL:
        return (f"You decided to cancel {m} in {d['cancelled_in']}, but it charged you again on "
                f"{d['date']}. The cancellation may not have been sent or processed yet. "
                "Contact the company and ask for this charge to be refunded.")
    if kind == rules.NEW_SUBSCRIPTION:
        return (f"{m} looks like a new subscription ({money(d['amount'])} on {d['date']}). "
                "Decide whether you want to keep paying for it every month.")
    return flag["message"]


def template_letter(kind: str, merchant: str, facts: str) -> str:
    if kind == "cancel":
        subject, body = (
            f"Subject: Cancellation of my {merchant} subscription",
            f"I would like to cancel my {merchant} subscription with immediate effect and "
            "stop all future charges to my card. Please confirm the cancellation in writing.",
        )
    else:
        subject, body = (
            f"Subject: Refund request for a charge from {merchant}",
            f"I have found a charge from {merchant} on my statement that I believe is incorrect. "
            "Please review it and refund the amount to my card.",
        )
    return (f"{subject}\n\nDear {merchant} Customer Support,\n\n{body}\n\n"
            f"Details:\n{facts}\n\n"
            "Account email: [your email]\nCard: [last 4 digits]\n\n"
            "Thank you,\n[Your name]\n")
