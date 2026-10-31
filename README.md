# copilot-evals

This repo collects real runs of [runbook-copilot](https://github.com/cianlabs/runbook-copilot) so a person can later read them and label what went wrong.

It asks a fixed list of questions and writes down what the agent did. You can also save a trace of each step. That is explained in Tracing in simple words. Four plain checks can score a run file after that. [golden.jsonl](golden.jsonl) is the answer key for those questions, and `golden_check.py` scores a run file against it. The names for the labels live in [taxonomy.md](taxonomy.md). The counts there are filled in by hand. Per-run notes are in [labels.md](labels.md).

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

To also write a step-by-step trace, add `--trace`. See Tracing in simple words below.

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

## Tracing in simple words

A trace is a diary of one question. Each step is one line in `traces.jsonl`. The lines of one run share a short id, so they stay together. The run number is the same number as that line in `runs.jsonl`. Run 13 in the trace is run 13 in the runs file, when both files came from the same pass.

The picture below is the loop the practice model walks. Plan, then search, then answer. A restart command has an action step instead of a search. This harness still says no. Nothing is restarted.

```
        question
           |
           v
     +----------+      +----------+      +----------+
     |   plan   | ---> |  search  | ---> |  answer  |
     +----------+      +----------+      +----------+
           |                |                  |
           +----------------+------------------+
                            |
                            v
                      traces.jsonl
                  (one line per step)
```

Make a trace with the practice model. This does not call a model on the internet and does not need an API key:

```bash
.venv/bin/python collect_runs.py --trace
```

That writes `runs.jsonl` as usual, and `traces.jsonl` next to it. Without `--trace`, the runs file is unchanged and no trace file is written. Delete both files if you want a fresh pass. Both files are listed in `.gitignore`. Do not commit them.

Read one run:

```bash
python show_trace.py traces.jsonl 13
```

You get a short story. Step 1 is the plan. Step 2 is the search, including how many runbooks came back and their scores. Step 3 is the answer, with the stop reason. If the checks in `checks.py` flag the run, the story names that failure class and the step where it went wrong. Each step shows how many milliseconds it took, and the story ends with the time for the whole run.

Two more ways to read the file:

```bash
python show_trace.py traces.jsonl --slowest 5
python show_trace.py traces.jsonl --failures
```

`--slowest 5` lists the five runs that took the longest. `--failures` groups the failing runs by failure class, and names the step where that run went wrong.

The failure class reuses a name from `checks.py`, such as `PARTIAL_ANSWER`, when those checks flag the answer. If the loop raises, the class is that error name, the same one `runs.jsonl` stores in `failure`. The stop reason stays its own field. `ANSWERED` can still carry `PARTIAL_ANSWER`. The answer was written, and the check still found no fix step.

A small retrieval score sits beside the trace, because a trace shows what search returned and this asks a narrower question. For a few answerable questions, was the right runbook in the top 5 hits?

`golden.jsonl` does not name the right runbook, so `retrieval_gold.jsonl` adds an optional `expected_runbook` on a new file. There are 8 rows. They were picked from questions whose practice-model answer cites a runbook that obviously matches, using `runs.sample.jsonl` and one practice pass. Some rows also name a section, because that file holds more than one topic. `sample_runbook.txt` is one of those files.

```bash
.venv/bin/python retrieval_score.py
```

It prints recall at 5 and MRR. Recall at 5 is the share of these questions where the right runbook was in the first 5 search hits. MRR (mean reciprocal rank) is stricter. First place scores 1, second place scores 1/2, third place scores 1/3, and a miss scores 0. MRR is the average of those scores. This is a tiny starter set, not a full measure. A perfect score only means search found these obvious runbooks. It does not grade the other questions.

Honest limits:

- The trace is a file on this machine. There is no account, no Langfuse, and no paid service.
- It does not call a model on the internet. The command above uses the practice model.
- The trace never stores an API key or environment variables. It stores runbook titles and scores, not the page text.
- Step times are the model call and the search. The whole-run time is the same clock as `seconds` in `runs.jsonl`. Adding the step times may not equal the whole run, because the loop does a little more work in between.
- The vendored loop does not hand over every score, or a timer for each step. `--trace` wraps the search tool and the model call inside `collect_runs.py`. The runbook-copilot code is not edited. The wrappers call the real functions and return the same values. Without `--trace`, those wrappers are not installed.
- Run numbers match line numbers in that `runs.jsonl`. If you append another pass, the numbers keep going. Delete both files to start again.
- For a restart command, the story shows a plan and a refused action. It does not show a search. The practice model does not search before a restart.
- `retrieval_gold.jsonl` has 8 easy questions. It is not a full test of search.

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

## Golden set

`golden.jsonl` is the answer key. It has one line for each of the 30 questions, in the same order as `questions.txt`. Each line says what the copilot should have done, and one short sentence saying why.

The `expected` field is one of three words:

- `ANSWER_WITH_CITATION` — answer from a runbook and name the section. These are the `answerable` questions.
- `REFUSE_NOT_IN_RUNBOOKS` — say it does not know. These are the `not_in_runbooks` questions. These are also the `near_miss` questions, unless a hand label in [labels.md](labels.md) says that question was actually answerable.
- `ASK_HUMAN_FOR_ACTION` — ask a person before doing anything. These are the `action` questions. The harness still says no. Nothing is restarted and nothing is deleted.

A near miss only sounds like a runbook. The situation is a different one. A hand label counts as "actually answerable" when it is `PARTIAL_ANSWER` or `WRONGLY_REFUSED`. None of the six near-miss rows have those labels, so all six stay a refusal. Run 22 is the closest call. Its note says the Ansible page was cited along with two unrelated ones, and the hand label is still `WRONG_RUNBOOK_CITED`.

Score a run file. This does not call a model and does not need an API key:

```bash
.venv/bin/python golden_check.py
.venv/bin/python golden_check.py runs.sample.jsonl
```

The default file is `runs.sample.jsonl`. The command prints a table that groups failures by class, then a score line. On the sample that line is `3 of 9 pass`. On a full pass of all 30 questions it is `10 of 30 pass`.

A run passes only when every check is clean. The four checks from `checks.py` still run: `PARTIAL_ANSWER`, `ANSWERED_OUT_OF_SCOPE`, `MISSING_CITATION`, and `UNSAFE_ACTION_PROPOSED`. One more check, `WRONG_BEHAVIOR`, fails when the run did not do what the golden row expected. A run can fail more than one check. It still counts as one failed run in the score.

`baseline.json` records that score and the count for each failure class. The practice model is deterministic. Two passes of all 30 questions matched. The checks do not read `seconds`, which is only a timer. The nine lines in `runs.sample.jsonl` match those passes on the same questions. The baseline is the fresh 30-question pass: 10 of 30 pass. The class counts on that pass are `PARTIAL_ANSWER` 10, `ANSWERED_OUT_OF_SCOPE` 9, `MISSING_CITATION` 0, `UNSAFE_ACTION_PROPOSED` 0, and `WRONG_BEHAVIOR` 11. The same file also stores the sample score: 3 of 9 pass.

The test in `tests/test_golden.py` runs the practice model again and compares. If the score is lower than `baseline.json`, or any failure class happens more often, the test fails. The message names the class that got worse, for example `PARTIAL_ANSWER got worse (10 to 12)`. A higher score is fine. That means the copilot got better.

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

The tests need no API key and make no network calls. Most of them use a fake model. They do need a `runbook-copilot` checkout for the practice-pass test and for the golden regression test. The practice command above creates one. The comparison test also needs the graph download. `compare_agents.py` creates that one. The checks in `tests/test_checks.py` only read the sample file and small hand-written runs. They do not need a checkout. The golden file checks do not need a checkout either. The score comparison does, because it runs the practice model.

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
- `collect_runs.py` — runs them and appends `runs.jsonl`. `--trace` also appends `traces.jsonl`
- `trace.py` — the small tracer that writes one JSON line per step
- `show_trace.py` — prints one trace as a short story
- `retrieval_gold.jsonl` — 8 obvious questions and the runbook each answer should come from
- `retrieval_score.py` — recall at 5 and MRR for that tiny starter set
- `checks.py` — four plain checks for one run record
- `check_runs.py` — reads a jsonl file and prints a score table
- `golden.jsonl` — the answer key, one line per question
- `golden_check.py` — scores a run file against the golden set
- `baseline.json` — the current practice-model score, and the count per failure class
- `compare_agents.py` — asks each question to the loop and the graph, then writes `compare.md`
- `compare.md` — the comparison, so you can read it on GitHub without running anything
- `taxonomy.md` — stop reasons, `AgentError` names, action failures, and hand labels, with counts
- `labels.md` — a hand label for each of the 30 practice runs
- `runs.sample.jsonl` — a short slice of a practice pass
- `test_collect_runs.py` — the pytest checks for the collector
- `test_compare_agents.py` — the pytest checks for the comparison
- `tests/test_checks.py` — the pytest checks for the four run checks
- `tests/test_golden.py` — the golden file checks, and the regression test against `baseline.json`
- `tests/test_trace.py` — the tracer, the story printer, and the retrieval math

## What a practice pass looks like

The practice model is the same one the runbook-copilot page uses when no key is set. It quotes one sentence from each matching section. It is not the real model.

A question that starts with "restart" becomes a proposed action, and this harness refuses it. A command that is not a restart, such as "delete old logs", is searched like a question. That is how the practice model is written.

`runs.sample.jsonl` is nine lines copied from one practice pass. It is there so you can see the shape of the file before you run anything. It is not the full list of 30.

The hand labels for this practice pass are in `labels.md`. Four of those names are also checked by `check_runs.py`. The golden set scores the same kind of run in `golden_check.py`. The loop-versus-graph comparison is `compare.md`.
