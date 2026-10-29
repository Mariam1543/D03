import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from subtracker import rules
from subtracker.agent import Tools, run_agent
from subtracker.llm import Writer
from subtracker.loader import load_statement, normalize_merchant, parse_amount, parse_date
from subtracker.memory import Memory
from subtracker.workflow import run_cycle, scripted_ask

DATA = Path(__file__).resolve().parent.parent / "data"
STATEMENTS = sorted(DATA.glob("statement_*.csv"))
SCRIPT = json.loads((DATA / "demo_decisions.json").read_text())


@pytest.fixture
def memory(tmp_path):
    m = Memory(tmp_path / "test.db")
    yield m
    m.close()


def flag_kinds(memory, cycle):
    return {(f["merchant"], f["kind"]) for f in memory.flags(cycle=cycle)}


# --- loader -------------------------------------------------------------------

def test_parsing_helpers():
    assert parse_amount("Rs. 1,000") == 1000
    assert parse_amount("-450") == 450
    assert parse_date("05/03/2026") == date(2026, 3, 5)
    assert parse_date("2026-01-05") == date(2026, 1, 5)
    assert normalize_merchant("SPOTIFY P2F4A1") == "Spotify"
    assert normalize_merchant("PADDLE.NET* NOTION LABS") == "Notion Labs"


def test_loader_handles_other_column_names():
    stmt = load_statement(DATA / "statement_2026_03.csv")   # Transaction Date / Description / Debit
    assert stmt.cycle == "2026-03"
    assert len(stmt.charges) == 8
    assert not stmt.warnings


def test_loader_skips_bad_rows(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("Date,Merchant,Amount\n2026-01-05,Netflix,1000\nnot a date,X,5\n")
    stmt = load_statement(f)
    assert len(stmt.charges) == 1 and len(stmt.warnings) == 1


# --- three-month story --------------------------------------------------------

def test_three_cycles_flags_and_memory(memory, tmp_path):
    writer, ask = Writer(None), scripted_ask(SCRIPT)
    jan, feb, mar = (run_cycle(s, memory, writer, ask, tmp_path) for s in STATEMENTS)

    # January: everything is new.
    assert flag_kinds(memory, "2026-01") == {
        (m, rules.NEW_SUBSCRIPTION) for m in ("Netflix", "PTCL Internet", "Gold's Gym", "Spotify")}
    assert jan.decisions["Gold's Gym"] == "cancel"

    # February: duplicate Spotify, gym charged after cancelling, Canva new.
    # Netflix is not asked again because it was kept in January.
    assert flag_kinds(memory, "2026-02") == {
        ("Spotify", rules.DUPLICATE), ("Gold's Gym", rules.CHARGED_AFTER_CANCEL),
        ("Canva", rules.NEW_SUBSCRIPTION)}
    assert "Netflix" not in feb.decisions

    # March: internet date moved, Canva price rose; Spotify's February duplicate is remembered.
    assert flag_kinds(memory, "2026-03") == {
        ("PTCL Internet", rules.DATE_SHIFT), ("Canva", rules.AMOUNT_CHANGE)}
    spotify = next(s for s in mar.statuses if s.merchant == "Spotify")
    assert [f["kind"] for f in spotify.past_flags if f["kind"] == rules.DUPLICATE] == ["DUPLICATE"]
    assert not spotify.needs_decision

    # Letters are drafted for cancel/dispute only, and reports exist.
    names = sorted(p.name for p in jan.letters + feb.letters + mar.letters)
    assert names == ["2026-01_cancel_gold_s_gym.txt", "2026-02_dispute_gold_s_gym.txt",
                     "2026-02_dispute_spotify.txt", "2026-03_cancel_canva.txt"]
    assert (tmp_path / "report_2026-03.csv").exists()


def test_rerunning_a_cycle_replaces_it(memory, tmp_path):
    writer, ask = Writer(None), scripted_ask(SCRIPT)
    run_cycle(STATEMENTS[0], memory, writer, ask, tmp_path)
    run_cycle(STATEMENTS[0], memory, writer, ask, tmp_path)
    assert len(memory.charges("2026-01")) == 7
    assert len(memory.flags(cycle="2026-01")) == 4
    assert len(memory.decisions("2026-01")) == 4


def test_non_subscription_merchants_are_not_flagged(memory, tmp_path):
    for s in STATEMENTS:
        run_cycle(s, memory, Writer(None), scripted_ask(SCRIPT), tmp_path)
    flagged = {f["merchant"] for f in memory.flags()}
    assert not flagged & {"Foodpanda", "Daraz", "Shell Petrol Station"}


# --- agent ----------------------------------------------------------------------

def test_save_decision_requires_real_user_answer(memory, tmp_path):
    tools = Tools(memory, tmp_path, input_fn=lambda prompt: "keep")
    with pytest.raises(PermissionError):
        tools.run("save_decision", {"cycle": "2026-01", "merchant": "Netflix",
                                    "decision": "keep", "note": "", "user_answer": "keep"})
    tools.run("ask_user", {"question": "Netflix?", "options": ["keep", "cancel"]})
    tools.run("save_decision", {"cycle": "2026-01", "merchant": "Netflix",
                                "decision": "keep", "note": "", "user_answer": "keep"})
    assert memory.latest_decision("Netflix")["decision"] == "keep"


class FakeClient:
    """Replays a fixed list of model turns so the agent loop can be tested offline."""

    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.turns)


def tool_turn(*calls):
    blocks = [SimpleNamespace(type="tool_use", id=f"t{i}", name=name, input=args)
              for i, (name, args) in enumerate(calls)]
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


def text_turn(text):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def test_agent_loop_runs_tools(memory, tmp_path):
    path = str(STATEMENTS[0])
    client = FakeClient([
        tool_turn(("load_statement", {"path": path})),
        tool_turn(("run_checks", {"cycle": "2026-01"})),
        tool_turn(("ask_user", {"question": "Keep Netflix?", "options": ["keep", "cancel"]})),
        tool_turn(("save_decision", {"cycle": "2026-01", "merchant": "Netflix", "decision": "keep",
                                     "note": "", "user_answer": "keep"}),
                  ("write_report", {"cycle": "2026-01"})),
        text_turn("Done."),
    ])
    answers = iter(["keep", ""])   # answer to ask_user, then Enter to finish
    run_agent(client, path, memory, tmp_path, input_fn=lambda prompt: next(answers))

    assert memory.latest_decision("Netflix")["decision"] == "keep"
    assert (tmp_path / "report_2026-01.csv").exists()
    # Every tool_use got a matching tool_result in the following request.
    last = client.requests[-1]["messages"]
    results = [b for m in last if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"]]
    assert all(not r.get("is_error") for r in results)
    assert len(results) == 5
