import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from case_contract import CaseContractError, validate_cases_methods


def sample():
    cases = [{
        "id": "case1", "original_number": "案例一", "source_id": "bank",
        "source_pages": [1, 2], "scenario": "项目进度情境", "diagram_images": [],
        "sub_questions": [{
            "id": "case1q1", "original_number": "（1）", "type": "calculation",
            "question": "计算工期", "source_pages": [2],
            "reference_answer": {"status": "verified", "text": "10 天", "source_id": "bank",
                                 "source_pages": [2], "sub_question_id": "case1q1"},
            "generated_analysis": "计算关键路径", "calculation_steps": [{"text": "相加",
                "input_basis": [{"source_id": "bank", "page": 2, "excerpt": "活动时间"}]}],
            "pitfalls": [], "concept_ids": [], "evidence_ids": [], "method_ids": ["method1"],
            "score": {"max_points": 5, "source_id": "bank", "source_pages": [2], "excerpt": "本题 5 分"},
            "scoring_points": [{"text": "列式", "source_id": "bank", "source_pages": [2], "excerpt": "列式 2 分"}],
        }],
        "coverage_review": {"status": "complete", "background_status": "complete",
                            "diagrams_status": "complete", "expected_diagram_pages": [],
                            "expected_sub_question_ids": ["case1q1"], "reason": "已逐题核对"},
    }]
    methods = [{"id": "method1", "title": "关键路径", "type": "calculation",
                "applicability": "有活动时间", "formula": "求最长路径", "substitution": "5+5", "units": "天",
                "pitfalls": [], "steps": ["列活动"],
                "case_basis": [{"source_id": "bank", "page": 2, "excerpt": "活动时间"}],
                "answer_structure": "过程加结论", "sub_question_ids": ["case1q1"],
                "concept_ids": [], "evidence_ids": []}]
    return cases, methods


def check(cases, methods):
    return validate_cases_methods(cases, methods, sources=[{"id": "bank", "role": "question_bank", "page_count": 3}],
                                  concepts=[], evidence=[], question_ids=set())


def test_valid_case_only_contract():
    cases, methods = sample()
    normalized_cases, normalized_methods, report = check(cases, methods)
    assert report["status"] == "review_required"
    assert report["sub_question_count"] == 1
    assert normalized_cases == cases and normalized_methods == methods


@pytest.mark.parametrize("change", [
    lambda c, m: c[0].update(source_pages=[4]),
    lambda c, m: c[0]["sub_questions"][0]["reference_answer"].update(sub_question_id="wrong"),
    lambda c, m: c[0]["sub_questions"][0]["score"].update(source_pages=[4]),
    lambda c, m: c[0]["sub_questions"][0].update(id="../escape"),
    lambda c, m: c[0]["sub_questions"][0].update(method_ids=["unknown"]),
    lambda c, m: m[0].update(sub_question_ids=[]),
])
def test_rejects_untraceable_or_broken_links(change):
    cases, methods = sample()
    change(cases, methods)
    with pytest.raises(CaseContractError):
        check(cases, methods)


def test_quality_flags_missing_answer_and_calculation_basis():
    cases, methods = sample()
    answer = cases[0]["sub_questions"][0]["reference_answer"]
    answer["status"] = "missing"
    answer["text"] = ""
    answer.pop("source_id")
    answer.pop("source_pages")
    cases[0]["sub_questions"][0]["calculation_steps"][0]["input_basis"] = []
    cases[0]["coverage_review"]["status"] = "unverified"
    _, _, report = check(cases, methods)
    assert report["status"] == "review_required"
    assert {item["code"] for item in report["findings"]} >= {
        "CASE_REFERENCE_ANSWER_MISSING", "CASE_CALCULATION_INPUT_BASIS_MISSING", "CASE_COVERAGE_INCOMPLETE"}


