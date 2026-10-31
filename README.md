# copilot-evals

This repo collects real runs of [runbook-copilot](https://github.com/cianlabs/runbook-copilot) so a person can later read them and label what went wrong.

It does not score the agent yet. It asks a fixed list of questions, writes down what the agent did, and stops. The names for those later labels live in [taxonomy.md](taxonomy.md). The count column there is blank until someone fills it in by hand.

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

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

The tests use a fake model. They need no API key and make no network calls. They do need a `runbook-copilot` checkout. The practice command above creates one.

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
- `taxonomy.md` — stop reasons, `AgentError` names, action failures, and hand labels
- `runs.sample.jsonl` — a short slice of a practice pass
- `test_collect_runs.py` — the pytest checks

## What a practice pass looks like

The practice model is the same one the runbook-copilot page uses when no key is set. It quotes one sentence from each matching section. It is not the real model.

A question that starts with "restart" becomes a proposed action, and this harness refuses it. A command that is not a restart, such as "delete old logs", is searched like a question. That is how the practice model is written.

`runs.sample.jsonl` is nine lines copied from one practice pass. It is there so you can see the shape of the file before you run anything. It is not the full list of 30.

Hand-labeling the runs, filling in the taxonomy counts, and any graph experiments are later work. This repo does not do those yet.
