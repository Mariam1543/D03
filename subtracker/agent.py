"""Agent mode: Claude gets the Python building blocks as tools and decides the steps.

Differences from the fixed workflow (workflow.py):
- Claude chooses which tool to call next (e.g. it looks up history only when
  a flag needs context, and skips questions when nothing changed).
- Claude can notice subscriptions the keyword rules miss (an unknown merchant
  name) and ask the user about them.
- After the cycle, the user can keep asking questions ("why is my spending up?")
  and Claude answers by calling the same tools.

Guard rails kept in code, not in the prompt alone:
- Flags come only from rules.py; Claude cannot create or delete them.
- save_decision is refused unless the decision quotes an answer the user
  actually typed through ask_user.
- There is no tool that sends anything; letters are only saved as drafts.
"""

import json
from pathlib import Path

from . import config
from .llm import create_message
from .loader import load_statement
from .memory import Memory
from .report import save_letter, write_report
from .rules import analyse_cycle

SYSTEM = """You are a personal subscription-tracking agent. Each month the user gives you a
bank statement CSV. Your job:
1. Load the statement, then run the rule checks for its cycle.
2. Review the result. Flags come from deterministic Python rules; treat them as facts,
   never invent or dismiss one. You may additionally point out charges the rules did not
   mark as subscriptions but that look like one to you (e.g. an unfamiliar software
   company), and ask the user about them.
3. For every merchant that needs a decision, explain the situation in plain words
   (use get_history when earlier months matter) and save a short explanation for each
   flag with save_explanation. Then ask the user with ask_user. Options are: keep, cancel,
   later, dispute. Ask one merchant at a time.
4. Save each answer with save_decision. Never decide for the user.
5. For 'cancel' write a cancellation letter, for 'dispute' a refund request letter, and
   store it with save_letter. Letters are drafts; you cannot send anything, so never say
   a letter was sent.
6. Write the report with write_report and finish with a short summary.
Merchants with no flags and an earlier 'keep' decision need no question; just mention them.
Amounts are in {currency}. Talk to the user in {language}; keep messages short."""


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


STR = {"type": "string"}
TOOLS = [
    _tool("load_statement", "Load a bank statement CSV into memory. Returns its cycle (YYYY-MM) "
          "and all charges. Re-loading a cycle replaces what was stored for it.",
          {"path": STR}),
    _tool("run_checks", "Run the deterministic rules for a cycle and store the flags. Returns, "
          "per merchant: charges, whether it counts as a subscription and why, the earlier "
          "decision, flags from earlier cycles, new flags (with ids) and needs_decision.",
          {"cycle": STR}),
    _tool("get_history", "All remembered charges, flags and decisions for one merchant.",
          {"merchant": STR}),
    _tool("spending_summary", "Totals per merchant for a cycle, next to the previous cycle's totals.",
          {"cycle": STR}),
    _tool("ask_user", "Ask the user a question and wait for their typed answer.",
          {"question": STR, "options": {"type": "array", "items": STR}}),
    _tool("save_explanation", "Store your plain-language explanation of one flag for the report.",
          {"flag_id": {"type": "integer"}, "explanation": STR}),
    _tool("save_decision", "Save the user's decision for a merchant. user_answer must be the "
          "user's reply to ask_user, copied exactly.",
          {"cycle": STR, "merchant": STR,
           "decision": {"type": "string", "enum": list(config.DECISIONS)},
           "note": STR, "user_answer": STR}),
    _tool("save_letter", "Save a letter draft to disk (it is not sent).",
          {"cycle": STR, "merchant": STR,
           "kind": {"type": "string", "enum": ["cancel", "dispute"]}, "text": STR}),
    _tool("write_report", "Write the CSV and Excel report for a cycle.", {"cycle": STR}),
]


