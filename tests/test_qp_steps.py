"""Shared A1 corpus, optional-field degradation and standalone release checks."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qp_steps as qp
from case_contract import validate_cases_methods

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/qp_steps'
CASES = [p for p in sorted(FIXTURES.glob('*.json')) if p.stem != 'basis-hash']


def method(block=None):
    result = dict(id='m1', title='PERT三点估算', type='calculation', applicability='三点估算',
                  formula='TE=(O+4*M+P)/6', substitution='', units='天', steps=['期望工期'],
                  pitfalls=[], answer_structure='', case_basis=[], sub_question_ids=[],
                  concept_ids=[], evidence_ids=[])
    if block is not None:
        result['qp_steps'] = copy.deepcopy(block)
    return result


def block():
    result = json.loads((FIXTURES / 'valid-pert.json').read_text())['block']
    result['provenance']['basis_hash'] = qp.basis_hash(method()['title'], method()['formula'])
    return result


def check(m):
    return validate_cases_methods([], [m], sources=[], concepts=[], evidence=[], question_ids=set())


@pytest.mark.parametrize('path', CASES, ids=lambda p: p.stem)
def test_shared_corpus(path):
    data = json.loads(path.read_text())
    ok, errors = qp.validate(data['block'])
    assert ok is data['expected']['valid'], errors
    if ok:
        for run in data['expected']['runs']:
            actual = qp.evaluate(data['block'], run['inputs'], run['choices'])
            assert len(actual) == len(run['steps'])
            for step, expected in zip(actual, run['steps']):
                assert step['id'] == expected['id']
                if 'value' in expected:
                    assert step['value'] == pytest.approx(expected['value'])
                assert step['verdicts'] == expected['verdicts']
                if 'show' in expected:
                    assert step['show'] == expected['show']
    else:
        assert errors[0].startswith(data['expected']['error_code'] + ':')


def test_hash_vectors_and_upstream_bytes():
    record = json.loads((ROOT / 'qp-steps-source.json').read_text())
    assert record['contract'] == 'qp-steps-v1'
    assert record['revision'] == 'content-addressed-sha256'
    assert 'repository' not in record and 'commit' not in record
    pinned = {item['path']: item['sha256'] for item in record['files']}
    assert pinned['qp_steps.py'] == 'a38cd291ed7dab57796151ddf8d068c7b0a833f092dc7b82b11e30594be291f3'
    assert pinned['schema/qp-steps-v1.schema.json'] == '6862c7f109727b95aa88c0e5ad34fb75e52583aaaec9dfa9ed5614c31aab2863'
    for item in record['files']:
        assert hashlib.sha256((ROOT / item['path']).read_bytes()).hexdigest() == item['sha256']
    for vector in json.loads((FIXTURES / 'basis-hash.json').read_text())['cases']:
        assert qp.basis_hash(vector['web']['method'], vector['web']['formulas_section']) == vector['expected']
        assert qp.basis_hash(vector['skill']['title'], vector['skill']['formula']) == vector['expected']


def test_optional_valid_and_absent_fields_do_not_change_input():
    original = method(block())
    before = copy.deepcopy(original)
    _, methods, report = check(original)
    assert methods == [before] and original == before
    assert not any(x['code'] == 'METHOD_QP_STEPS_DROPPED' for x in report['findings'])
    assert 'qp_steps' not in check(method())[1][0]


@pytest.mark.parametrize('change', [
    lambda m: m.update(formula='different formula'),
    lambda m: m.update(title='different title'),
    lambda m: m.update(type='answering'),
    lambda m: m['qp_steps']['steps'][0].update(expr='1/0'),
    lambda m: m.update(qp_steps=None),
    lambda m: m.update(formula=''),
    lambda m: m.update(formula=' \n\t'),
    lambda m: m.update(formula='## split\nformula'),
])
def test_invalid_or_stale_block_drops_only_field(change):
    original = method(block())
    change(original)
    if original['formula'].strip() in ('', '## split\nformula'):
        original['qp_steps']['provenance']['basis_hash'] = qp.basis_hash(original['title'], original['formula'])
    before = copy.deepcopy(original)
    _, methods, report = check(original)
    assert methods[0] == {k: v for k, v in before.items() if k != 'qp_steps'}
    assert original == before
    assert any(x['code'] == 'METHOD_QP_STEPS_DROPPED' for x in report['findings'])


@pytest.mark.parametrize('layout,prefix', [('workbuddy', ''), ('generic', 'quick-pass-exam/'), ('source', 'quick-pass-exam/')])
def test_release_unpacks_and_validates_without_site_packages(tmp_path, layout, prefix):
    from tools.build_snapshot import build
    archive = tmp_path / (layout + '.zip')
    build(archive, layout=layout)
    dest = tmp_path / 'unpacked'
    with zipfile.ZipFile(archive) as z:
        assert prefix + 'qp_steps.py' in z.namelist()
        assert prefix + 'schema/qp-steps-v1.schema.json' in z.namelist()
        z.extractall(dest)
    app = dest / prefix
    probe = tmp_path / 'probe.py'
    probe.write_text('import sys,json\nsys.path.insert(0,sys.argv[1])\nfrom qp_steps import validate\n'
                     'from case_contract import validate_cases_methods\n'
                     'data=json.load(open(sys.argv[2]))\nassert validate(data)[0]\n')
    input_file = tmp_path / 'block.json'
    input_file.write_text(json.dumps(block()))
    result = subprocess.run([sys.executable, '-I', '-S', str(probe), str(app), str(input_file)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
