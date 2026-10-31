# copilot-evals

This repo collects real runs of [runbook-copilot](https://github.com/cianlabs/runbook-copilot) so a person can later read them and label what went wrong.

It asks a fixed list of questions and writes down what the agent did. Four plain checks can score a run file after that. The names for the labels live in [taxonomy.md](taxonomy.md). The counts there are filled in by hand. Per-run notes are in [labels.md](labels.md).

If the agent proposes an action, this harness always says no. A restart is not run. A delete is not run.

## Run the practice pass

From this folder:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python collect_runs.py
```

The first run clones `runbook-copilot` into `.vendor/runbook-copilot` at a pinned commit. That download is the agent code, not a call to a model. After that, the same command reuses the clone.

The default is the built-in practice model (`DemoClient` in runbook-copilot's `app.py`). It searches the local runbooks on this machine. It needs no API key and does not call the model network.

Each question adds one line to `runs.jsonl` in the current directory. Running the command again appends more lines. Delete `runs.jsonl` first if you want a fresh file.

Ask every question more than once:

```bash
.venv/bin/python collect_runs.py --passes 3
```

## Compare the loop and the graph

The old copilot walks in a loop (`run_agent` in `agent.py`). A newer copy walks a picture of boxes (`run_graph` in `graph_agent.py`). That newer copy is on the branch `cursor/graph-agent-loop-86f9` of runbook-copilot. The branch is not merged.

This command asks all 30 questions to both versions and writes `compare.md`:

```bash
.venv/bin/python compare_agents.py
```

The first run downloads that branch into `.vendor-graph/`. Git ignores that folder. The download is the agent code, not a call to a model. After that, the same command reuses the download.

It uses the same practice rules as `collect_runs.py`: the practice model, no API key, no model network call, every proposed action declined, and logging turned off. Running it again replaces `compare.md`.

Open `compare.md` to see the counts, one row per question, and a short note for any question where the two versions did not match.

## Open a run

`runs.jsonl` is plain text. One run is one line of JSON.

Pretty-print the first line of the sample that is already committed:

```bash
python3 -c "import json; print(json.dumps(json.loads(open('runs.sample.jsonl').readline()), indent=2))"
```

`runs.sample.jsonl` is nine lines copied from a practice pass. Your full `runs.jsonl` stays on your machine (it is listed in `.gitignore`).

Fields on each line:

| Field | What it is |
| --- | --- |
| question | The text that was asked |
| category | `answerable`, `not_in_runbooks`, `near_miss`, or `action` |
| stop_reason | Why the agent loop stopped, such as `ANSWERED` or `NO_RELEVANT_RUNBOOK` |
| answer | The reply the loop kept, without a copied Sources block. If it proposed an action, the line also says nothing was run |
| sources | Runbook sections the citation rule kept. Same facts as the Sources list in the terminal |
| steps | How many model steps the loop used |
| thoughts | What the model said it still needed before each tool call |
| seconds | How long that question took |
| failure | The `AgentError` name if the loop raised, otherwise `null`. A retrieve failure is stored under its own name too |
| pass_number | `1` the first time through the list. Higher when you use `--passes` |

## Check a run file

```bash
.venv/bin/python check_runs.py
.venv/bin/python check_runs.py runs.sample.jsonl
.venv/bin/python check_runs.py --strict
```

This reads a jsonl file and runs four checks on each line. It does not call a model. The default file is `runs.sample.jsonl`.

The table lists each check, how many runs it flagged, and those run numbers. It also prints a total. The command exits 0 even when a check flags a run. Add `--strict` to exit with status 1 when any check flags.

Checked by code: `PARTIAL_ANSWER`, `ANSWERED_OUT_OF_SCOPE`, `MISSING_CITATION`, `UNSAFE_ACTION_PROPOSED`.

`PARTIAL_ANSWER` covers an answerable question. It also covers an action question when the stop reason is `ANSWERED` and the reply is only a symptom line, with no proposed action.

Still needs a person: `WRONG_RUNBOOK_CITED`, `WRONGLY_REFUSED`, `ANSWERED_WRONGLY`, `RAMBLING_OR_PASTED_TEXT`.

Known limitation: `ANSWERED_OUT_OF_SCOPE` flags a `near_miss` run that was answered. The code cannot judge whether a cited runbook fits the question. On the 30 practice runs, runs 22 and 25 are flagged by this check and hand-labeled `WRONG_RUNBOOK_CITED` in [labels.md](labels.md). Citing the wrong runbook stays a human label.

The rules are in [taxonomy.md](taxonomy.md).

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

The tests need no API key and make no network calls. Most of them use a fake model. They do need a `runbook-copilot` checkout for the practice-pass test. The practice command above creates one. The comparison test also needs the graph download. `compare_agents.py` creates that one. The checks in `tests/test_checks.py` only read the sample file and small hand-written runs. They do not need a checkout.

To use a checkout you already have, instead of the pinned clone:

```bash
export RUNBOOK_COPILOT_PATH="$HOME/src/runbook-copilot"
```

`--copilot-path` does the same thing for one command.

## Real model

```bash
.venv/bin/python collect_runs.py --real
```

`--real` reads `XAI_API_KEY` from the environment. Set the key in the terminal. Do not put it in a file. The harness never prints it, never logs it, and never writes it into `runs.jsonl`. If the key is missing, the command stops with `MISSING_KEY` and does not write a line per question.

## What each file is

- `questions.txt` — 30 starter questions, written as `category | question`
- `collect_runs.py` — runs them and appends `runs.jsonl`
- `checks.py` — four plain checks for one run record
- `check_runs.py` — reads a jsonl file and prints a score table
- `compare_agents.py` — asks each question to the loop and the graph, then writes `compare.md`
- `compare.md` — the comparison, so you can read it on GitHub without running anything
- `taxonomy.md` — stop reasons, `AgentError` names, action failures, and hand labels, with counts
- `labels.md` — a hand label for each of the 30 practice runs
- `runs.sample.jsonl` — a short slice of a practice pass
- `test_collect_runs.py` — the pytest checks for the collector
- `test_compare_agents.py` — the pytest checks for the comparison
- `tests/test_checks.py` — the pytest checks for the four run checks

## What a practice pass looks like

The practice model is the same one the runbook-copilot page uses when no key is set. It quotes one sentence from each matching section. It is not the real model.

A question that starts with "restart" becomes a proposed action, and this harness refuses it. A command that is not a restart, such as "delete old logs", is searched like a question. That is how the practice model is written.

`runs.sample.jsonl` is nine lines copied from one practice pass. It is there so you can see the shape of the file before you run anything. It is not the full list of 30.

The hand labels for this practice pass are in `labels.md`. Four of those names are also checked by `check_runs.py`. The loop-versus-graph comparison is `compare.md`.