class Tools:
    def __init__(self, memory: Memory, out_dir: Path, input_fn=input):
        self.memory = memory
        self.out_dir = out_dir
        self.input_fn = input_fn
        self.user_answers: set[str] = set()

    def run(self, name: str, args: dict) -> object:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ValueError(f"unknown tool {name}")
        return handler(**args)

    def tool_load_statement(self, path: str):
        stmt = load_statement(path)
        self.memory.import_statement(stmt)
        return {"cycle": stmt.cycle, "warnings": stmt.warnings,
                "charges": [{"date": c.date.isoformat(), "merchant": c.merchant,
                             "statement_text": c.raw_merchant, "amount": c.amount}
                            for c in stmt.charges]}

    def tool_run_checks(self, cycle: str):
        if cycle not in self.memory.cycles():
            raise ValueError(f"cycle {cycle} is not loaded; call load_statement first")
        self.memory.clear_flags(cycle)
        result = []
        for s in analyse_cycle(self.memory, cycle):
            flags = [{"flag_id": self.memory.save_flag(cycle, f.merchant, f.kind, f.message, f.data),
                      "kind": f.kind, "finding": f.message, "details": f.data} for f in s.flags]
            result.append({
                "merchant": s.merchant,
                "charges": [{"date": c.date.isoformat(), "amount": c.amount,
                             "statement_text": c.raw_merchant} for c in s.charges],
                "is_subscription": s.is_subscription, "reason": s.reason,
                "previous_decision": s.previous_decision and {
                    k: s.previous_decision[k] for k in ("cycle", "decision", "note")},
                "earlier_flags": [{"cycle": f["cycle"], "kind": f["kind"]} for f in s.past_flags],
                "flags": flags,
                "needs_decision": s.needs_decision,
            })
        return result

    def tool_get_history(self, merchant: str):
        return self.memory.history(merchant)

    def tool_spending_summary(self, cycle: str):
        cycles = self.memory.cycles()
        previous = max((c for c in cycles if c < cycle), default=None)
        before = {r["merchant"]: r["total"] for r in self.memory.spending(previous)} if previous else {}
        rows = [{**r, "previous_total": before.get(r["merchant"], 0)}
                for r in self.memory.spending(cycle)]
        return {"cycle": cycle, "previous_cycle": previous, "merchants": rows,
                "total": sum(r["total"] for r in rows), "previous_total": sum(before.values())}

    def tool_ask_user(self, question: str, options: list[str]):
        hint = f" [{'/'.join(options)}]" if options else ""
        answer = self.input_fn(f"\nAgent asks: {question}{hint}\n> ").strip()
        self.user_answers.add(answer)
        return {"answer": answer}

    def tool_save_explanation(self, flag_id: int, explanation: str):
        self.memory.set_explanation(flag_id, explanation)
        return {"saved": True}

    def tool_save_decision(self, cycle: str, merchant: str, decision: str, note: str,
                           user_answer: str):
        if user_answer.strip() not in self.user_answers:
            raise PermissionError("user_answer does not match anything the user typed; "
                                  "ask the user with ask_user first")
        self.memory.save_decision(cycle, merchant, decision, note)
        return {"saved": True}

    def tool_save_letter(self, cycle: str, merchant: str, kind: str, text: str):
        path = save_letter(self.out_dir, cycle, kind, merchant, text)
        return {"saved_to": str(path), "sent": False}

    def tool_write_report(self, cycle: str):
        return {"files": [str(p) for p in write_report(self.memory, cycle, self.out_dir)]}


def run_agent(client, statement_path: str, memory: Memory, out_dir: Path,
              language: str = "English", input_fn=input, max_steps: int = 60) -> None:
    tools = Tools(memory, out_dir, input_fn)
    system = SYSTEM.format(currency=config.CURRENCY, language=language)
    messages = [{"role": "user", "content":
                 f"Here is this month's statement: {statement_path}. Please review it."}]

    steps = 0
    while steps < max_steps:
        steps += 1
        response = create_message(client, max_tokens=16000, system=system, tools=TOOLS,
                                  output_config={"effort": "medium"}, messages=messages)
        messages.append({"role": "assistant", "content": response.content})
        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(f"\nAgent: {block.text.strip()}")

        if response.stop_reason == "refusal":
            print("\n[agent] the model declined to continue.")
            return
        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"  [tool] {block.name}({_short(block.input)})")
                try:
                    output = tools.run(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(output, default=str)})
                except Exception as exc:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Error: {exc}", "is_error": True})
            messages.append({"role": "user", "content": results})
            continue

        # end_turn (or max_tokens): hand the conversation back to the user.
        follow_up = input_fn("\nYou (press Enter to finish): ").strip()
        if not follow_up:
            return
        messages.append({"role": "user", "content": follow_up})
    print(f"\n[agent] stopped after {max_steps} steps.")


def _short(args: dict) -> str:
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) < 120 else text[:117] + "..."
