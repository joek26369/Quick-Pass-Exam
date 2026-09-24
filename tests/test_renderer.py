from __future__ import annotations

import importlib.util
from pathlib import Path


def _renderer():
    path = Path(__file__).parents[1] / "renderer.py"
    spec = importlib.util.spec_from_file_location("quick_pass_renderer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_package_renders_a_linked_learning_page(tmp_path: Path):
    renderer = _renderer()
    questions = [{"id": "Q1", "question_zh": "题干", "options": [{"label": "A", "text": "正确", "is_correct": True}], "concept_ids": ["C1"]}]
    concepts = [{"id": "C1", "title": "概念", "source_questions": ["Q1"], "core_concept": {"syntax": "x = y"}}]
    page = renderer.render_package(questions, concepts, tmp_path / "package")
    text = page.read_text(encoding="utf-8")
    assert "x = y" in text and "持久错题本" in text
    assert "Quick Pass Exam-快考通" in text
    assert (tmp_path / "package" / "assets" / "logo-mark.png").is_file()
    assert "CORNELL 自测" in text
    assert "cl-cards" in text and "康奈尔" in text and "闪卡" in text


def test_package_rejects_nonexistent_concept_link(tmp_path: Path):
    renderer = _renderer()
    questions = [{"id": "Q1", "options": [{"label": "A", "is_correct": True}], "concept_ids": ["missing"]}]
    try:
        renderer.render_package(questions, [], tmp_path / "package")
    except ValueError as exc:
        assert "不存在的概念" in str(exc)
    else:
        raise AssertionError("expected invalid concept link to be rejected")


def test_svg_rejects_css_network_and_embedded_active_content(tmp_path):
    renderer = _renderer()
    for body in ('<style>@import "https://example.org/a.css";</style>',
                 '<image href="data:image/svg+xml,anything"/>',
                 '<rect style="fill:url(https://example.org/a)"/>',
                 '<script>alert(1)</script>'):
        file = tmp_path / 'unsafe.svg'
        file.write_text('<svg xmlns="http://www.w3.org/2000/svg">'+body+'</svg>')
        assert not renderer._Resources._safe_svg(file)


def test_source_pdf_preserves_exact_file_and_physical_page(tmp_path):
    import hashlib
    import shutil
    renderer = _renderer()
    source = tmp_path / 'source'
    source.mkdir()
    pdf = Path(__file__).parent / 'fixtures' / 'source-pages.pdf'
    shutil.copy2(pdf, source / 'source-pages.pdf')
    q = [{'id': 'source_q', 'question_zh': 'CPI?', 'answer': 'A',
          'options': [{'label': 'A', 'text': 'EV/AC', 'is_correct': True}],
          'concept_ids': ['source_c'], 'source_file': 'source-pages.pdf', 'source_page': 2}]
    c = [{'id': 'source_c', 'title': 'CPI', 'source_questions': ['source_q'],
          'core_concept': {'definition': 'EV/AC'}}]
    output = tmp_path / 'package'
    page = renderer.render_package(q, c, output, input_dir=source)
    copied = list((output / 'assets/content').glob('*.pdf'))
    assert len(copied) == 1
    assert hashlib.sha256(copied[0].read_bytes()).digest() == hashlib.sha256(pdf.read_bytes()).digest()
    rendered = page.read_text()
    assert copied[0].relative_to(output).as_posix() + '#page=2' in rendered
    import json
    packaged = json.loads((output / 'manifest.json').read_text())
    assert packaged['questions'] == 1
    image = next((output / 'assets/content').glob('*-page-2.png'))
    assert image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert image.relative_to(output).as_posix() in rendered
    assert '查看原题所在第' in rendered
    resources = renderer._Resources(output, source)
    for invalid in [0, -1, True, 1.5, '2.5']:
        assert renderer._source_link(dict(q[0], source_page=invalid), resources) is None


def test_input_source_link_is_discarded_unless_local_pdf_link_is_derived(tmp_path):
    renderer = _renderer()
    questions = [{
        "id": "Q1", "question_zh": "题干", "source_link": "javascript:alert(document.URL)",
        "options": [{"label": "A", "text": "正确", "is_correct": True}],
        "concept_ids": ["C1"],
    }]
    concepts = [{"id": "C1", "title": "概念", "source_questions": ["Q1"]}]
    page = renderer.render_package(questions, concepts, tmp_path / "package")
    text = page.read_text(encoding="utf-8")
    assert "javascript:alert(document.URL)" not in text


def test_reserved_ids_and_chapter_names_use_null_prototype_state_maps(tmp_path):
    renderer = _renderer()
    questions = [{
        "id": "constructor", "question_zh": "题干", "answer": "A",
        "options": [{"label": "A", "text": "正确", "is_correct": True}],
        "concept_ids": ["__proto__"],
    }]
    concepts = [{
        "id": "__proto__", "title": "概念", "chapter": "constructor",
        "source_questions": ["constructor"],
    }]
    page = renderer.render_package(questions, concepts, tmp_path / "package")
    text = page.read_text(encoding="utf-8")
    assert "answers:Object.create(null)" in text
    assert "picked:Object.create(null)" in text
    assert "const groups=Object.create(null)" in text
    assert "QMAP=nullMap" in text and "CMAP=nullMap" in text


def test_canonical_teaching_evidence_is_copied_and_rendered_offline(tmp_path):
    import shutil
    renderer = _renderer()
    source = tmp_path / "source"
    source.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "source-pages.pdf"
    shutil.copy2(fixture, source / "guide.pdf")
    questions = [{"id": "Q1", "options": [{"label": "A", "text": "ok", "is_correct": True}],
                  "concept_ids": ["C1"]}]
    concepts = [{"id": "C1", "title": "关键路径", "source_questions": ["Q1"]}]
    output = tmp_path / "package"
    page = renderer.render_package(
        questions, concepts, output, input_dir=source,
        sources=[{"id": "book-1", "role": "teaching_material", "title": "项目管理教程", "path": "guide.pdf"}],
        teaching_evidence=[{"id": "ev-1", "concept_ids": ["C1"], "source_id": "book-1",
                            "relation": "supports", "status": "input_provided",
                            "locator": {"anchor": "关键路径法", "page": 2,
                                        "excerpt": "关键路径决定项目最短工期。"}}],
    )
    text = page.read_text(encoding="utf-8")
    pdfs = list((output / "assets" / "content").glob("*.pdf"))
    thumbs = list((output / "assets" / "content").glob("*-page-2.png"))
    assert len(pdfs) == 1 and len(thumbs) == 1
    assert "关键路径决定项目最短工期" in text
    assert "项目管理教程" in text and "#page=2" in text
    assert "renderMaterialEvidence" in text and "material-dialog" in text
    manifest = (output / "manifest.json").read_text(encoding="utf-8")
    assert '"source_count": 1' in manifest and '"teaching_evidence_count": 1' in manifest


def test_material_contract_rejects_urls_traversal_symlinks_and_bad_links(tmp_path):
    renderer = _renderer()
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    (source / "linked.pdf").symlink_to(outside)
    questions = [{"id": "Q1", "options": [{"label": "A", "is_correct": True}],
                  "concept_ids": ["C1"]}]
    concepts = [{"id": "C1", "title": "概念", "source_questions": ["Q1"]}]

    for path in ("https://example.test/book.pdf", "../outside.pdf", "linked.pdf"):
        try:
            renderer.render_package(
                questions, concepts, tmp_path / ("out-" + str(len(path))), input_dir=source,
                sources=[{"id": "book", "role": "teaching_material", "path": path}],
                teaching_evidence=[])
        except ValueError as exc:
            assert "教辅资源" in str(exc)
        else:
            raise AssertionError(f"expected unsafe material to be rejected: {path}")

    fixture = Path(__file__).parent / "fixtures" / "source-pages.pdf"
    (source / "guide.pdf").write_bytes(fixture.read_bytes())
    try:
        renderer.render_package(
            questions, concepts, tmp_path / "bad-link", input_dir=source,
            sources=[{"id": "book", "role": "teaching_material", "path": "guide.pdf"}],
            teaching_evidence=[{"id": "ev", "concept_ids": ["missing"], "source_id": "book",
                                "relation": "supports", "status": "input_provided",
                                "locator": {"page": 1, "excerpt": "节选"}}],
        )
    except ValueError as exc:
        assert "不存在的概念" in str(exc)
    else:
        raise AssertionError("expected missing concept link to be rejected")


def test_render_call_allows_no_teaching_evidence(tmp_path):
    renderer = _renderer()
    page = renderer.render_package(
        [{"id": "Q1", "options": [{"label": "A", "is_correct": True}], "concept_ids": ["C1"]}],
        [{"id": "C1", "title": "概念", "source_questions": ["Q1"]}],
        tmp_path / "package",
    )
    assert page.is_file()
    text = page.read_text(encoding="utf-8")
    assert '"sources":[]' in text and '"teaching_evidence":[]' in text


def test_case_package_keeps_child_ui_and_assets_offline(tmp_path: Path):
    renderer = _renderer()
    page = renderer.render_package(
        [], [], tmp_path / "package",
        cases=[{"id": "case-1", "original_number": "案例 1", "scenario": "共享情境",
                "source_pages": [], "diagram_images": [], "sub_questions": [{
                    "id": "case-1-a", "original_number": "(1)", "type": "calculation",
                    "question": "计算工期", "reference_answer": {"status": "verified", "text": "10 天"},
                    "method_ids": ["method-1"], "concept_ids": []}]}],
        methods=[{"id": "method-1", "title": "关键路径法", "type": "calculation",
                  "sub_question_ids": ["case-1-a"], "concept_ids": []}],
    )
    text = page.read_text(encoding="utf-8")
    assert '"cases"' in text and '"methods"' in text
    assert "案例题学习进度" in text and "保存作答" in text
    assert "cases/progress" in text and "case-assets.json" not in text
    assert (tmp_path / "package" / "case-assets.json").is_file()


def test_case_only_package_has_safe_empty_notes_and_serialized_draft_ui(tmp_path: Path):
    renderer = _renderer()
    page = renderer.render_package([], [], tmp_path / "package", cases=[{
        "id": "case-1", "scenario": "共享情境", "sub_questions": [{"id": "child-1", "question": "作答"}],
    }])
    text = page.read_text(encoding="utf-8")
    assert "暂无考点笔记" in text and "暂无选择题" in text
    assert "const queues=Object.create(null)" in text
    assert "captureCaseDrafts" in text and "data-case-draft" in text


def test_photo_case_keeps_original_image_as_source_and_diagram(tmp_path: Path):
    import base64
    import json
    renderer = _renderer()
    source = tmp_path / "source"
    source.mkdir()
    photo = source / "question.png"
    photo.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLZfAAAAABJRU5ErkJggg=="))
    output = tmp_path / "package"
    renderer.render_package([], [], output, input_dir=source,
        sources=[{"id": "photo", "role": "question_bank", "path": photo.name}],
        cases=[{"id": "case-photo", "source_id": "photo", "source_pages": [],
                "scenario": "看原图", "diagram_images": [],
                "sub_questions": [{"id": "child-photo", "question": "计算工期"}]}])
    data = json.loads((output / "case-assets.json").read_text())
    asset = data["case-photo"]["diagram_assets"][0]
    assert (output / asset).read_bytes() == photo.read_bytes()
    assert f'"source_file":"{asset}"' in (output / "index.html").read_text()


def test_quiz_source_pdf_stays_collapsed_until_user_opens_it(tmp_path: Path):
    renderer = _renderer()
    source = Path(__file__).parent / "fixtures" / "source-pages.pdf"
    page = renderer.render_package(
        [{
            "id": "q-source", "question_zh": "来源页不应因选项重绘而展开。",
            "options": [{"label": "A", "text": "甲", "is_correct": True}],
            "concept_ids": [], "source_file": source.name, "source_page": 1,
        }], [], tmp_path / "package", input_dir=source.parent,
    )
    text = page.read_text(encoding="utf-8")
    assert "details.open=false" in text


def test_top_navigation_order_and_choice_label(tmp_path: Path):
    renderer = _renderer()
    page = renderer.render_package(
        [{"id": "q1", "question_zh": "题目", "options": [{"label": "A", "text": "甲", "is_correct": True}], "concept_ids": []}],
        [], tmp_path / "package",
    )
    text = page.read_text(encoding="utf-8")
    order = [text.index(f'data-view="{view}"') for view in ("notes", "methods", "wrongbook", "quiz", "cases")]
    assert order == sorted(order)
    assert ">选择题</button>" in text
    assert ">刷题</button>" not in text
    assert '当前为单机版 Skill，更多功能及使用可访问：<a href="https://www.quickpexam.com/"' in text
    assert '>www.quickpexam.com</a><span id="save-warning"' in text


def test_page_displays_human_profile_name_and_stable_id(tmp_path: Path):
    renderer = _renderer()
    page = renderer.render_package([], [], tmp_path / "package",
        profile={"exam_code": "ruankao-xitongjicheng",
                 "exam_name_zh": "系统集成项目管理工程师（软考中级）"},
        cases=[{"id": "case-1", "scenario": "共享情境",
                "sub_questions": [{"id": "child-1", "question": "作答"}]}])
    text = page.read_text(encoding="utf-8")
    assert '<strong>当前 Profile：</strong>' in text
    assert "exam_name_zh||DATA.profile?.exam_full_name" in text
    assert "document.body.dataset.profile=profileId" in text
    assert 'ruankao-xitongjicheng' in text
    assert '系统集成项目管理工程师（软考中级）' in text
    assert '图片资源加载失败' in text
    assert '单文件模式' in text


def test_page_uses_quick_pass_logo_as_browser_favicon(tmp_path: Path):
    renderer = _renderer()
    page = renderer.render_package([], [], tmp_path / "package", cases=[{
        "id": "case-1", "scenario": "共享情境", "sub_questions": [{"id": "child-1", "question": "作答"}],
    }])
    text = page.read_text(encoding="utf-8")
    assert '<link rel="icon" type="image/svg+xml" href="assets/favicon.svg">' in text
    assert '<link rel="apple-touch-icon" href="assets/logo-mark.png">' in text
    assert (tmp_path / "package" / "assets" / "logo-mark.png").is_file()
    import base64
    import xml.etree.ElementTree as ET
    favicon = ET.parse(tmp_path / "package" / "assets" / "favicon.svg").getroot()
    assert favicon.attrib["viewBox"] == "95 -28.5 532 532"
    image = next(iter(favicon))
    assert (image.attrib["width"], image.attrib["height"], image.attrib["y"]) == ("722", "475", "0")
    embedded = image.attrib["href"].split(",", 1)[1]
    assert base64.b64decode(embedded) == (tmp_path / "package" / "assets" / "logo-mark.png").read_bytes()


def test_canonical_v2_sources_and_multi_concept_evidence(tmp_path):
    import shutil
    renderer = _renderer()
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy2(Path(__file__).parent / "fixtures" / "source-pages.pdf", source / "guide.pdf")
    questions = [
        {"id": "Q1", "options": [{"label": "A", "is_correct": True}], "concept_ids": ["C1", "C2"]},
    ]
    concepts = [
        {"id": "C1", "title": "关键路径", "source_questions": ["Q1"]},
        {"id": "C2", "title": "进度控制", "source_questions": ["Q1"]},
    ]
    page = renderer.render_package(
        questions, concepts, tmp_path / "package", input_dir=source,
        sources=[
            {"id": "guide", "role": "teaching_material", "title": "教程.pdf", "path": "guide.pdf"},
            # Non-teaching sources are outside this renderer contract and must
            # not be copied or validated as textbook material.
            {"id": "question-bank", "role": "question_bank", "path": "https://bad.test/q.pdf"},
        ],
        teaching_evidence=[{
            "source_id": "guide", "concept_ids": ["C1", "C2"],
            "relation": "supports", "status": "verified",
            "locator": {"page": 2, "anchor": "关键路径法", "excerpt": "决定最短工期。",
                        "region": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25}},
        }],
    )
    text = page.read_text(encoding="utf-8")
    assert text.count('"source_id":"guide"') == 2
    assert '"concept_id":"C1"' in text and '"concept_id":"C2"' in text
    assert '"relation":"supports"' in text and '"status":"verified"' in text
    assert '"region":{"x":0.1,"y":0.2,"width":0.3,"height":0.25}' in text
    assert "material-region" in text and "question-bank" not in text and "bad.test" not in text
    assert len(list((tmp_path / "package/assets/content").glob("*.pdf"))) == 1
