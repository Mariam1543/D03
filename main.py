"""Command line entry point.

    python main.py demo                         # all 3 sample months, scripted answers
    python main.py run data/statement_2026_01.csv
    python main.py agent data/statement_2026_01.csv
    python main.py history Spotify
    python main.py status
    python main.py reset
"""

import argparse
import json
import sys
from pathlib import Path

from subtracker import config
from subtracker.agent import run_agent
from subtracker.llm import Writer, make_client
from subtracker.memory import Memory
from subtracker.workflow import interactive_ask, run_cycle, scripted_ask

DATA = config.PROJECT_ROOT / "data"


def load_env_file() -> None:
    """Read KEY=VALUE lines from .env so the API key does not live in code."""
    import os
    env = config.PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def cmd_run(args) -> None:
    memory = Memory(args.db)
    writer = Writer(make_client(args.offline), args.language)
    if args.decisions:
        ask = scripted_ask(json.loads(Path(args.decisions).read_text()))
    else:
        ask = interactive_ask
    run_cycle(args.statement, memory, writer, ask, args.out)
    memory.close()


def cmd_demo(args) -> None:
    db = args.out / "demo.db"
    db.unlink(missing_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    memory = Memory(db)
    writer = Writer(make_client(args.offline), args.language)
    ask = scripted_ask(json.loads((DATA / "demo_decisions.json").read_text()))
    for statement in sorted(DATA.glob("statement_*.csv")):
        run_cycle(statement, memory, writer, ask, args.out)
    print(f"\nDemo memory kept in {db}")
    memory.close()


def cmd_agent(args) -> None:
    client = make_client(offline=False)
    if client is None:
        sys.exit("Agent mode needs Claude API access. Put ANTHROPIC_API_KEY in .env.")
    memory = Memory(args.db)
    try:
        run_agent(client, args.statement, memory, args.out, args.language)
    except Exception as exc:  # e.g. missing credentials or a network error
        sys.exit(f"Agent stopped: {exc.__class__.__name__}: {exc}")
    finally:
        memory.close()


def cmd_history(args) -> None:
    memory = Memory(args.db)
    print(json.dumps(memory.history(args.merchant), indent=2, default=str))
    memory.close()


def cmd_status(args) -> None:
    memory = Memory(args.db)
    print("Cycles in memory:", ", ".join(memory.cycles()) or "none")
    for d in memory.decisions():
        print(f"  {d['cycle']}  {d['merchant']:<20} {d['decision']:<8} {d['note']}")
    memory.close()


def cmd_reset(args) -> None:
    args.db.unlink(missing_ok=True)
    print(f"Deleted {args.db}")


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Subscription and recurring-charge tracker")
    parser.add_argument("--db", type=Path, default=config.DEFAULT_DB_PATH, help="SQLite memory file")
    parser.add_argument("--out", type=Path, default=config.DEFAULT_OUT_DIR, help="output folder")
    parser.add_argument("--language", default="English",
                        help='language for explanations and letters, e.g. "Roman Urdu"')
    parser.add_argument("--offline", action="store_true", help="do not call the LLM; use templates")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="review one statement with the fixed workflow")
    p.add_argument("statement")
    p.add_argument("--decisions", help="JSON file with answers instead of asking")
    p.set_defaults(func=cmd_run)

    sub.add_parser("demo", help="run the three sample months with scripted answers").set_defaults(func=cmd_demo)

    p = sub.add_parser("agent", help="review one statement with the LLM agent")
    p.add_argument("statement")
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("history", help="show everything remembered about a merchant")
    p.add_argument("merchant")
    p.set_defaults(func=cmd_history)

    sub.add_parser("status", help="list cycles and decisions in memory").set_defaults(func=cmd_status)
    sub.add_parser("reset", help="delete the memory database").set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
