"""Deterministic content checks: no model, no arbitrary text-length requirement."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vendor.generation_quality_gate import evaluate_card_content, evaluate_generation


def card():
    return {
        'id': 'c1', 'title': 'CPI', 'source_questions': ['q1'],
        'one_liner': 'CPI 衡量成本效率。',
        'mnemonic': '成本效率看 CPI',
        'visualization': {'type': 'flow', 'nodes': ['挣值', '成本效率'], 'relations': ['挣值 → 成本效率']},
        'cornell_note': {'pairs': [{'cue': '如何计算？', 'note': 'CPI = EV / AC。'}],
                         'summary': '用挣值与实际成本比较。'},
    }


def reviewed(value, status='reviewed'):
    value['content_review'] = {'reviewer': 'agent', 'status': status,
                               'rationale': '已核对题库解析；未发现直接教辅证据，仅保留题库支持的公式。'}
    from vendor.generation_quality_gate import LEARNING_SUPPORT_FIELDS, _has_learning_support
    value['learning_support_review'] = {
        field: {'status': 'included' if _has_learning_support(value, field) else 'not_applicable',
                'reason': f'已核对本卡题目与内容，{field}按本卡学习用途判断。'}
        for field in LEARNING_SUPPORT_FIELDS
    }
    return value


def check(value, evidence=()):
    return evaluate_card_content([value], [{'id': 'q1'}], evidence)


def test_actual_mechanical_copy_pattern_is_blocked_even_with_review():
    value = reviewed(card())
    value['one_liner'] = '**原题解释**'
    value['cornell_note']['summary'] = '原题\n解释'
    value['cornell_note']['pairs'][0]['note'] = '原题解释'
    report = check(value)
    assert report['status'] == 'blocked'
    assert report['metrics']['triple_duplicate_count'] == 1
    assert 'CARD_TRIPLE_DUPLICATE' in report['concepts'][0]['findings']


def test_terminal_punctuation_and_generic_body_cannot_rescue_copied_card():
    value = reviewed(card())
    copied = '项目只有验收通过后才能转为已完成，提交成果本身不满足完成条件'
    value['one_liner'] = copied
    value['cornell_note']['summary'] = copied + '。'
    value['cornell_note']['pairs'][0]['note'] = copied + '！'
    value['core_concept'] = {'definition': '请记住此知识点。'}
    report = check(value)
    assert report['status'] == 'blocked'
    assert 'CARD_TRIPLE_DUPLICATE' in report['concepts'][0]['findings']
    assert not report['concepts'][0]['has_substantive_body']


def test_long_near_copy_requires_review_despite_agent_declaration():
    value = reviewed(card())
    copied = '变更申请应先登记并评估范围成本进度影响，随后由授权人批准，批准以后才能实施变更活动'
    value['one_liner'] = copied
    value['cornell_note']['summary'] = copied.replace('随后', '之后')
    value['cornell_note']['pairs'][0]['note'] = copied.replace('以后', '之后')
    value['core_concept'] = {'definition': '登记留下请求记录，评估表记录影响。'}
    report = check(value)
    assert report['status'] == 'review_required'
    assert 'CARD_NEAR_DUPLICATE' in report['concepts'][0]['findings']


def test_short_fact_repetition_with_distinct_body_remains_accepted():
    value = reviewed(card())
    value['one_liner'] = '复习日是周四'
    value['cornell_note']['summary'] = '本练习包周四复习'
    value['cornell_note']['pairs'][0] = {'cue': '哪天复习？', 'note': '周四'}
    value['core_concept'] = {'definition': '这是本练习包规定的安排。'}
    assert check(value)['status'] == 'agent_reviewed'


def test_short_single_question_single_pair_card_is_not_blocked():
    report = check(reviewed(card()))
    assert report['status'] == 'agent_reviewed'
    assert report['metrics']['one_question_card_count'] == 1
    assert report['semantic_verification'] == 'not_performed'
    assert all(item['severity'] == 'info' for item in report['findings'])


def test_formula_reused_inside_distinct_explanations_is_not_blocked():
    value = reviewed(card())
    value['one_liner'] = 'CPI = EV / AC 衡量成本效率。'
    value['cornell_note']['pairs'][0]['note'] = 'CPI = EV / AC；AC 不能为零。'
    value['cornell_note']['summary'] = 'CPI = EV / AC；小于 1 表示成本超支。'
    assert check(value)['status'] == 'agent_reviewed'


@pytest.mark.parametrize('relation', [None, 'related', 'supports'])
def test_evidence_coverage_is_counted_without_semantic_claims_or_hard_block(relation):
    evidence = [] if relation is None else [{'id': 'e1', 'concept_ids': ['c1'], 'relation': relation}]
    report = check(reviewed(card(), 'limited'), evidence)
    assert report['status'] == 'limited'
    assert report['metrics']['concepts_without_supports'] == (relation != 'supports')
    assert report['metrics']['concepts_with_related'] == (relation == 'related')
    assert report['metrics']['concepts_without_teaching_evidence'] == (relation is None)


@pytest.mark.parametrize('placeholder', ['TODO', '**待补充**', '原文节选占位。'])
def test_whole_field_placeholders_block(placeholder):
    value = reviewed(card())
    value['core_concept'] = {'rules': [placeholder]}
    assert check(value)['status'] == 'blocked'


def test_placeholder_word_in_real_lesson_is_not_rejected():
    value = reviewed(card())
    value['core_concept'] = {'definition': 'TODO 表示代码中的待办事项，本卡解释其含义。'}
    assert check(value)['status'] == 'agent_reviewed'


@pytest.mark.parametrize('status', ['reviewed', 'limited'])
def test_review_metadata_cannot_override_absence_of_independent_body(status):
    value = reviewed(card(), status)
    value['cornell_note']['pairs'][0]['note'] = value['one_liner']
    report = check(value)
    assert report['status'] == 'review_required'
    assert not report['concepts'][0]['has_substantive_body']


def test_missing_review_is_never_passed():
    assert check(card())['status'] == 'review_required'


@pytest.mark.parametrize('review', [
    {'reviewer': 'agent', 'status': 'reviewed', 'rationale': 'TODO'},
    {'reviewer': 'agent', 'status': 'reviewed', 'rationale': ''},
    {'reviewer': 'agent', 'status': 'needs_revision', 'rationale': '公式条件未核验。'},
    {'reviewer': 'human', 'status': 'reviewed', 'rationale': '未知审校来源。'},
])
def test_invalid_or_revision_review_cannot_certify(review):
    value = card()
    value['content_review'] = review
    assert check(value)['status'] == 'review_required'


def test_mixed_batch_and_empty_batch_are_not_certified():
    ready = reviewed(card())
    pending = deepcopy(card())
    pending['id'] = 'c2'
    report = evaluate_card_content([ready, pending], [{'id': 'q1'}])
    assert report['status'] == 'review_required'
    assert report['metrics']['agent_reviewed_count'] == 1
    assert report['metrics']['review_required_count'] == 1
    assert evaluate_card_content([], [])['status'] == 'review_required'


def test_legacy_question_origin_gate_unchanged():
    value = card()
    report = evaluate_generation([value], ['q1'], generation_id='legacy')
    assert report['contract_version'] == 'question-origin-v1'
    assert report['status'] == 'passed'


def test_adding_duplicate_pairs_cannot_bypass_mechanical_copy_block():
    value = reviewed(card())
    value['cornell_note']['summary'] = value['one_liner']
    value['cornell_note']['pairs'] = [
        {'cue': '含义？', 'note': value['one_liner']},
        {'cue': '用途？', 'note': value['one_liner']},
    ]
    assert check(value)['status'] == 'blocked'


def test_included_metadata_cannot_hide_empty_support_field():
    value = reviewed(card())
    value.pop('mnemonic')
    report = check(value)
    assert report['status'] == 'review_required'
    assert report['learning_support_coverage']['mnemonic']['unexplained_missing'] == 1
    assert any(item['code'] == 'CARD_LEARNING_SUPPORT_INCLUDED_EMPTY' and item['field'] == 'mnemonic'
               for item in report['findings'])


def test_legacy_card_remains_readable_but_requires_review():
    value = reviewed(card())
    value.pop('learning_support_review')
    report = check(value)
    assert report['status'] == 'review_required'
    assert len([item for item in report['findings']
                if item['code'] == 'CARD_LEARNING_SUPPORT_REVIEW_MISSING']) == 6


def test_comparison_variants_count_as_one_support_module():
    value = reviewed(card())
    value['core_concept'] = {'type_comparison': [{'type': 'A', 'key_rules': '适用条件 A'}]}
    value['learning_support_review']['comparisons'] = {
        'status': 'included', 'reason': '本卡存在两个公式变体，需要说明各自适用条件。'}
    report = check(value)
    assert report['concepts'][0]['learning_support']['comparisons']['present']


def test_package_zero_visuals_and_mnemonics_requires_whole_package_review():
    value = reviewed(card())
    value.pop('mnemonic')
    value.pop('visualization')
    for field in ('mnemonic', 'visualization'):
        value['learning_support_review'][field] = {
            'status': 'not_applicable', 'reason': '本卡为单一事实，原资料没有结构或顺序可作图示或助记。'}
    report = check(value)
    assert report['status'] == 'review_required'
    assert {item['field'] for item in report['findings']
            if item['code'] == 'PACKAGE_LEARNING_SUPPORT_ZERO'} == {'mnemonic', 'visualization'}


def test_visualization_type_without_renderable_nodes_is_not_included():
    value = reviewed(card())
    value['visualization'] = {'type': 'flow', 'nodes': [], 'relations': []}
    report = check(value)
    assert not report['concepts'][0]['learning_support']['visualization']['present']
    assert any(item['code'] == 'CARD_LEARNING_SUPPORT_INCLUDED_EMPTY'
               and item['field'] == 'visualization' for item in report['findings'])


@pytest.mark.parametrize('malformed', ["A 对 B", [{'vs': 'A'}], [{'type': 'A'}],
                                             [{'difference': '不同'}], {'vs': 'A', 'difference': '不同'}])
def test_malformed_comparison_does_not_count_as_included(malformed):
    value = reviewed(card())
    value['core_concept'] = {'comparisons': malformed}
    value['learning_support_review']['comparisons'] = {
        'status': 'included', 'reason': '本卡确有两个可比较的类型，需要说明边界。'}
    report = check(value)
    assert not report['concepts'][0]['learning_support']['comparisons']['present']
    assert any(item['code'] == 'CARD_LEARNING_SUPPORT_INCLUDED_EMPTY'
               and item['field'] == 'comparisons' for item in report['findings'])
