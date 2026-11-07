# D03 – Simple Guide + Demo Plan

---

## 1. The project in one minute

Every month your bank gives you a statement (a list of payments).
Hidden in that list are **subscriptions**: Netflix, Spotify, gym, internet...
They take money every month and people forget about them.

**Our program reads the statement and acts like a careful assistant:**

1. It finds the subscriptions.
2. It spots problems:
   - charged **twice** (duplicate)
   - bill came on a **different date**
   - **price went up**
   - you said "cancel" but they **still charged you**
3. It **asks you** what to do: keep / cancel / later / dispute.
4. It **remembers** your answer for next month.
5. It makes a **report** (Excel + CSV) and **letter drafts** (cancel / refund).
   It never sends anything itself.

The special part is **memory**. Next month it already knows what you decided,
so it does not ask the same question again. It also remembers old problems.

---

## 2. The four helpers inside the project

| Helper | Think of it as | What it does |
|---|---|---|
| **Python rules** | A strict checker with a rule book | Compares numbers and dates and decides what is suspicious |
| **SQLite database** | A diary | Saves every charge, every problem, every decision, month after month |
| **Claude (LLM)** | A writer | Explains each problem in simple words and writes letters |
| **Report** | The result sheet | Excel/CSV with everything in one place |

**Important:** Claude never decides what is suspicious. Python does that with
fixed rules. Claude only *explains* it. Without Claude, the program uses
ready-made template sentences instead.

---

## 3. What happens in one month (one "cycle")

```
 Bank CSV ──► 1. Read & clean ──► 2. Save in diary (SQLite)
                                        │
                                        ▼
            3. Python rules compare with last month ──► problems ("flags")
                                        │
                                        ▼
            4. Explain each flag (Claude, or template if offline)
                                        │
                                        ▼
            5. Ask you: keep / cancel / later / dispute
                                        │
                                        ▼
            6. Save your answer in diary ──► 7. Letter draft (cancel/dispute)
                                        │
                                        ▼
                               8. Report (CSV + Excel)
```

---

## 4. What each file does

| File | Simple meaning |
|---|---|
| `main.py` | **The front door.** You type commands here (`demo`, `run`, `status`, ...). |
| `subtracker/config.py` | **The settings.** All the numbers the rules use (5 days, 10 %, etc.), the list of subscription words, and the merchant name fixes. |
| `subtracker/loader.py` | **The reader.** Opens the CSV, understands different column names and date styles, cleans names (`SPOTIFY P2F4A1` → `Spotify`). |
| `subtracker/memory.py` | **The diary.** Creates the SQLite tables and saves/reads charges, flags and decisions. |
| `subtracker/rules.py` | **The checker.** Finds the 5 kinds of problems (table below). |
| `subtracker/llm.py` | **The writer.** Asks Claude to explain flags and write letters. If no Claude, uses templates. |
| `subtracker/workflow.py` | **The fixed recipe.** Runs steps 1–8 in the same order every time. |
| `subtracker/agent.py` | **The smart mode.** Gives the same steps to Claude as "tools" and lets Claude choose the order. Needs Claude. |
| `subtracker/report.py` | **The report maker.** Writes the CSV, the Excel file (4 sheets) and the letter files. |
| `data/` | **Sample statements** for January, February, March + the demo's ready answers. |
| `tests/test_tracker.py` | **Automatic checks** that prove everything works. |

### The 5 problems ("flags") the checker finds

| Flag | Meaning in simple words | Rule |
|---|---|---|
| `NEW_SUBSCRIPTION` | "I see this subscription for the first time" | name looks like a subscription and never seen before |
| `DUPLICATE` | "They took money twice" | same shop, same amount, within 5 days |
| `DATE_SHIFT` | "Bill came on a different date" | date moved more than 3 days |
| `AMOUNT_CHANGE` | "Price changed" | amount changed more than 10 % |
| `CHARGED_AFTER_CANCEL` | "You said cancel, but they still charged you" | earlier decision was cancel |

