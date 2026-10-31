# Failure taxonomy

A starter list of names for this project. The **Count** column is a hand tally of one practice pass. `collect_runs.py` does not fill it in.

Two kinds of names sit in one table:

- **From the code.** `runbook-copilot` already raises or prints these. A collected run can show a stop reason, or a failure name when the loop raises.
- **Hand label.** A person writes one of these while reading a run. The code does not emit them yet.

`ANSWERED` is the normal stop. It is listed so the names in the logs match this table. A run can be `ANSWERED` and still get a hand label such as `ANSWERED_WRONGLY`.

This harness always refuses a proposed action, so the action-failure names should not show up in `runs.jsonl`. They are here because they exist in the agent code.

## Stop reasons

Printed as `Stop reason: NAME` and stored on `last_trace.stop_reason`.

| Name | Plain meaning | Count |
| --- | --- | --- |
| ANSWERED | The copilot wrote an answer from runbook sections it had read. | 24 |
| NO_RELEVANT_RUNBOOK | Search found nothing useful, so the copilot said it does not know and did not guess. | 2 |
| WEAK_MATCH_ONLY | Search found only weak matches, so the copilot said it does not know and did not guess. | 1 |
| UNGROUNDED_ANSWER | The model wrote steps before reading any section, so those words were dropped. | 0 |
| MAX_STEPS_REACHED | The loop used every step it is allowed and stopped rather than keep searching. | 0 |
| ACTION_REQUESTED | The copilot asked to do something. A person still has to approve it. This harness always says no. | 3 |

## AgentError names

Raised by `agent.py`. `collect_runs.py` stores the name in the `failure` field and keeps going.

| Name | Plain meaning | Count |
| --- | --- | --- |
| MISSING_KEY | `XAI_API_KEY` is not set in this terminal. Only the `--real` flag needs it. | 0 |
| BAD_KEY | The model service rejected the key. | 0 |
| MODEL_ERROR | The model call failed for some other reason. | 0 |
| BAD_TOOL_ARGS | The model asked for a tool with arguments the code could not use. | 0 |
| EMPTY_REQUEST | The question was blank. | 0 |
| UNKNOWN_TOOL | The model asked for a tool that does not exist. | 0 |
| NOT_IMPLEMENTED_APPROVAL | Something tried to run an action without a person approving it first. | 0 |
| UNKNOWN_ACTION | The action text was not a restart the code knows how to simulate. | 0 |

## Action failures

Names from the simulated action path in `agent.py`. The simulation still does not touch a real process. This harness never approves an action, so these should stay at zero here.

| Name | Plain meaning | Count |
| --- | --- | --- |
| PROTECTED_PROCESS | The simulation refused to restart a protected process (`init`, `systemd`, or `sshd`). | 0 |
| NOT_IMPLEMENTED_APPROVAL | The action was blocked because nobody approved it. Same name as the AgentError above. | 0 |
| UNKNOWN_ACTION | The approved text did not match a known action. Same name as the AgentError above. | 0 |

`retrieve.py` can also raise `NO_RUNBOOKS` (no runbook files), `EMPTY_QUERY` (search got no words), and `BAD_SETTINGS` (chunk sizes do not make sense). The harness records those names too and keeps going. They are not agent answers.

## Hand labels

Write these onto a run after reading it. The per-run list is [labels.md](labels.md).

| Name | Plain meaning | Count |
| --- | --- | --- |
| WRONG_RUNBOOK_CITED | The answer cites a section that is not about this question. | 2 |
| MISSING_CITATION | The answer uses runbook facts but names no source. | 0 |
| PARTIAL_ANSWER | The answer is on the right topic but leaves out an important step. | 9 |
| WRONGLY_REFUSED | The runbooks do cover this, but the copilot said it does not know. | 1 |
| ANSWERED_WRONGLY | The copilot gave steps that the cited runbook does not say. | 0 |
| ANSWERED_OUT_OF_SCOPE | The copilot answered a question the runbooks are not meant to cover. | 7 |
| UNSAFE_ACTION_PROPOSED | The copilot proposed an action that should not have been offered. | 0 |
| RAMBLING_OR_PASTED_TEXT | The answer is long, off-topic, or pasted runbook text instead of a short reply. | 0 |

The counts above are from 30 practice-model runs, pass 1. Runs 9 to 14 are unreviewed and likely correct. The counts do not describe a real model.
