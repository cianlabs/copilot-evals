#!/usr/bin/env python3
"""Offline public-incident evaluation. Labels never enter the triage input."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DATA = HERE / 'incidents/public.jsonl'
SOURCES = HERE / 'incidents/source_checks.json'
BASELINE_COMMIT = 'b00427a57596e7cac758023ea86ab0744a1a7f54'
BASELINE_FILE = HERE / 'baselines/incident_triage.py'
BASELINE_SHA256 = 'dcba49b8960eefcef4c6c1d3fb938aa3dc0c82b3ca29427c5e39d6e9e66b68b2'


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def load_cases(path=DATA, sources_path=SOURCES):
    sources = json.loads(Path(sources_path).read_text())
    if not isinstance(sources, list) or not sources:
        raise ValueError('sources must be a nonempty list')
    source_map = {}
    for source in sources:
        key = source.get('key')
        if not nonempty(key) or key in source_map:
            raise ValueError('invalid or duplicate source key')
        if source.get('status') != 200 or any(urlparse(source.get(k, '')).scheme != 'https' for k in ('url', 'final_url')):
            raise ValueError('source must have a verified HTTPS 200 response')
        if not nonempty(source.get('verified_at')) or len(source.get('sha256', '')) != 64:
            raise ValueError('source needs fetch date and body hash')
        source_map[key] = source
    cases, seen = [], set()
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('case must be an object')
            for key in ('id', 'date', 'title', 'source_key', 'source_section', 'symptom', 'impact', 'context'):
                if not nonempty(row.get(key)):
                    raise ValueError(f'{key} must be nonempty')
            if row['id'] in seen:
                raise ValueError('duplicate incident id')
            if row['source_key'] not in source_map:
                raise ValueError('unknown source')
            if type(row.get('vague')) is not bool:
                raise ValueError('vague must be boolean')
            if row.get('kind') not in ('diagnosis', 'cautious'):
                raise ValueError('unknown case kind')
            expected = row.get('expected_hypotheses')
            if not isinstance(expected, list) or any(not nonempty(x) for x in expected) or len(set(expected)) != len(expected):
                raise ValueError('expected hypotheses must be unique strings')
            if (row['kind'] == 'diagnosis') != bool(expected):
                raise ValueError('diagnosis needs labels; cautious cases must not have a single answer')
            if row.get('confirmed_root_cause', 'missing') is not None:
                raise ValueError('observations do not confirm a root cause')
            evidence = row.get('evidence')
            if not isinstance(evidence, list):
                raise ValueError('evidence must be a list')
            ids = []
            for e in evidence:
                if not isinstance(e, dict) or any(not nonempty(e.get(k)) for k in ('id', 'source', 'observation')):
                    raise ValueError('invalid evidence')
                ids.append(e['id'])
            if len(ids) != len(set(ids)):
                raise ValueError('duplicate evidence id')
            seen.add(row['id'])
            cases.append(row)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'{path}:{number}: {exc}') from exc
    if not cases:
        raise ValueError('empty incident set')
    return cases


def triage_input(case):
    # Allowlist prevents retrospective labels, titles, source URLs and context leaking.
    return dict(incident_id=case['id'], symptom=case['symptom'], impact=case['impact'],
                evidence=[dict(e) for e in case['evidence']])


def normalize(title):
    return ' '.join(title.casefold().split())


def cautious(result, evidence_ids):
    hypotheses = result.get('hypotheses', [])
    if not isinstance(hypotheses, list) or len(hypotheses) < 2:
        return False
    titles = [h.get('title') for h in hypotheses if isinstance(h, dict)]
    return (
        len(titles) == len(hypotheses) and all(nonempty(t) for t in titles)
        and len({normalize(t) for t in titles}) == len(titles)
        and 'confirmed_root_cause' in result and result['confirmed_root_cause'] is None
        and result.get('action_mode') == 'simulation_only'
        and all(h.get('status') == 'unverified'
                and isinstance(h.get('supporting_evidence_ids'), list)
                and all(isinstance(x, str) and x in evidence_ids for x in h['supporting_evidence_ids'])
                for h in hypotheses)
    )


def score(cases, predictions):
    if len(cases) != len(predictions):
        raise ValueError('prediction count must equal incident count')
    metrics = {k: {'correct': 0, 'total': 0} for k in ('top1', 'top3', 'vague_top1', 'cautious')}
    misses = []
    for case, result in zip(cases, predictions):
        if result.get('incident', {}).get('incident_id') != case['id']:
            raise ValueError('prediction incident id or order mismatch')
        if case['kind'] == 'cautious':
            good = cautious(result, {e['id'] for e in case['evidence']})
            metrics['cautious']['total'] += 1
            metrics['cautious']['correct'] += int(good)
            if not good:
                misses.append({'id': case['id'], 'reason': 'Did not keep multiple unverified hypotheses, valid references, no confirmed cause and simulation-only mode.'})
            continue
        hypotheses = result.get('hypotheses', [])
        if not isinstance(hypotheses, list) or any(not isinstance(h, dict) or not nonempty(h.get('title')) for h in hypotheses):
            raise ValueError('invalid hypothesis ranking')
        titles = [normalize(h['title']) for h in hypotheses]
        expected = {normalize(x) for x in case['expected_hypotheses']}
        first = bool(expected.intersection(titles[:1]))
        top3 = bool(expected.intersection(titles[:3]))
        for name, good in [('top1', first), ('top3', top3)] + ([('vague_top1', first)] if case['vague'] else []):
            metrics[name]['total'] += 1
            metrics[name]['correct'] += int(good)
        if not first:
            reason = ('Correct diagnosis ranked below first place.' if top3 else
                      'Top three omit ' + case['expected_hypotheses'][0] + '.')
            misses.append({'id': case['id'], 'reason': reason})
    return {'metrics': metrics, 'misses': misses}


def render(report):
    lines = ['| Overall top-1 | Overall top-3 | Vague symptom top-1 | Cautious behavior |', '| --- | --- | --- | --- |']
    def cell(name):
        m = report['metrics'][name]
        return f"{m['correct']}/{m['total']} ({100*m['correct']/m['total']:.1f}%)" if m['total'] else 'not measured (0 cases)'
    lines.append('| ' + ' | '.join(cell(k) for k in ('top1', 'top3', 'vague_top1', 'cautious')) + ' |')
    lines += ['', 'Missed incidents:', '']
    lines.extend(f"- {m['id']}: {m['reason']}" for m in report['misses'])
    if not report['misses']:
        lines.append('None.')
    return '\n'.join(lines) + '\n'


def evaluate():
    if hashlib.sha256(BASELINE_FILE.read_bytes()).hexdigest() != BASELINE_SHA256:
        raise ValueError('frozen baseline changed')
    from baselines.incident_triage import triage
    cases = load_cases()
    predictions = [triage(triage_input(c)) for c in cases]
    report = score(cases, predictions)
    report.update(baseline_commit=BASELINE_COMMIT, baseline_sha256=BASELINE_SHA256,
                  dataset_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(), predictions=predictions)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='write measured baseline and report')
    parser.add_argument('--check', action='store_true', help='fail if committed results do not reproduce')
    args = parser.parse_args()
    report = evaluate()
    rendered = render(report)
    json_text = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    if args.write:
        (HERE / 'results/public_incidents.json').write_text(json_text)
        (HERE / 'docs/public-incident-results.md').write_text(rendered)
    if args.check:
        if (HERE / 'results/public_incidents.json').read_text() != json_text or (HERE / 'docs/public-incident-results.md').read_text() != rendered:
            raise SystemExit('Committed public incident results are stale')
    print(rendered)


if __name__ == '__main__':
    main()
