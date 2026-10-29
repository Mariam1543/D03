# D03 – Subscription & Recurring-Charge Tracker Agent

An agent that reviews a monthly bank statement (CSV), finds subscriptions and
recurring bills, flags anything suspicious (duplicate charges, changed billing
dates, price changes, charges after you cancelled), asks you what to do,
**remembers your decisions in SQLite**, and writes a report plus letter drafts.

> Roman Urdu mein: har mahine statement do, agent bills check karta hai, gadbad
> pakarta hai, tumse poochta hai (keep / cancel / later / dispute), tumhara
> faisla yaad rakhta hai, aur agle mahine wohi memory use karta hai.

## Who does what

| Part | Role | File |
|---|---|---|
| Python rules | Decide **what** is suspicious (fixed thresholds, same input → same flags) | `subtracker/rules.py` |
| SQLite | Memory across months: charges, flags, decisions | `subtracker/memory.py` |
| LLM (Claude) | Explains flags in plain language, writes letters; in agent mode also chooses the steps | `subtracker/llm.py`, `subtracker/agent.py` |
| CSV / Excel | Report of charges, flags, decisions and spending | `subtracker/report.py` |

The LLM never creates or removes a flag. It only explains flags that the Python
rules raised. A flag means "please look", not "fraud": e.g. an internet company
may simply move its billing date. **You** make the final decision.

## Flags (rules)

| Flag | Rule (thresholds in `subtracker/config.py`) |
|---|---|
| `NEW_SUBSCRIPTION` | First time a merchant that looks like a subscription appears |
| `DUPLICATE` | Same merchant, same amount (±1 %), within 5 days in one cycle |
| `DATE_SHIFT` | Billing day moved by more than 3 days compared with last cycle |
| `AMOUNT_CHANGE` | Amount changed by more than 10 % compared with last cycle |
| `CHARGED_AFTER_CANCEL` | You chose *cancel* earlier but were charged again |

A merchant counts as a subscription if you made a decision about it before, if it
was charged a similar amount last cycle (±10 %), or if its name matches a known
subscription service. You are only asked about a merchant when it has a flag or
has no decision yet (or you said *later*). Anything you already decided *keep*
with no new issues is not asked again: that is the memory at work.

## Two modes: workflow vs. agent

**Workflow (`run`, `demo`)**: fixed steps in a fixed order:
load → save to memory → run rules → LLM explains → ask you → save decision →
letter → report. It runs fully offline (template text) if no API key is set.

**Agent (`agent`)**: Claude gets the same building blocks as tools
(`load_statement`, `run_checks`, `get_history`, `spending_summary`, `ask_user`,
`save_explanation`, `save_decision`, `save_letter`, `write_report`) and decides
which to call and when. What this adds over plain automation:

- **Judgment on unknown merchants.** In March, `PADDLE.NET* NOTION LABS` is not on
  the keyword list, so the rules do not treat it as a subscription. The agent can
  recognise it as a software subscription and ask you about it.
- **Uses memory when it matters.** It calls `get_history` only when a flag needs
  context ("this duplicate also happened in February").
- **Conversation.** After the review you can ask things like "why is my spending
  higher this month?" and it answers with `spending_summary` / `get_history`.

Guard rails are enforced in code, not only in the prompt:

- `save_decision` is refused unless it quotes an answer you actually typed in `ask_user`.
- There is no "send" tool. Letters are only saved as drafts in `out/letters/`.
- Flags only come from `rules.py`.

## Setup (VS Code)

```bash
git clone https://github.com/Mariam1543/D03.git
cd D03
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your ANTHROPIC_API_KEY in .env
```

Without a key, everything except `agent` still works; explanations and letters
use built-in templates.

## Run

```bash
# The 3-month story with scripted answers (fresh memory every time)
python main.py demo
python main.py --offline demo          # same, without calling the LLM

# Review one statement yourself (you are asked keep/cancel/later/dispute)
python main.py run data/statement_2026_01.csv
python main.py run data/statement_2026_02.csv
python main.py run data/statement_2026_03.csv

# Same, but with the LLM agent deciding the steps
python main.py agent data/statement_2026_01.csv

# Explanations and letters in Roman Urdu
python main.py --language "Roman Urdu" run data/statement_2026_01.csv

# Look into the memory
python main.py status
python main.py history Spotify
python main.py reset                   # delete memory.db and start over
```

Outputs go to `out/`: `report_<cycle>.csv`, `report_<cycle>.xlsx` (sheets:
Charges, Flags, Decisions, Spending) and `letters/<cycle>_<cancel|dispute>_<merchant>.txt`.

## The 3-month sample data (`data/`)

| Cycle | What happens | What the agent does |
|---|---|---|
| **2026-01** | Netflix, PTCL Internet, Gold's Gym, Spotify appear for the first time | Flags all four as new; demo answers: Gym → *cancel* (letter drafted), others → *keep* |
| **2026-02** | Spotify charged twice; Gym charged although cancelled; Canva appears | `DUPLICATE`, `CHARGED_AFTER_CANCEL`, `NEW_SUBSCRIPTION`. Netflix and Internet are **not** asked again (kept in January) |
| **2026-03** | Internet billed on the 12th instead of the 5th; Canva price 1,200 → 1,500; Notion appears; different CSV column names and date format | `DATE_SHIFT`, `AMOUNT_CHANGE`; Spotify is not asked but the February duplicate is shown from memory; Notion is caught only in agent mode |

The March file deliberately uses other column names (`Transaction Date,
Description, Debit`) and `dd/mm/yyyy` dates to show that the loader copes with
different bank formats.

## Project structure

```
D03/
├── main.py                 # command line
├── data/                   # 3 sample statements + scripted demo answers
├── subtracker/
│   ├── config.py           # thresholds, keywords, merchant aliases, model
│   ├── loader.py           # CSV → clean charges (column aliases, dates, amounts, names)
│   ├── memory.py           # SQLite memory
│   ├── rules.py            # deterministic flags
│   ├── llm.py              # Claude: explanations + letters (template fallback)
│   ├── workflow.py         # fixed pipeline
│   ├── agent.py            # tool-using agent loop
│   └── report.py           # CSV / Excel / letters
└── tests/test_tracker.py
```

## Tests

```bash
python -m pytest
```

The tests replay the three months and check every expected flag, that kept
subscriptions are not asked again, that the February duplicate is remembered in
March, that re-running a month replaces it instead of duplicating it, and that
the agent loop dispatches tools correctly (with a fake client, no API calls).

## Notes and limits

- Model: `claude-opus-5-5` (change with `SUBTRACKER_MODEL`). Requests enable the
  API's server-side refusal fallback (`fallbacks="default"`).
- The keyword list and merchant aliases are small examples; extend them in
  `config.py` for your bank.
- Running on Kaggle instead of VS Code works too, but keep all months in one
  session (or download `memory.db`), because Kaggle deletes files when the session ends.
