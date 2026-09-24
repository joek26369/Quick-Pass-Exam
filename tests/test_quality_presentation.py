"""Quality metadata stays in backend reports and out of learner-facing web."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from renderer import render_package
from study_server import register


def _render(tmp_path, summary=None, rationale='已对照资料'):
    questions = [{'id': 'Q1', 'question_zh': '题干', 'concept_ids': ['C1'],
                  'options': [{'label': 'A', 'text': '选项', 'is_correct': True}]}]
    concepts = [{'id': 'C1', 'title': '概念', 'source_questions': ['Q1'],
                 'content_review': {'status': 'reviewed', 'rationale': rationale}}]
    return render_package(questions, concepts, tmp_path / 'web', quality_summary=summary)


def test_quality_metadata_is_not_copied_to_web_manifest_or_html(tmp_path):
    summary = {'structural_status': 'passed', 'content_status': 'limited',
               'semantic_verification': 'not_performed', 'browser_status': 'not_checked',
               'metrics': {'missing_support': 2}}
    page = _render(tmp_path, summary)
    manifest = json.loads((page.parent / 'manifest.json').read_text())
    html = page.read_text()
    assert 'quality_summary' not in manifest
    assert 'quality_summary' not in html
    assert 'quality-status' not in html
    assert '内容待审校' not in html
    assert '学习内容覆盖情况' not in html


def test_card_and_case_review_details_are_absent_from_web_payload(tmp_path):
    attack = '</script><img src=x onerror=alert(1)>'
    page = _render(tmp_path, {'content_status': 'agent_reviewed'}, attack)
    html = page.read_text()
    assert attack not in html
    assert 'renderQualityStatus' not in html
    assert 'renderCardReview' not in html
    assert 'content_review' not in html
    assert 'learning_support_review' not in html


@pytest.mark.parametrize('status', ['blocked', 'failed'])
def test_register_rejects_explicit_failed_quality_before_writing_library(tmp_path, status):
    package = tmp_path / 'package'
    package.mkdir()
    (package / 'manifest.json').write_text(json.dumps({'profile': 'test', 'quality_status': status}))
    library = tmp_path / 'library'
    with pytest.raises(ValueError, match='不能注册'):
        register(library, package)
    assert not library.exists()


@pytest.mark.parametrize('status', [None, 'passed', 'review_required', 'agent_reviewed', 'limited'])
def test_register_retains_legacy_and_reviewable_packages(tmp_path, status):
    package = tmp_path / 'package'
    (package / 'web').mkdir(parents=True)
    (package / 'data').mkdir()
    (package / 'web/index.html').write_text('学习包')
    (package / 'data/questions.json').write_text('[{"id":"Q1"}]')
    manifest = {'profile': 'test'}
    if status is not None:
        manifest['quality_status'] = status
    (package / 'manifest.json').write_text(json.dumps(manifest))
    assert register(tmp_path / 'library', package)[1] == 'test'
