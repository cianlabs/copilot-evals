"""Loader and score behavior, including wrong and overconfident predictions."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
import incident_eval as ev


@pytest.fixture
def cases():
    return ev.load_cases()


def prediction(case, titles, **changes):
    result = dict(incident={'incident_id': case['id']},
                  hypotheses=[dict(title=t, status='unverified', supporting_evidence_ids=[]) for t in titles],
                  confirmed_root_cause=None, action_mode='simulation_only')
    result.update(changes)
    return result


def test_real_set_balance_provenance_and_frozen_code(cases):
    assert len(cases) == 30
    assert sum(c['vague'] for c in cases) == 15
    assert sum(c['kind'] == 'cautious' for c in cases) == 4
    assert hashlib.sha256(ev.BASELINE_FILE.read_bytes()).hexdigest() == ev.BASELINE_SHA256
    sources = json.loads(ev.SOURCES.read_text())
    assert {c['source_key'] for c in cases} == {s['key'] for s in sources}
    links = set(__import__('re').findall(r'\]\((https://[^)]+)\)', (ev.HERE / 'SOURCES.md').read_text()))
    assert links == {s['url'] for s in sources}


@pytest.mark.parametrize('change', [
    {'id': ''}, {'vague': 'yes'}, {'kind': 'other'}, {'source_key': 'missing'},
    {'expected_hypotheses': []}, {'expected_hypotheses': ['x', 'x']},
    {'confirmed_root_cause': 'guess'}, {'evidence': [{'id': 'x'}]},
    {'evidence': [dict(id='x', source='s', observation='o')]*2},
])
def test_loader_rejects_bad_cases(tmp_path, cases, change):
    row = dict(cases[0], **change)
    path = tmp_path / 'bad.jsonl'
    path.write_text(json.dumps(row) + '\n')
    with pytest.raises(ValueError, match=':1:'):
        ev.load_cases(path)


@pytest.mark.parametrize('text', ['', 'not json', '[]'])
def test_loader_rejects_empty_and_malformed(tmp_path, text):
    path = tmp_path / 'bad.jsonl'
    path.write_text(text)
    with pytest.raises(ValueError):
        ev.load_cases(path)


def test_duplicate_case_rejected(tmp_path, cases):
    path = tmp_path / 'bad.jsonl'
    path.write_text((json.dumps(cases[0]) + '\n')*2)
    with pytest.raises(ValueError, match='duplicate incident'):
        ev.load_cases(path)


@pytest.mark.parametrize('change', [{'status': 404}, {'verified_at': ''}, {'sha256': ''}, {'final_url': 'http://example.com'}])
def test_unverified_source_rejected(tmp_path, change):
    sources = json.loads(ev.SOURCES.read_text())
    sources[0].update(change)
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps(sources))
    with pytest.raises(ValueError):
        ev.load_cases(sources_path=path)


def test_label_leakage_and_input_mutation(cases):
    case = cases[0]
    original = copy.deepcopy(case)
    supplied = ev.triage_input(case)
    assert set(supplied) == {'incident_id', 'symptom', 'impact', 'evidence'}
    assert case['reference_cause'] not in json.dumps(supplied)
    supplied['evidence'][0]['observation'] = 'changed'
    assert case == original


def test_top_k_vague_and_cautious_denominators(cases):
    rows = [copy.deepcopy(cases[0]), copy.deepcopy(cases[2]), copy.deepcopy(cases[3])]
    a, b = rows[0]['expected_hypotheses'][0], rows[1]['expected_hypotheses'][0]
    predictions = [prediction(rows[0], ['wrong', a]), prediction(rows[1], [b]), prediction(rows[2], ['first', 'second'])]
    result = ev.score(rows, predictions)
    assert result['metrics'] == dict(top1=dict(correct=1,total=2), top3=dict(correct=2,total=2),
                                   vague_top1=dict(correct=0,total=1), cautious=dict(correct=1,total=1))
    assert result['misses'] == [{'id': rows[0]['id'], 'reason': 'Correct diagnosis ranked below first place.'}]


def test_fourth_place_is_not_top_three_and_normalized_match(cases):
    c = cases[0]
    label = c['expected_hypotheses'][0]
    assert ev.score([c], [prediction(c, ['wrong', 'other', 'third', label])])['metrics']['top3']['correct'] == 0
    assert ev.score([c], [prediction(c, ['  ' + label.upper() + '  '])])['metrics']['top1']['correct'] == 1


@pytest.mark.parametrize('changes', [
    {'confirmed_root_cause': 'guessed'}, {'action_mode': 'execute'},
    {'hypotheses': []}, {'hypotheses': [dict(title='same',status='unverified',supporting_evidence_ids=[])]*2},
    {'hypotheses': [dict(title='a',status='confirmed',supporting_evidence_ids=[]),dict(title='b',status='unverified',supporting_evidence_ids=[])]},
    {'hypotheses': [dict(title='a',status='unverified',supporting_evidence_ids=['invented']),dict(title='b',status='unverified',supporting_evidence_ids=[])]},
])
def test_caution_rejects_confident_unsafe_or_invalid_outputs(cases, changes):
    c = cases[3]
    result = ev.score([c], [prediction(c, ['a','b'], **changes)])
    assert result['metrics']['cautious'] == dict(correct=0, total=1)
    assert len(result['misses']) == 1


def test_missing_cause_field_is_not_caution(cases):
    c = cases[3]
    p = prediction(c, ['a','b'])
    del p['confirmed_root_cause']
    assert not ev.cautious(p, {'observation-1'})


def test_predictions_must_cover_same_cases_in_order(cases):
    with pytest.raises(ValueError, match='count'):
        ev.score(cases, [])
    with pytest.raises(ValueError, match='order'):
        ev.score([cases[0]], [prediction(cases[1], ['a'])])


def test_baseline_report_reproduces_and_lists_every_miss(cases):
    result = ev.evaluate()
    assert result == json.loads((ev.HERE / 'results/public_incidents.json').read_text())
    assert {m['id'] for m in result['misses']} == {c['id'] for c in cases if c['kind'] == 'diagnosis'}
    assert ev.render(result) == (ev.HERE / 'docs/public-incident-results.md').read_text()
    assert all(p['action_mode'] == 'simulation_only' for p in result['predictions'])
