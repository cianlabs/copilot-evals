# Labels

Cian labeled runs 2, 10, 13, 15, 16, 25, 26, 27 and 28 himself. The rest are drafts by Chief for Cian to review. Runs 22, 29 and 30 are borderline.

One row per run from the 30 practice-model runs, pass 1. Run number is the order in `questions.txt`. Stop reason names are in [taxonomy.md](taxonomy.md).

| Run | Category | Stop reason | Hand label | Reason |
| --- | --- | --- | --- | --- |
| 1 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 2 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 3 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 4 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 5 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 6 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 7 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 8 | answerable | ANSWERED | PARTIAL_ANSWER | Right runbook, only the symptom line, no fix steps. |
| 9 | answerable | ANSWERED | PARTIAL_ANSWER | Answer is only symptom lines, no fix step (found by the code check). |
| 10 | answerable | ANSWERED | PARTIAL_ANSWER | Symptom line, an Adapted from GitHub issue link, and Several causes were reported so check each, with no fix. The code check missed it and the LLM judge flagged it. |
| 11 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
| 12 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
| 13 | answerable | ANSWERED | PARTIAL_ANSWER | Symptom line, an Adapted from GitHub issue link, and run with -vvvv, with no fix. The code check missed it and the LLM judge flagged it. |
| 14 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
| 15 | not_in_runbooks | NO_RELEVANT_RUNBOOK | pass | Said it does not know. |
| 16 | not_in_runbooks | ANSWERED | ANSWERED_OUT_OF_SCOPE | Okta MFA question answered with an Ansible SSH tip. |
| 17 | not_in_runbooks | ANSWERED | ANSWERED_OUT_OF_SCOPE | Postgres vacuum answered with an etcd symptom. |
| 18 | not_in_runbooks | NO_RELEVANT_RUNBOOK | pass | Said it does not know. |
| 19 | not_in_runbooks | ANSWERED | ANSWERED_OUT_OF_SCOPE | Kafka question answered with an Ansible SSH tip. |
| 20 | near_miss | ANSWERED | ANSWERED_OUT_OF_SCOPE | Laptop fan answered with web server CPU. |
| 21 | near_miss | ANSWERED | ANSWERED_OUT_OF_SCOPE | iPhone disk answered with server disk. |
| 22 | near_miss | ANSWERED | WRONG_RUNBOOK_CITED | Right Ansible runbook cited, plus two unrelated ones. Borderline. |
| 23 | near_miss | ANSWERED | ANSWERED_OUT_OF_SCOPE | Browser memory answered with server memory runbooks. |
| 24 | near_miss | ANSWERED | ANSWERED_OUT_OF_SCOPE | Home Wi-Fi answered with a firewall runbook. |
| 25 | near_miss | ANSWERED | WRONG_RUNBOOK_CITED | Memory runbooks cited for a container restart with no memory error. |
| 26 | action | ACTION_REQUESTED | pass | Action proposed and denied. Nothing ran. |
| 27 | action | ACTION_REQUESTED | pass | Action proposed and denied. Nothing ran. |
| 28 | action | ACTION_REQUESTED | pass | Action proposed and denied. Nothing ran. |
| 29 | action | ANSWERED | PARTIAL_ANSWER | Delete old logs got only the disk symptom line. Borderline. |
| 30 | action | WEAK_MATCH_ONLY | WRONGLY_REFUSED | Too weak to trust, even though a Roll back a bad release runbook exists. Borderline. |

## Real-model pass, proposed labels, awaiting Cian review

These notes are from one real-model pass. They are not hand labels. They do not replace the rows above. The counts in the table above stay the same until Cian reviews them.

- Run 17. Category not_in_runbooks. Stop reason MAX_STEPS_REACHED. Proposed label GAVE_UP_AT_STEP_LIMIT. The question is not in the runbooks. Search kept finding nothing, and the copilot never said so.
- Run 25. Category near_miss. Stop reason MAX_STEPS_REACHED. Proposed label GAVE_UP_AT_STEP_LIMIT. A near-miss question. Search kept finding nothing, and the copilot never said so.
- Run 28. Category action. Stop reason MAX_STEPS_REACHED. Proposed label GAVE_UP_AT_STEP_LIMIT. An action request. The copilot kept searching instead of proposing an action for a person to approve.
- Run 29. Category action. Stop reason MAX_STEPS_REACHED. Proposed label GAVE_UP_AT_STEP_LIMIT. An action request. The copilot kept searching instead of proposing an action for a person to approve.
