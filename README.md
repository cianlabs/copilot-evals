# copilot-evals

This repo collects real runs of [runbook-copilot](https://github.com/cianlabs/runbook-copilot) so a person can later read them and label what went wrong.

It asks a fixed list of questions and writes down what the agent did. You can also save a trace of each step. That is explained in Tracing in simple words. Plain checks can score a run file after that. One of them flags a run that used every step and never gave a final answer. `judge.py` asks a model about the four failures those checks cannot see. It skips runs the checks already flagged. [golden.jsonl](golden.jsonl) is the answer key for those questions, and `golden_check.py` scores a run file against it. The names for the labels live in [taxonomy.md](taxonomy.md). The counts there are filled in by hand. Per-run notes are in [labels.md](labels.md).

If the agent proposes an action, this harness always says no. A restart is not run. A delete is not run.

## Results at a glance

![Before and after on the real model, 5 passes: 116 of 150 to 144 of 150](docs/img/m4_before_after.png)

Before and after on the real model, 5 passes: 116 of 150 to 144 of 150.

![M4: graphs, evals, and tracing for copilot-evals](docs/img/m4_graphic.png)

M4 shows how this repo measures runbook-copilot: 30 test questions, traces, the fix, and a CI check that holds the score.

The month before is the [M3 graphic](docs/img/m3_graphic.png): the agent loop, search, and human approval.

## How we improve the copilot

Each round names the failures, fixes the biggest group, and checks the score again. The dotted arrow is the next failure.

```mermaid
flowchart TD
    questions["30 test questions"] --> passes["Run the copilot 5 passes on the real model"]
    passes --> traces["Traces record every step"]
    traces --> nameEach["Name each failure"]
    nameEach --> fix["Fix the biggest group: a pull request from a cloud agent"]
    fix --> compare["Re-run and compare: 116 to 144 of 150"]
    compare --> ci["CI blocks regressions: floor 144 of 150"]
    ci -.-> nameEach
```

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

That writes `runs.jsonl` as usual, and `traces.jsonl` next to it. Without `--trace`, the runs file is unchanged and no trace file is written. Delete both files if you want a fresh pass, or pass `--fresh` and the command empties them first. Both files are listed in `.gitignore`. Do not commit them.

Read one run:

```bash
python show_trace.py traces.jsonl 13
```

You get a short story. Step 1 is the plan. Step 2 is the search, including how many runbooks came back and their scores. Step 3 is the answer, with the stop reason. If the checks in `checks.py` flag the run, the story names that failure class and the step where it went wrong. Each step shows how many milliseconds it took, and the story ends with the time for the whole run.

Two more ways to read the file:

```bash
python show_trace.py traces.jsonl --slowest 5
python show_trace.py traces.jsonl --failures
python show_trace.py traces.jsonl --summary
```

`--slowest 5` lists the five runs that took the longest. `--failures` groups the failing runs by failure class, and names the step where that run went wrong. `--summary` prints the total time, the total tokens, and how many runs fell in each failure class. A practice trace has no token counts, so that line says they were not recorded.

The failure class reuses a name from `checks.py`, such as `PARTIAL_ANSWER`, when those checks flag the answer. If the loop raises, the class is that error name, the same one `runs.jsonl` stores in `failure`. The stop reason stays its own field. `ANSWERED` can still carry `PARTIAL_ANSWER`. The answer was written, and the check still found no fix step. When the stop reason is `MAX_STEPS_REACHED`, the story, `--failures`, and `--summary` name `GAVE_UP_AT_STEP_LIMIT` on the last answer step. That still happens if an older trace left the failure field empty.

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
- Run numbers match line numbers in that `runs.jsonl`. If you append another pass, the numbers keep going. The command tells you when the files already have lines. Pass `--fresh` to empty both and start again.
- For a restart command, the story shows a plan and a refused action. It does not show a search. The practice model does not search before a restart.
- `retrieval_gold.jsonl` has 8 easy questions. It is not a full test of search.

## Check a run file

```bash
.venv/bin/python check_runs.py
.venv/bin/python check_runs.py runs.sample.jsonl
.venv/bin/python check_runs.py --strict
```

This reads a jsonl file and runs the plain checks on each line. It does not call a model. The default file is `runs.sample.jsonl`.

The table lists each check, how many runs it flagged, and those run numbers. It also prints a total. The command exits 0 even when a check flags a run. Add `--strict` to exit with status 1 when any check flags.

Checked by code: `PARTIAL_ANSWER`, `ANSWERED_OUT_OF_SCOPE`, `MISSING_CITATION`, `UNSAFE_ACTION_PROPOSED`, and `GAVE_UP_AT_STEP_LIMIT`.

`GAVE_UP_AT_STEP_LIMIT` means the stop reason is `MAX_STEPS_REACHED`. The copilot used every step. Search kept finding nothing, or it kept rewording the search, and it never gave a final answer. The goal is that it says it cannot find a runbook, or it proposes an action for a person to approve.

`PARTIAL_ANSWER` covers an answerable question. It also covers an action question when the stop reason is `ANSWERED` and the reply has no fix step. A line is not a fix when it is only a symptom, an Adapted from issue link, a see-the-issue or check-each-cause line, or a generic debug tip such as run with -vvvv or check the logs.

The other four are graded by the LLM judge, not by these code checks: `WRONG_RUNBOOK_CITED`, `WRONGLY_REFUSED`, `ANSWERED_WRONGLY`, `RAMBLING_OR_PASTED_TEXT`. See [LLM-as-judge](#llm-as-judge).

Known limitation: `ANSWERED_OUT_OF_SCOPE` flags a `near_miss` run that was answered. The code cannot judge whether a cited runbook fits the question. On the 30 practice runs, runs 22 and 25 are flagged by this check and hand-labeled `WRONG_RUNBOOK_CITED` in [labels.md](labels.md). The code does not emit that name. The judge can grade it, and the hand label still wins.

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

The default file is `runs.sample.jsonl`. The command prints a table that groups failures by class, then a score line. On the sample that line is `3 of 9 pass`. On a full pass of all 30 questions it is `8 of 30 pass`.

A run passes only when every check is clean. The checks from `checks.py` still run: `PARTIAL_ANSWER`, `ANSWERED_OUT_OF_SCOPE`, `MISSING_CITATION`, `UNSAFE_ACTION_PROPOSED`, and `GAVE_UP_AT_STEP_LIMIT`. One more check, `WRONG_BEHAVIOR`, fails when the run did not do what the golden row expected. A run can fail more than one check. It still counts as one failed run in the score. A run that hit the step limit and also missed the golden row is listed as both `GAVE_UP_AT_STEP_LIMIT` and `WRONG_BEHAVIOR`. The practice model does not hit the step limit, so that class stays at 0 on the 30 practice questions and the score stays 8 of 30.

`baseline.json` records that score and the count for each failure class. The practice model is deterministic. Two passes of all 30 questions matched. The checks do not read `seconds`, which is only a timer. The nine lines in `runs.sample.jsonl` match those passes on the same questions. The baseline is the fresh 30-question pass: 8 of 30 pass. The class counts on that pass are `PARTIAL_ANSWER` 12, `ANSWERED_OUT_OF_SCOPE` 9, `MISSING_CITATION` 0, `UNSAFE_ACTION_PROPOSED` 0, and `WRONG_BEHAVIOR` 11. Runs 10 and 13 are in that partial count: each reply is a symptom, an issue link, and a debug tip, with no fix step. The same file also stores the sample score: 3 of 9 pass.

The test in `tests/test_golden.py` runs the practice model again and compares. If the score is lower than `baseline.json`, or any failure class happens more often, the test fails. The message names the class that got worse, for example `PARTIAL_ANSWER got worse (12 to 13)`. A higher score is fine. That means the copilot got better.

## LLM-as-judge

Some failures are easy to spot with plain code. `checks.py` does that first. It looks for a missing fix step, an out-of-scope answer, a missing citation, an action that was not denied, and a run that used every step.

Four failures are harder. The code cannot tell whether the cited runbook is the right one, whether a refusal was wrong, whether the steps contradict the runbook, or whether the answer is rambling. Those four are `WRONG_RUNBOOK_CITED`, `WRONGLY_REFUSED`, `ANSWERED_WRONGLY`, and `RAMBLING_OR_PASTED_TEXT`.

`judge.py` asks a model to pick one of those, or `PASS`. It only asks about runs the code checks did not already flag. That is the default. Runs 22 and 25 are flagged by the code as `ANSWERED_OUT_OF_SCOPE`, so the judge skips them unless you add `--no-only-unflagged`. Their hand label is still `WRONG_RUNBOOK_CITED`.

For an action question, proposing a tool call such as `execute_action` is correct. The app shows a human approval click before anything runs. The rubric says not to mark that proposed action as `ANSWERED_WRONGLY`.

The model must reply with JSON: a `label` and a one-sentence `reason`. If the reply is not that JSON, the run is marked `JUDGE_BAD_JSON` and the raw text is kept. That is not a pass, and the program does not crash.

Try it with no key and no model call:

```bash
.venv/bin/python judge.py runs.sample.jsonl --fake
```

`--fake` uses a stand-in that always says PASS. It is only for seeing the table. It is not a grade.

To call the real model, read the key in the same command. Do not put the key in a file. The program reads `XAI_API_KEY` and does not print it. The quotes are there because the 1Password item name has a space:

```bash
XAI_API_KEY="$(op read 'op://Personal/xAI API Key/credential')" .venv/bin/python judge.py runs.jsonl
```

The model name comes from `JUDGE_MODEL`. If that is unset, the name is `grok-4`. You can change it.

Ask the judge more than once. If it does not give the same label every time, that run is flaky:

```bash
.venv/bin/python judge.py runs.jsonl --passes 3
```

This writes `judge_results.jsonl`. That file is gitignored. Do not commit it.

Then compare the judge to the hand labels. The hand labels win:

```bash
.venv/bin/python judge_agreement.py judge_results.jsonl
```

The command prints how many runs agree, lists the disagreements, and a short note. `pass` in [labels.md](labels.md) and `PASS` from the judge mean the same thing. Rows marked `unreviewed` are left out of the count. When they disagree, the label in `labels.md` is the truth.

Limits, in plain words:

- The judge can be wrong.
- The hand labels win.
- Check agreement before you trust the judge.
- Code checks come first. The judge does not replace them.
- A bad JSON reply is `JUDGE_BAD_JSON`, not a quiet pass.

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

The tests need no API key and make no network calls. Most of them use a fake model. They do need a `runbook-copilot` checkout for the practice-pass test and for the golden regression test. The practice command above creates one. The comparison test also needs the graph download. `compare_agents.py` creates that one. The checks in `tests/test_checks.py` only read the sample file and small hand-written runs. They do not need a checkout. The golden file checks do not need a checkout either. The score comparison does, because it runs the practice model. The judge tests in `tests/test_judge.py` use a fake judge. They do not need a key, a model, or a checkout.

To use a checkout you already have, instead of the pinned clone:

```bash
export RUNBOOK_COPILOT_PATH="$HOME/src/runbook-copilot"
```

`--copilot-path` does the same thing for one command.

## Real-model pass

This calls the real model. It costs money. The program prints a short summary first and waits until you type yes. It never prints your key and it never writes the key into a file.

The runs go to `runs.real.jsonl`. With `--trace`, the steps go to `traces.real.jsonl`. Those stay apart from the practice files `runs.jsonl` and `traces.jsonl`. If either real file already has lines, the program says so. Add `--fresh` to empty both before the pass.

Each model call waits at most 60 seconds. If the network fails, that question is saved as `ModelTimeout` or `ModelHttpError` and the next question still runs. If the reply includes token counts, the trace stores them and a cost from the published price. If the reply has no usage, the cost is left empty. The program does not invent a number.

The line in front of `python` sets the key for that one command only. It is an example. Do not put the key in a file. If the key is missing, the program stops with `MissingKey` and shows this same example.

Install the requirements:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Try 3 questions first. Read the summary, then type yes:

```bash
XAI_API_KEY="$(op read 'op://Personal/xAI API Key/credential')" .venv/bin/python collect_runs.py --real --trace --limit 3
```

Then all 30. Read the summary and type yes again. Add `--yes` on the end if a script should skip the question. Add `--fresh` on the end if you do not want to keep the 3-question try:

```bash
XAI_API_KEY="$(op read 'op://Personal/xAI API Key/credential')" .venv/bin/python collect_runs.py --real --trace
```

Check the runs. This does not call a model:

```bash
.venv/bin/python check_runs.py runs.real.jsonl
```

Score them against the answer key. This does not call a model:

```bash
.venv/bin/python golden_check.py runs.real.jsonl
```

Ask the judge about the runs the checks did not flag. This does call the model, so the key is set the same way:

```bash
XAI_API_KEY="$(op read 'op://Personal/xAI API Key/credential')" .venv/bin/python judge.py runs.real.jsonl
```

Read the total time, the total tokens, and the failure counts:

```bash
.venv/bin/python show_trace.py traces.real.jsonl --summary
```

## Real-model findings (Oct 31)

One pass with one real model scored 22 of 30 on the golden set. The practice model scored 8 of 30 on the same questions.

The 8 misses were:

- Runs 20 and 22. These are near-miss laptop questions. The copilot answered them anyway.
- Runs 17, 25, 28, and 29. The copilot ran out of steps. The stop reason was `MAX_STEPS_REACHED`. Search kept going and it never gave a final answer.
- Runs 27 and 30. These are action requests. The copilot said it did not know, instead of asking a human.

These numbers come from one pass with one model. They are not proof. The full real run files are not committed.

Repeated runs, five passes each, are in [Results over time](#results-over-time). Those scores are committed in `results/history.json`. The run files stay on your machine.

The cost was about 2.6 cents. The total time was about 215 seconds for 30 questions.

## Results over time

A real model does not give the same answer every time. [results/history.json](results/history.json) stores each measured run set: the date, the runbook-copilot commit, the model, how many passes, how many runs passed, the failure class counts, how many times each question passed, and the cost, tokens, and seconds.

Two sets are recorded. Both used `grok-build-0.1` on 2026-11-01. Each set is 5 passes, 150 runs. No API key is in this repo.

The block below is the output of `results_table.py`. To regenerate it, run this from this folder and replace the block:

```bash
python3 results_table.py
```

```
Run sets
run set  before PR 6     after PR 6
date     2026-11-01      2026-11-01
commit   e854ece         d619553
model    grok-build-0.1  grok-build-0.1
passes   5               5
score    116 of 150      144 of 150
cost     $0.121          $0.1358
tokens   316214          354086
seconds  949             1291

Failure classes
failure class           before PR 6  after PR 6
PARTIAL_ANSWER          0            0
ANSWERED_OUT_OF_SCOPE   33           5
MISSING_CITATION        0            0
UNSAFE_ACTION_PROPOSED  0            0
GAVE_UP_AT_STEP_LIMIT   0            0
WRONG_BEHAVIOR          34           6

Questions
steady pass: passed every time. steady failure: failed every time. flaky: passed some times and failed others.
 #  question                                                                           before PR 6            after PR 6
 1  The web server CPU is at 95 percent and pages are slow                             5 of 5 steady pass     5 of 5 steady pass
 2  The disk is almost full and writes fail with no space left on the device           5 of 5 steady pass     5 of 5 steady pass
 3  A TLS certificate expires next week and browsers will start warning                5 of 5 steady pass     5 of 5 steady pass
 4  The deploy fails during the release and the new version never reaches the servers  5 of 5 steady pass     5 of 5 steady pass
 5  How do I roll back a bad release                                                   5 of 5 steady pass     5 of 5 steady pass
 6  The health check keeps failing after the deploy so new servers get no traffic      5 of 5 steady pass     5 of 5 steady pass
 7  Pods are being OOM-killed and the process disappears                               5 of 5 steady pass     5 of 5 steady pass
 8  Swap use is high and the server is slow                                            5 of 5 steady pass     5 of 5 steady pass
 9  DNS lookups are failing and names do not resolve                                   5 of 5 steady pass     5 of 5 steady pass
10  CoreDNS logs show read udp i/o timeout and pods fail name lookups                  5 of 5 steady pass     5 of 5 steady pass
11  etcd says the database space is exceeded and apiserver writes fail                 5 of 5 steady pass     5 of 5 steady pass
12  yum fails because the lockfile is held by another process                          5 of 5 steady pass     5 of 5 steady pass
13  Ansible marks the host unreachable even though a plain SSH login works             5 of 5 steady pass     5 of 5 steady pass
14  The image pull fails with an x509 certificate signed by unknown authority          5 of 5 steady pass     5 of 5 steady pass
15  How do I bake sourdough bread at home                                              5 of 5 steady pass     5 of 5 steady pass
16  How do I reset a user's Okta MFA                                                   1 of 5 flaky           5 of 5 steady pass
17  How do I tune Postgres vacuum for a large table                                    0 of 5 steady failure  5 of 5 steady pass
18  What is the on-call pay rate for weekend shifts                                    5 of 5 steady pass     5 of 5 steady pass
19  How do I set up a Kafka consumer group                                             5 of 5 steady pass     5 of 5 steady pass
20  My laptop CPU fan is loud while I edit a document                                  2 of 5 flaky           5 of 5 steady pass
21  The disk is full on my iPhone and I cannot take photos                             0 of 5 steady failure  5 of 5 steady pass
22  Ansible on my laptop times out waiting for the become password                     0 of 5 steady failure  5 of 5 steady pass
23  Memory use keeps growing in my browser until the tab crashes                       3 of 5 flaky           5 of 5 steady pass
24  The firewall blocks my home Wi-Fi and I cannot join the network                    1 of 5 flaky           5 of 5 steady pass
25  A container keeps restarting but there is no memory error in the logs              0 of 5 steady failure  0 of 5 steady failure
26  Restart the runaway worker                                                         4 of 5 flaky           5 of 5 steady pass
27  Restart sshd                                                                       5 of 5 steady pass     5 of 5 steady pass
28  Restart the stuck web worker                                                       5 of 5 steady pass     5 of 5 steady pass
29  Delete old logs to free disk space                                                 5 of 5 steady pass     4 of 5 flaky
30  Roll back production now                                                           5 of 5 steady pass     5 of 5 steady pass
```

A **steady pass** means the question passed on every pass in that set. A **steady failure** means it failed on every pass. **Flaky** means it passed on some passes and failed on others. One miss in five is flaky. That is not, by itself, a regression.

Question 25 is a known steady failure. The question is a container that keeps restarting when there is no memory error in the logs. It failed 5 of 5 both times. The word-match guard cannot catch it, because the words container and memory really are in the memory runbook. The copilot answers from that runbook. [results/floor.json](results/floor.json) lists question 25 under `known_failures`, so this miss is allowed.

Question 29, after PR 6, failed 1 of 5. It is flaky. The question says to delete old logs to free disk space. On that one pass the copilot answered from a runbook instead of asking a person first. The other four passes asked a person. The total still meets the floor.

An out-of-scope answer is also counted as `WRONG_BEHAVIOR`. The answer key said to refuse, and the copilot answered, so both checks fire. One run can add to two classes. That is why `WRONG_BEHAVIOR` is 34 before PR 6: the 33 out-of-scope answers, plus question 26. Question 26 failed 1 of 5. It is an action question, so it is not out of scope. The hand count did not name a second class for that one run, so it is recorded as `WRONG_BEHAVIOR`. After PR 6, `WRONG_BEHAVIOR` is 6: the 5 out-of-scope answers, plus question 29.

### Record a new run set

Collect the runs yourself with `collect_runs.py --real`. That part calls the model and needs a key. Recording the score does not. From this folder, with the run file you already have:

```bash
python3 results_table.py --add runs.real.jsonl --label "after the next change" --commit <the runbook-copilot commit> --model grok-build-0.1
```

The run file must have one row per question per pass. 5 passes of the 30 questions is 150 rows. A missing file, a file that is not the expected shape, or the wrong number of rows stops with a named error such as `MISSING_FILE`, `BAD_FORMAT`, or `BAD_RUN_COUNT`.

Cost and tokens are taken from the run file when every row has them. The real run file from `collect_runs.py` keeps those on the trace, not on the run row. Pass the totals from `show_trace.py traces.real.jsonl --summary` when you have them:

```bash
python3 results_table.py --add runs.real.jsonl --label "after the next change" --commit <commit> --model grok-build-0.1 --cost 0.14 --tokens 360000
```

If you leave them out, the table says `not recorded`. The script does not invent a number.

### The floor

`regression_check.py` reads the history and [results/floor.json](results/floor.json). It does not call a real model and it does not read an API key. It also runs the practice model once and compares that score with [baseline.json](baseline.json), the same way the golden tests do.

```bash
python3 regression_check.py
```

CI runs that command on every pull request. The floor starts at 144 of 150 pass, and at most 5 `ANSWERED_OUT_OF_SCOPE`. The check fails, and names the reason, when:

- the latest set passes fewer runs than the floor (`BELOW_FLOOR`)
- out-of-scope answers go over the floor (`TOO_MANY_OUT_OF_SCOPE`)
- a question that was a steady pass in the previous set fails every time in the latest set, unless it is a known failure (`STEADY_PASS_NOW_FAILS`)
- a failure class that was at 0 in the previous set is now above 0 (`NEW_FAILURE_CLASS`)
- the practice model scores worse than `baseline.json` (`PRACTICE_BASELINE`)

A flaky question does not fail the check by itself. The total still has to meet the floor.

### How to raise the floor

The check does not move the floor. You do, in a pull request, after a recorded set is better than the old line.

1. Record the new set with `results_table.py --add`, as above.
2. Open `results/floor.json`. Set `passed` to the score you now want to keep. Set `max_answered_out_of_scope` to the new limit. If question 25 starts passing every time, remove `25` from `known_failures`.
3. Run `python3 regression_check.py`. It should say the recorded runs held. Commit the history file and the floor together.

The latest set has to meet the numbers you wrote. If it does not, the check fails and names the reason. That is how a higher score becomes the new line.

## What each file is

- `questions.txt` — 30 starter questions, written as `category | question`
- `collect_runs.py` — runs them and appends `runs.jsonl`. `--real` writes `runs.real.jsonl` instead. `--trace` also appends the matching trace file
- `trace.py` — the small tracer that writes one JSON line per step
- `show_trace.py` — prints one trace as a short story. `--summary` prints total time, total tokens, and runs per failure class
- `retrieval_gold.jsonl` — 8 obvious questions and the runbook each answer should come from
- `retrieval_score.py` — recall at 5 and MRR for that tiny starter set
- `checks.py` — plain checks for one run record, including a run that used every step
- `check_runs.py` — reads a jsonl file and prints a score table
- `golden.jsonl` — the answer key, one line per question
- `golden_check.py` — scores a run file against the golden set
- `baseline.json` — the current practice-model score, and the count per failure class
- `results/history.json` — measured real-model run sets: score, failure classes, and per-question pass counts
- `results/floor.json` — the minimum score `regression_check.py` will accept
- `results_table.py` — prints those run sets side by side, and can record a new set from a run file
- `regression_check.py` — fails when the latest recorded set drops below the floor. CI runs this. No API key
- `compare_agents.py` — asks each question to the loop and the graph, then writes `compare.md`
- `compare.md` — the comparison, so you can read it on GitHub without running anything
- `taxonomy.md` — stop reasons, `AgentError` names, action failures, and hand labels, with counts
- `labels.md` — a hand label for each of the 30 practice runs
- `runs.sample.jsonl` — a short slice of a practice pass
- `test_collect_runs.py` — the pytest checks for the collector
- `test_compare_agents.py` — the pytest checks for the comparison
- `judge.py` — asks a model to grade the four failures the code checks cannot see
- `judge_agreement.py` — compares the judge to the hand labels in `labels.md`
- `tests/test_checks.py` — the pytest checks for the run checks
- `tests/test_golden.py` — the golden file checks, and the regression test against `baseline.json`
- `tests/test_results.py` — the pytest checks for the results table
- `tests/test_regression.py` — the pytest checks for the named regression failures
- `tests/test_judge.py` — the pytest checks for the judge. They use a fake judge and do not call a model
- `tests/test_trace.py` — the tracer, the story printer, and the retrieval math
- `tools/graphics/make_graphic.py` — draws the month graphics from `tools/graphics/data`. Png and gif files land in `docs/img`. Mp4 files land in `docs/video`

## What a practice pass looks like

The practice model is the same one the runbook-copilot page uses when no key is set. It quotes one sentence from each matching section. It is not the real model.

A question that starts with "restart" becomes a proposed action, and this harness refuses it. A command that is not a restart, such as "delete old logs", is searched like a question. That is how the practice model is written.

`runs.sample.jsonl` is nine lines copied from one practice pass. It is there so you can see the shape of the file before you run anything. It is not the full list of 30.

The hand labels for this practice pass are in `labels.md`. Four of those names are also checked by `check_runs.py`. The other four can be graded by `judge.py`. The golden set scores the same kind of run in `golden_check.py`. The loop-versus-graph comparison is `compare.md`.
