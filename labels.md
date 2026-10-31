# Labels

Cian labeled runs 2, 15, 16, 25, 26, 27 and 28 himself. The rest are drafts by Chief for Cian to review. Runs 22, 29 and 30 are borderline.

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
| 10 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
| 11 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
| 12 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
| 13 | answerable | ANSWERED | unreviewed | Likely pass. Right runbooks, and they cite fix sections. |
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