A flag means **"please check"**, not **"fraud"**. Example: an internet company
can simply change its billing date. That is why **you** decide, not the program.

---

## 5. Running it WITHOUT Claude (no API key)

Add `--offline` to every command. Then no Claude call is made at all.

### One-time setup (Windows, in VS Code terminal)

```bash
git clone https://github.com/Mariam1543/D03.git
cd D03
pip install -r requirements.txt
```
(Offline mode really only needs `openpyxl` for the Excel file.)

Mac/Linux: use `python3` instead of `python` in the commands below.

### Commands

| Command | What it does |
|---|---|
| `python main.py --offline demo` | Runs all 3 months automatically with ready answers. **Best for the demo.** |
| `python main.py --offline run data/statement_2026_01.csv` | Runs one month and **asks you** the questions. |
| `python main.py status` | Shows which months and decisions are in the diary. |
| `python main.py history Spotify` | Shows everything the diary knows about Spotify. |
| `python main.py reset` | Deletes the diary to start fresh. |
| `python -m pytest` | Runs the automatic tests. |

The `demo` command keeps its own diary in `out/demo.db`. To look inside it, add
`--db out/demo.db`, for example `python main.py --db out/demo.db history Spotify`.

**Results appear in the `out/` folder:**
- `report_2026-01.xlsx`, `..._02`, `..._03`: Excel with sheets **Charges, Flags, Decisions, Spending**
- `letters/`: letter drafts such as `2026-02_dispute_spotify.txt`

---

## 6. The 3-month story (what you will see)

**January:** everything is new.
- Netflix, Internet, Gym, Spotify → `NEW_SUBSCRIPTION`
- Answers: Gym = **cancel** (cancel letter made), others = **keep**
- Foodpanda, Daraz, Shell → listed as "other charges" (not subscriptions)

**February:** problems appear.
- Spotify charged twice → `DUPLICATE` → answer **dispute** (refund letter)
- Gym charged although cancelled → `CHARGED_AFTER_CANCEL` → **dispute**
- Canva appears → `NEW_SUBSCRIPTION` → **later**
- Netflix and Internet → **not asked again** ("your last decision was keep"). ← memory!

**March:** memory pays off.
- Internet bill on the 12th instead of the 5th → `DATE_SHIFT` → **keep**
- Canva 1,200 → 1,500 → `AMOUNT_CHANGE` → **cancel**
- Spotify normal now, but the program says **"earlier DUPLICATE in 2026-02"**. ← memory!
- The March file has **different column names and date style**, and it still works.
- **Notion** is NOT caught (its name is not in the word list).
  This is exactly where the **agent mode** (with Claude) helps: it can recognise it.

---

## 7. Demo script for tomorrow (about 8–10 minutes)

> Before you start: open the D03 folder in VS Code, open a terminal, and run
> `python main.py reset` so nothing old is left.

### Step 1: The problem (1 min)
**Say:** "People forget subscriptions and do not notice double charges or price
increases. I built an agent that checks the monthly bank statement, finds these
problems, asks the user what to do, and remembers the decisions every month."

### Step 2: Show the input (1 min)
Open `data/statement_2026_01.csv`, then `data/statement_2026_03.csv`.
**Say:** "This is the bank statement. Notice March uses different column names
and a different date style, like a different bank. The loader handles both."

### Step 3: Run all three months (3 min)
```bash
python main.py --offline demo
```
Scroll through the output and point at:
- January: 4 new subscriptions, Gym cancelled → letter saved
- February: **DUPLICATE** Spotify, **CHARGED_AFTER_CANCEL** Gym,
  and **"Netflix: no new issues, your last decision was keep"**
- March: **DATE_SHIFT** Internet, **AMOUNT_CHANGE** Canva,
  and **"Spotify ... earlier DUPLICATE in 2026-02"**

