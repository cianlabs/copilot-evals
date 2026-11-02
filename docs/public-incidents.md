# Public incident evaluation

Run `python incident_eval.py` offline. Use `python incident_eval.py --check` to check the committed results, or `--write` to regenerate them. CI reproduces the report and runs the loader and scoring tests without contacting incident sites or a model. All actions stay simulated.

The set has 30 distinct public incidents, 15 with customer-style vague symptoms and four cautious cases. Main did not contain a 12-incident public set when this work began; this adds a separate benchmark beside the existing 30-question practice evaluation. The older evaluation, ranking code and regression floor are unchanged.

The baseline is the frozen, unchanged companion triage module at b00427a57596e7cac758023ea86ab0744a1a7f54. Its file hash is checked before evaluation. Full predictions and dataset hash are in results/public_incidents.json. [The measured table and every miss](public-incident-results.md) are generated together from those predictions.

## Sources and inputs

[SOURCES.md](../SOURCES.md) names the public page, date, section and observed impact for every case. Twenty-two unique first-party pages cover 30 distinct events. Several monthly reports describe more than one incident. Every page was fetched with HTTP GET and read to verify both impact and labels. All cited URLs returned 200. Dead paths were left out. Fetch dates, resolved URLs and HTML hashes are in incidents/source_checks.json.

`python verify_incident_sources.py` re-fetches every page and checks that each named section is still present. This is an explicit online check, separate from offline CI. Section matching alone cannot verify a summary: people must read changed pages. `--write` refreshes the fetch receipts after review. A later page edit can change a hash without invalidating an incident.

The symptom, impact and one paraphrased user-visible observation go to the agent. Retrospective causes, source URLs, section names, dates, case kind and answer labels do not. Vague symptoms contain no cause hints or technical diagnoses. They are authored paraphrases of reported user impact, not actual customer quotations. Evidence remains equally sparse across both subsets. No diagnostic logs or checks are invented.

## Scoring rules

Overall top-1 and top-3 measure specific incident diagnoses across the 26 cases with a published mechanism label. A correct unverified hypothesis gets credit; the agent need not assert a confirmed cause. The first or first three hypothesis titles must match one accepted label after case and whitespace normalization. There is no fuzzy substring or model judge. Expected labels can list reviewed equivalent titles, but broad investigation paths do not count as a specific mechanism. The frozen baseline cannot name any of these 26 mechanisms. Its zero score measures that vocabulary gap as well as ranking failure; it does not show that all its investigation paths are useless. No new diagnosis vocabulary or ranking rules were added to fit the set.

Vague symptom accuracy is top-1 on the 13 diagnosable vague cases. The other two vague cases belong to the cautious subset. Cautious cases are excluded from diagnosis denominators because choosing one retrospective cause would be misleading. Counts are printed with every percentage.

Cautious behavior is scored separately on four cases: at least two distinct hypotheses in ranked list order, every status unverified, all referenced evidence IDs valid, an explicitly empty confirmed root cause, and simulation-only action mode. A missing confirmed-cause field fails. This checks restraint and output structure, not whether the hypotheses are relevant or the ordering is useful. Always abstaining can pass this subset and still get zero diagnosis accuracy. This limitation is visible in the current result.

PUB-04 still investigates CPU starvation after multiple mitigation changes. PUB-19 uses only an initial October 2018 update rather than a later causal analysis. PUB-23 has two independent overlapping failures. PUB-25 explicitly describes uncertainty about the electrical sequence as well as hidden service dependencies. Their context explains why no single cause should be confirmed from the supplied observations.

## Limits

These examples are selected public reports from three providers, heavily weighted toward GitHub. They are not a random sample of real support requests. Reports are written after the event, and their summaries are selected by a person. User-visible symptoms usually cannot identify a cause by themselves. Even the 26 diagnosis labels are retrospective targets, not proof available to the agent.

The current code ignores the symptom and impact when ranking; it only matches keywords in evidence observations and always returns the same three investigation paths. The vague score is therefore a subset score, not evidence that vague wording caused the misses. A matched word does not establish causation. Exact title scoring can reject a valid differently worded answer; review aliases before using another agent. These scores do not measure a live model, diagnosis from real logs, a successful repair, or production safety. Nothing is restarted, deleted or changed by this benchmark.
