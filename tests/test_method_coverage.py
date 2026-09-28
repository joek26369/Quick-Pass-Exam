import copy
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from method_coverage import audit_method_coverage, SCHEMA
from generator import generate_package, ContractError
from package_audit import audit_package
from test_package_audit import inputs, web_data


def sample():
    q = [{'id': 'q1', 'question_zh': '计算两方案的 EMV'}]
    m = [dict(id='m1', type='calculation', calculation_type='emv',
              applicability='概率与收益已知', assumptions='情景互斥且完备',
              formula='EMV=ΣpV', units='万元', steps=['统一收益口径，再概率加权'],
              input_requirements=['各情景概率与收益'], case_basis=[{'excerpt': '题干'}],
              question_ids=['q1'], sub_question_ids=[])]
    inv = dict(schema_version=SCHEMA, items=[dict(question_id='q1', classification='calculation',
               reason='题目要求按概率计算', input_excerpt='计算两方案的 EMV',
               requirements=[dict(type_id='emv', method_id='m1', reason='概率加权步骤匹配')])])
    return q, [], m, inv


def test_complete_choice_calculation():
    assert audit_method_coverage(*sample())['status'] == 'passed'


@pytest.mark.parametrize('change,code', [
    ('missing', 'METHOD_QUESTION_UNREVIEWED'), ('duplicate', 'METHOD_REVIEW_ID_INVALID'),
    ('wrong_type', 'METHOD_TYPE_MISMATCH'), ('no_link', 'METHOD_LINK_MISSING'),
    ('wrong_excerpt', 'METHOD_INPUT_EXCERPT_INVALID'), ('no_steps', 'METHOD_CONTENT_MISSING'),
    ('unresolved', 'METHOD_REVIEW_UNRESOLVED'), ('no_requirement', 'METHOD_REQUIREMENT_MISSING'),
])
def test_detects_coverage_defects(change, code):
    q, c, m, inv = sample()
    row = inv['items'][0]
    if change == 'missing': inv['items'] = []
    if change == 'duplicate': inv['items'].append(copy.deepcopy(row))
    if change == 'wrong_type': m[0]['calculation_type'] = 'critical-path'
    if change == 'no_link': m[0]['question_ids'] = []
    if change == 'wrong_excerpt': row['input_excerpt'] = '不存在的输入'
    if change == 'no_steps': m[0]['steps'] = []
    if change == 'unresolved': row['classification'] = 'unresolved'
    if change == 'no_requirement': row['requirements'] = []
    report = audit_method_coverage(q, c, m, inv)
    assert report['status'] == 'blocked'
    assert code in {f['code'] for f in report['findings']}


def test_legacy_is_limited_but_new_generation_requires_inventory():
    q, c, m, _ = sample()
    assert audit_method_coverage(q, c, m, None)['status'] == 'limited'
    assert audit_method_coverage(q, c, m, None, required=True)['status'] == 'blocked'


def test_multi_algorithm_case_requires_each_algorithm_and_both_links():
    q, _, m, inv = sample()
    c = [{'scenario': '背景', 'sub_questions': [{'id': 'q1', 'question': q[0]['question_zh'], 'method_ids': ['m1','m2']}]}]
    m[0].update(question_ids=[], sub_question_ids=['q1'])
    m.append(dict(m[0], id='m2', calculation_type='contract-payment'))
    inv['items'][0]['requirements'].append(dict(type_id='contract-payment', method_id='m2', reason='另一任务'))
    assert audit_method_coverage([], c, m, inv)['status'] == 'passed'
    c[0]['sub_questions'][0]['method_ids'].remove('m2')
    assert audit_method_coverage([], c, m, inv)['status'] == 'blocked'


def test_generation_missing_inventory_leaves_report_not_package(tmp_path):
    path, root, inventory = inputs(tmp_path)
    payload = json.loads(path.read_text()); payload.pop('method_coverage')
    path.write_text(json.dumps(payload))
    out = tmp_path/'failed'
    with pytest.raises(ContractError, match='计算方法覆盖'):
        generate_package(path, out, profile_name='ruankao-xitixiangmu', agent_content=True)
    assert not out.exists()
    assert json.loads((tmp_path/'failed.method-coverage.json').read_text())['repair_instructions']


def test_postflight_checks_method_text_and_navigation(tmp_path):
    path, root, inventory = inputs(tmp_path)
    payload = json.loads(path.read_text())
    payload['questions'][0]['question_zh'] = 'EV=60，AC=75，计算 CPI'
    payload['methods'] = [dict(id='m1', type='calculation', title='CPI', calculation_type='evm',
        applicability='EV 与 AC 已知', assumptions='同一时点且 AC 非零', formula='CPI=EV/AC',
        units='无量纲', substitution='60/75=0.8', steps=['核对单位', '相除'], pitfalls=[],
        input_requirements=['EV','AC'], case_basis=[dict(source_id='bank',excerpt='EV=60，AC=75')],
        answer_structure='', question_ids=['q1'], sub_question_ids=[], concept_ids=['c1'], evidence_ids=['ev1'])]
    row = payload['method_coverage']['items'][0]
    row.update(classification='calculation', reason='计算 CPI', input_excerpt='计算 CPI',
               requirements=[dict(type_id='evm', method_id='m1', reason='同一时点金额相除')])
    path.write_text(json.dumps(payload, ensure_ascii=False))
    out = generate_package(path, tmp_path/'pkg', profile_name='ruankao-xitixiangmu',
                           agent_content=True, source_root=root, source_inventory=inventory)
    assert audit_package(out)['status'] == 'passed'
    html, start, end, web = web_data(out)
    assert web['methods'][0]['question_ids'] == ['q1']
    web['methods'][0]['formula'] = 'wrong'
    (out/'web/index.html').write_text(html[:start]+json.dumps(web)+html[start+end:])
    report = audit_package(out)
    assert 'WEB_METHOD_MISMATCH' in {f['code'] for f in report['findings']}
    # Independently recheck the stored review, not its former status report.
    coverage = json.loads((out/'data/method-coverage.json').read_text())
    coverage['items'] = []
    (out/'data/method-coverage.json').write_text(json.dumps(coverage))
    assert 'METHOD_QUESTION_UNREVIEWED' in {f['code'] for f in audit_package(out)['findings']}
