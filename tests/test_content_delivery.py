"""Exercise content quality at the actual packaging/CLI boundary."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator import ContractError, generate_package


def write_input(tmp_path, review=None, duplicate=False):
    (tmp_path / 'bank.txt').write_text('自编验证题：CPI衡量成本效率。', encoding='utf-8')
    concept = {
        'id': 'c1', 'title': '成本绩效指数', 'source_questions': ['q1'],
        'one_liner': 'CPI 用于衡量成本效率。',
        'core_concept': {'definition': '成本绩效指数是挣值与实际成本的比值，用于判断成本效率。'},
        'cornell_note': {'pairs': [{'cue': '怎样判断成本效率？',
                                    'note': '计算挣值与实际成本的比值，低于一表示成本效率偏低。'}],
                         'summary': '先区分挣值与实际成本，再计算比值并解释成本效率。'},
        'teaching_evidence_ids': [],
    }
    if duplicate:
        text = '这道题选择 A，因为成本绩效指数衡量成本效率。'
        concept.pop('core_concept')
        concept['one_liner'] = concept['cornell_note']['summary'] = text
        concept['cornell_note']['pairs'][0]['note'] = text
    if review:
        concept['mnemonic'] = '挣值比成本，指数看效率'
        concept['visualization'] = {'type': 'flow', 'nodes': ['挣值', '实际成本', '成本效率'],
                                    'relations': ['挣值 → 成本效率', '实际成本 → 成本效率']}
        concept['learning_support_review'] = {
            field: {'status': 'included' if field in ('mnemonic', 'visualization') else 'not_applicable',
                    'reason': f'已核对本卡题目和解释，{field}按学习用途逐项判断。'}
            for field in ('mnemonic', 'visualization', 'principle', 'comparisons',
                          'best_practices', 'why_tested')
        }
        concept['content_review'] = {'reviewer': 'agent', 'status': review,
                                     'rationale': '已检查题目关联及讲解；未提供教辅，证据范围限于题库。'}
    payload = {
        'schema_version': 'quick-pass-agent-content-v2',
        'sources': [{'id': 'bank', 'role': 'question_bank', 'path': 'bank.txt'}],
        'questions': [{'id': 'q1', 'question_zh': 'CPI衡量什么？', 'answer': 'A',
                       'options': [{'label': 'A', 'text': '成本效率', 'is_correct': True},
                                   {'label': 'B', 'text': '人员数量', 'is_correct': False}],
                       'source_id': 'bank', 'concept_ids': ['c1']}],
        'concepts': [concept], 'teaching_evidence': [],
    }
    path = tmp_path / 'agent-content.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.mark.parametrize('review, expected', [(None, 'review_required'),
                                              ('reviewed', 'agent_reviewed'),
                                              ('limited', 'limited'),
                                              ('needs_revision', 'review_required')])
def test_review_status_survives_delivery_without_claiming_semantic_truth(tmp_path, review, expected):
    out = generate_package(write_input(tmp_path, review), tmp_path / 'out',
                           profile_name='ruankao-xitixiangmu', agent_content=True)
    manifest = json.loads((out / 'manifest.json').read_text())
    report = json.loads((out / 'reports/quality-report.json').read_text())
    web = json.loads((out / 'web/manifest.json').read_text())
    assert manifest['quality_status'] == manifest['content_status'] == expected
    assert manifest['structural_status'] == 'passed'
    assert manifest['browser_status'] == report['browser']['status'] == 'not_checked'
    assert report['content']['status'] == expected
    assert report['content']['semantic_verification'] == 'not_performed'
    assert manifest['usage']['attempt_count'] == 0
    assert 'quality_summary' not in web
    assert manifest['learning_support_coverage'] == report['content']['learning_support_coverage']
    html = (out / 'web/index.html').read_text()
    assert 'quality_summary' not in html
    assert '学习内容覆盖情况' not in html


def test_cli_blocks_copied_cards_before_package_or_library_registration(tmp_path):
    source = write_input(tmp_path, 'reviewed', duplicate=True)
    out, library = tmp_path / 'out', tmp_path / 'library'
    result = subprocess.run([sys.executable, str(ROOT / 'cli.py'), '--input', str(source),
                             '--output', str(out), '--agent-content', '--open',
                             '--library', str(library)], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'QUALITY' in result.stderr
    assert not out.exists() and not library.exists()
    report = json.loads((tmp_path / 'out.failed-quality.json').read_text())
    assert report['content']['status'] == 'blocked'
    assert report['content']['metrics']['blocked_count'] == 1


def test_fixture_is_labeled_demo_instead_of_content_passed(tmp_path):
    out = generate_package(ROOT / 'examples/learning-package-input.json', tmp_path / 'demo',
                           profile_name='ruankao-xitixiangmu', fixture=True)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['mode'] == manifest['content_status'] == 'fixture'
    assert manifest['structural_status'] == 'passed'


def test_intermediate_exam_profile_preserves_subject_in_page_and_manifest(tmp_path):
    source = write_input(tmp_path, 'limited')
    out = generate_package(source, tmp_path / 'middle',
                           profile_name='ruankao-xitongjicheng', agent_content=True)
    assert json.loads((out / 'manifest.json').read_text())['profile'] == 'ruankao-xitongjicheng'
    assert '软考中级 · 系统集成项目管理工程师' in (out / 'web/index.html').read_text()
    with pytest.raises(ContractError, match='仅支持 --agent-content'):
        generate_package(source, tmp_path / 'wrong-mode',
                         profile_name='ruankao-xitongjicheng', fixture=True)
