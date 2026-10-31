# Old loop compared with the new graph

Each question in `questions.txt` was asked once to two versions of runbook-copilot.

- The old version is the loop. Its function is `run_agent` in `agent.py`.
- The new version is the graph. Its function is `run_graph` in `graph_agent.py`.

The graph code is on the branch `cursor/graph-agent-loop-86f9` (commit `b3358854f835761fc7a74de607b5ba2aeb11e673`). That branch is not merged. Both versions in this report came from that download, because the branch keeps the old loop and adds the graph next to it. The download sits in `.vendor-graph/` and is not part of this repo.

How they were asked:

- Practice model only. That is the built-in stand-in. It reads the local runbooks.
- No API key.
- No call to a model on the internet.
- If either version asked to do something, the answer was no. Nothing was restarted or deleted.
- Logging was turned off, so no `agent.log` was written.

Stop-reason names are explained in [taxonomy.md](taxonomy.md).

## Summary

- Questions asked: 30
- Same stop reason: 30
- Different stop reason: 0
- Cited the same sections: 30
- Cited different sections: 0

The two versions behaved identically. For every question, they stopped for the same reason and cited the same runbook sections.

## Results

Number is the order in `questions.txt`, skipping blank lines and comments. Category is the label on that line. Same or different is only about the stop reason. Graph node path is the list of boxes the new version walked. The old loop does not have boxes, so that column is only for the graph. Cited sources matched is yes when both versions named the same runbook sections, in the same order.

| Number | Category | Question | Loop stop reason | Graph stop reason | Same or different | Graph node path | Cited sources matched |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | answerable | The web server CPU is at 95 percent and pages are slow | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 2 | answerable | The disk is almost full and writes fail with no space left on the device | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 3 | answerable | A TLS certificate expires next week and browsers will start warning | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 4 | answerable | The deploy fails during the release and the new version never reaches the servers | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 5 | answerable | How do I roll back a bad release | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 6 | answerable | The health check keeps failing after the deploy so new servers get no traffic | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 7 | answerable | Pods are being OOM-killed and the process disappears | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 8 | answerable | Swap use is high and the server is slow | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 9 | answerable | DNS lookups are failing and names do not resolve | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 10 | answerable | CoreDNS logs show read udp i/o timeout and pods fail name lookups | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 11 | answerable | etcd says the database space is exceeded and apiserver writes fail | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 12 | answerable | yum fails because the lockfile is held by another process | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 13 | answerable | Ansible marks the host unreachable even though a plain SSH login works | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 14 | answerable | The image pull fails with an x509 certificate signed by unknown authority | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 15 | not_in_runbooks | How do I bake sourdough bread at home | NO_RELEVANT_RUNBOOK | NO_RELEVANT_RUNBOOK | same | PLAN → SEARCH → CHECK → IDK | yes |
| 16 | not_in_runbooks | How do I reset a user's Okta MFA | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 17 | not_in_runbooks | How do I tune Postgres vacuum for a large table | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 18 | not_in_runbooks | What is the on-call pay rate for weekend shifts | NO_RELEVANT_RUNBOOK | NO_RELEVANT_RUNBOOK | same | PLAN → SEARCH → CHECK → IDK | yes |
| 19 | not_in_runbooks | How do I set up a Kafka consumer group | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 20 | near_miss | My laptop CPU fan is loud while I edit a document | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 21 | near_miss | The disk is full on my iPhone and I cannot take photos | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 22 | near_miss | Ansible on my laptop times out waiting for the become password | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 23 | near_miss | Memory use keeps growing in my browser until the tab crashes | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 24 | near_miss | The firewall blocks my home Wi-Fi and I cannot join the network | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 25 | near_miss | A container keeps restarting but there is no memory error in the logs | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 26 | action | Restart the runaway worker | ACTION_REQUESTED | ACTION_REQUESTED | same | PLAN → ACTION_GATE | yes |
| 27 | action | Restart sshd | ACTION_REQUESTED | ACTION_REQUESTED | same | PLAN → ACTION_GATE | yes |
| 28 | action | Restart the stuck web worker | ACTION_REQUESTED | ACTION_REQUESTED | same | PLAN → ACTION_GATE | yes |
| 29 | action | Delete old logs to free disk space | ANSWERED | ANSWERED | same | PLAN → SEARCH → CHECK → ANSWER → CHECK → ANSWER | yes |
| 30 | action | Roll back production now | WEAK_MATCH_ONLY | WEAK_MATCH_ONLY | same | PLAN → SEARCH → CHECK → IDK | yes |

A question in the action group can still stop with something other than ACTION_REQUESTED. The practice model only treats a restart as something to do. Other commands are searched like a normal question. Both versions use that same practice model, so this is not a difference between them.

## Differences

None. The stop reasons matched, and the cited sections matched, on every question.