def test_non_pdf_case_uses_empty_pages_and_unknown_basis_page():
    cases, methods = sample()
    cases[0]["source_pages"] = []
    cases[0]["sub_questions"][0]["source_pages"] = []
    cases[0]["sub_questions"][0]["reference_answer"]["source_pages"] = []
    cases[0]["sub_questions"][0]["score"]["source_pages"] = []
    cases[0]["sub_questions"][0]["scoring_points"][0]["source_pages"] = []
    cases[0]["sub_questions"][0]["calculation_steps"][0]["input_basis"][0]["page"] = None
    methods[0]["case_basis"][0].pop("page")
    _, _, report = validate_cases_methods(
        cases, methods, sources=[{"id": "bank", "role": "question_bank"}],
        concepts=[], evidence=[], question_ids=set())
    assert report["sub_question_count"] == 1


@pytest.mark.parametrize("field", ["background_status", "diagrams_status", "expected_diagram_pages"])
def test_missing_background_or_diagram_coverage_is_rejected(field):
    cases, methods = sample()
    del cases[0]["coverage_review"][field]
    with pytest.raises(CaseContractError):
        check(cases, methods)


def test_declared_diagram_omission_is_reported():
    cases, methods = sample()
    cases[0]["coverage_review"]["expected_diagram_pages"] = [2]
    _, _, report = check(cases, methods)
    assert any(item["code"] == "CASE_COVERAGE_INCOMPLETE" for item in report["findings"])


def test_unresolved_answer_requires_explicit_reason():
    cases, methods = sample()
    cases[0]["sub_questions"][0]["reference_answer"].update(status="unresolved", text="")
    with pytest.raises(CaseContractError, match="reason"):
        check(cases, methods)


def test_diagram_without_a_physical_page_is_rejected():
    cases, methods = sample()
    cases[0]["diagram_images"] = [{}]
    with pytest.raises(CaseContractError, match="图示必须引用 PDF 物理页"):
        check(cases, methods)


def test_case_only_concept_evidence_method_package_roundtrip(tmp_path):
    import json
    from reportlab.pdfgen import canvas
    from generator import AGENT_CONTENT_SCHEMA, generate_package

    for name in ("bank.pdf", "guide.pdf"):
        document = canvas.Canvas(str(tmp_path / name))
        for page_number in (1, 2):
            document.drawString(36, 800, f"synthetic page {page_number}")
            document.showPage()
        document.save()
    cases, methods = sample()
    child = cases[0]["sub_questions"][0]
    child["concept_ids"] = ["concept1"]
    child["evidence_ids"] = ["evidence1"]
    methods[0]["concept_ids"] = ["concept1"]
    methods[0]["evidence_ids"] = ["evidence1"]
    payload = {
        "schema_version": AGENT_CONTENT_SCHEMA, "questions": [],
        "concepts": [{"id": "concept1", "title": "进度计算", "source_questions": ["case1q1"],
                      "one_liner": "列活动时间并计算最长路径。",
                      "cornell_note": {"pairs": [{"cue": "怎么计算？", "note": "先列各路径再取最长。"}],
                                       "summary": "计算后核对单位。", "pairing_status": "paired"},
                      "teaching_evidence_ids": ["evidence1"]}],
        "sources": [{"id": "bank", "role": "question_bank", "path": "bank.pdf"},
                    {"id": "guide", "role": "teaching_material", "path": "guide.pdf"}],
        "teaching_evidence": [{"id": "evidence1", "source_id": "guide",
                               "status": "input_provided", "relation": "supports",
                               "concept_ids": ["concept1"],
                               "locator": {"page": 1, "excerpt": "先列各路径再取最长。"}}],
        "cases": cases, "methods": methods,
    }
    path = tmp_path / "agent.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output = generate_package(path, tmp_path / "package", profile_name="ruankao-xitixiangmu",
                              agent_content=True)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["question_count"], manifest["case_count"], manifest["sub_question_count"]) == (0, 1, 1)
    assert json.loads((output / "data" / "cases.json").read_text(encoding="utf-8"))[0]["sub_questions"][0]["id"] == "case1q1"
    assert json.loads((output / "data" / "methods.json").read_text(encoding="utf-8"))[0]["id"] == "method1"