**Say:** "The agent is not only looking at today's file. It uses its memory of
earlier months. That is the main idea of the project."

### Step 4: Show the results (1.5 min)
- Open `out/report_2026-03.xlsx` and show the 4 sheets.
- Open `out/letters/2026-02_dispute_spotify.txt`.

**Say:** "Letters are only drafts. The program can never send anything."

### Step 5: Show the memory (1 min)
```bash
python main.py --db out/demo.db history Spotify
```
**Say:** "This is the SQLite diary: every charge, every flag, every decision."

### Step 6: Live, you decide (1.5 min)
```bash
python main.py --offline run data/statement_2026_01.csv
```
It asks for Gold's Gym, Netflix, PTCL Internet and Spotify, in that order.
Type `k` (keep), `c` (cancel), `l` (later) or `d` (dispute), then press Enter
for the note.

**Say:** "The user always makes the final decision. A flag means 'please check',
not 'fraud'."

### Step 7: Explain Claude's role and agent mode (1 min)
**Say:** "Today I ran it offline, so explanations come from templates. With an
API key, Claude writes the explanations and letters. In **agent mode**, Claude
gets these same steps as tools and decides the order itself. For example, it can
recognise *Notion* as a subscription even though my rules missed it. For safety,
the code refuses to save a decision unless the user really typed it, and there
is no tool that sends anything."

### Step 8: Prove it works (30 sec)
```bash
python -m pytest
```
**Say:** "8 automatic tests check every expected flag across the three months."

---

## 8. Questions the teacher may ask (and simple answers)

**Q: Isn't this just automation? Where is the agent?**
A: The `run`/`demo` mode is a fixed workflow, which is automation. The `agent`
mode is the agent: Claude chooses which tool to use and when, handles unknown
merchants like Notion, and answers follow-up questions like "why is my spending
higher this month?"

**Q: Why does Python decide the flags and not the LLM?**
A: Rules give the same answer every time, cost nothing, and can be tested. An
LLM can make mistakes with numbers. So Python finds the problem and the LLM
explains it.

**Q: How does the memory work?**
A: SQLite file with 4 tables: `cycles`, `charges`, `flags`, `decisions`. Each new
month is compared with what is stored from earlier months.

**Q: What if I run the same month twice?**
A: It replaces that month's data instead of adding it twice. There is a test for this.

**Q: Why was Notion not flagged?**
A: The rules only know subscription names from a word list in `config.py`.
Notion is not on it. This shows the limit of plain rules, and why the agent
mode with Claude is useful.

**Q: Can the agent make decisions without me?**
A: No. In the code, `save_decision` is refused unless it matches an answer the
user actually typed.

**Q: Does it send emails or cancel subscriptions?**
A: No. It only saves letter drafts. There is no "send" function.

**Q: What if the bank uses other column names?**
A: The loader knows several names for each column (e.g. "Description" =
"Merchant", "Debit" = "Amount"). The March file proves it.

**Q: Where can I change the rules?**
A: `subtracker/config.py`, e.g. 5 days for duplicates, 10 % for price changes.

---

## 9. If something goes wrong

| Problem | Fix |
|---|---|
| `python` not found | Try `py main.py ...` or `python3 main.py ...` |
| `No module named openpyxl` | `pip install openpyxl` |
| Excel file will not open/update | Close it in Excel first, then run again |
| Old results mixed in | `python main.py reset` and delete the `out` folder |
| It asks questions you did not expect | That is normal for `run`: just answer `k/c/l/d` |

---

## 10. Checklist for tonight

- [ ] Clone the repo and run `pip install -r requirements.txt`
- [ ] Run `python main.py --offline demo` once and read the output
- [ ] Open the Excel report and one letter
- [ ] Practise Step 6 (the live questions) once
- [ ] Run `python -m pytest` and check that all 8 pass
- [ ] Read section 8 (questions) twice
- [ ] Before the demo: `python main.py reset`
