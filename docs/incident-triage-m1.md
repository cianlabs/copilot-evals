# Milestone 1: incident-triage evaluation contract

The new read-only incident triage is implemented in the companion `runbook-copilot` branch `feature/incident-triage-m1` as `incident_triage.py`.

This first increment adds offline contract tests without modifying the pinned 30-question agent baseline or changing `collect_runs.py`.

Run both repositories side by side:

```sh
RUNBOOK_COPILOT_PATH=../runbook-copilot python -m unittest test_incident_triage_contract.py -v
```

Acceptance criteria: three unverified hypotheses, references only to supplied evidence IDs, no confirmed root cause without verification, and simulation-only action mode.

Next iteration: add labeled incident examples, retrieval quality checks, and a separate CI job that checks out the matching copilot feature branch or a pinned commit. No production actions or external calls are performed by these tests.
