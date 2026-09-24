from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


def _renderer():
    path = Path(__file__).parents[1] / "renderer.py"
    spec = importlib.util.spec_from_file_location("quick_pass_renderer_fidelity", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_fidelity_fields_and_inline_images_are_packaged_without_mutating_input(tmp_path: Path):
    renderer = _renderer()
    source = tmp_path / "input"
    source.mkdir()
    (source / "stem.png").write_bytes(b"synthetic-image")
    questions = [{
        "id": "Q-fidelity",
        "source_paper": "输入题库 A 卷",
        "question_zh": "计算题\n![流程图](stem.png)\n![远程图](https://example.invalid/x.png)",
        "options": [{"label": "A", "text": "正确", "is_correct": True}],
        "answer": "A",
        "answer_mismatch": True,
        "llm_answer": "B",
        "concept_ids": ["C-fidelity"],
        "core_exam_points": [{"title": "核心公式", "body": "EV / AC"}],
        "calc_solution": {"method_name": "挣值法", "steps": "代入 EV 与 AC", "common_patterns": "先辨别分子分母"},
        "knowledge_expansion": [{"topic": "扩展", "body": "CV = EV - AC"}],
        "method_extract": {"method_name": "计算法", "description": "适用于已知 EV、AC"},
        "generated_analysis": {
            "core_exam_points": [{"title": "模型考点", "body": "仅作辅助"}],
            "calc_solution": {"method_name": "模型计算", "steps": "模型步骤"},
            "knowledge_expansion": [{"topic": "模型扩展", "body": "模型内容"}],
            "method_extract": {"method_name": "模型方法", "applicable_conditions": "模型条件"},
            "answer_mismatch": True,
            "llm_answer": "C",
        },
    }]
    concepts = [{
        "id": "C-fidelity", "title": "成本绩效", "source_questions": ["Q-fidelity"],
        "question_origins": [{"question_id": "Q-fidelity"}],
        "canonical_references": [{"title": "输入书目", "source_file": "book.pdf", "page": 1}],
        "references": ["历史字段来源"],
        "core_concept": {"definition": "定义"},
    }]
    original_questions, original_concepts = copy.deepcopy(questions), copy.deepcopy(concepts)

    page = renderer.render_package(questions, concepts, tmp_path / "package", input_dir=source)
    payload = page.read_text(encoding="utf-8")
    assert questions == original_questions and concepts == original_concepts
    assert '"source":"stem.png"' in payload
    assert '"asset":"assets/content/' in payload
    assert '"source":"https://example.invalid/x.png","asset":null' in payload
    assert (tmp_path / "package" / "assets" / "content").glob("*.png")
    for expected in (
        "renderQuestionLearningDetails(a,q)", "renderQuestionLearningDetails(a,ga,'模型生成')",
        "renderAnswerMismatchDetails(a,q,ga)", "答案存疑", "核心考点", "计算步骤",
        "模型考点", "模型计算", "扩展知识", "方法论抽取", "题干图片不可用", "renderConceptFidelityDetails(a,c)",
        "来源题目（输入声明）", "输入提供的来源（未额外核验）", "旧式来源字段（未核验）",
    ):
        assert expected in payload


def test_inline_markdown_reference_parser_only_collects_complete_image_lines(tmp_path: Path):
    renderer = _renderer()
    source = tmp_path / "input"
    source.mkdir()
    (source / "one.png").write_bytes(b"one")
    question = {
        "id": "Q1", "question_zh": "![one](one.png)\n正文 ![not-line](one.png)",
        "options": [{"label": "A", "text": "a", "is_correct": True}], "concept_ids": ["C1"],
    }
    concept = {"id": "C1", "source_questions": ["Q1"]}
    normal = renderer._normalise_questions([question], renderer._Resources(tmp_path / "out", source))[0]
    assert normal["inline_image_assets"] == [{"source": "one.png", "asset": "assets/content/" + next((tmp_path / "out" / "assets" / "content").iterdir()).name}]
    assert normal["unavailable_inline_images"] == []
    assert question["question_zh"].endswith("![not-line](one.png)")
