# Frozen incident triage baseline

incident_triage.py is an unchanged, byte-for-byte snapshot from cianlabs/runbook-copilot at commit b00427a57596e7cac758023ea86ab0744a1a7f54.

This copy makes the public benchmark reproducible offline without changing the older agent baseline pin. incident_eval.py checks its SHA-256 before running it. No keyword, title, sorting rule or confidence behavior was changed for this set. Only the triage function is called. It contains no action execution or model client.
