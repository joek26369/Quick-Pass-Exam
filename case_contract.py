"""Deterministic structural checks for Agent supplied case study content.

These checks establish traceability and shape, never semantic correctness.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any


class CaseContractError(ValueError):
    pass


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _fail(where: str, message: str) -> None:
    raise CaseContractError(f"{where}: {message}")


def _id(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(where, "必须是安全、非空的稳定 ID")
    return value


def _text(value: Any, where: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        _fail(where, "必须是字符串" + ("且不可为空" if required else ""))
    return value


def _ids(value: Any, where: str, known: set[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        _fail(where, "必须是数组")
    result = [_id(item, where) for item in value]
    if len(set(result)) != len(result):
        _fail(where, "不得重复")
    if known is not None and not set(result) <= known:
        _fail(where, f"引用不存在的 ID：{sorted(set(result) - known)}")
    return result


def _pages(value: Any, source_id: str, where: str, sources: dict[str, dict]) -> list[int]:
    if source_id not in sources:
        _fail(where, f"来源不存在：{source_id}")
    if not isinstance(value, list):
        _fail(where, "必须填写来源页码数组")
    count = sources[source_id].get("page_count")
    if count is None:
        if value:
            _fail(where, "非 PDF 来源不得填写物理页码")
        return value
    if not isinstance(count, int) or isinstance(count, bool) or not value:
        _fail(where, "PDF 来源必须填写物理页码")
    if any(isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= count for p in value):
        _fail(where, "物理页码越界")
    if len(set(value)) != len(value):
        _fail(where, "物理页码重复")
    return value


def _basis(value: Any, where: str, sources: dict[str, dict], *, required: bool = False) -> list[dict]:
    if not isinstance(value, list) or (required and not value):
        _fail(where, "必须是" + ("非空" if required else "") + "数组")
    for i, item in enumerate(value):
        label = f"{where}[{i}]"
        if not isinstance(item, dict):
            _fail(label, "必须是对象")
        sid = _id(item.get("source_id"), label + ".source_id")
        if sources.get(sid, {}).get("role") != "question_bank":
            _fail(label + ".source_id", "案例输入依据必须引用 question_bank")
        page = item.get("page")
        _pages([page] if page is not None else [], sid, label + ".page", sources)
        _text(item.get("excerpt"), label + ".excerpt")
    return value


def _scoring_basis(value: list[dict], where: str, sources: dict[str, dict]) -> None:
    for i, item in enumerate(value):
        label = f"{where}[{i}]"
        sid = _id(item.get("source_id"), label + ".source_id")
        if sources.get(sid, {}).get("role") != "question_bank":
            _fail(label + ".source_id", "评分出处必须引用 question_bank")
        _pages(item.get("source_pages"), sid, label + ".source_pages", sources)
        _text(item.get("excerpt"), label + ".excerpt")


def validate_cases_methods(raw_cases: Any, raw_methods: Any, *, sources: list[dict],
                           concepts: list[dict], evidence: list[dict],
                           question_ids: set[str]) -> tuple[list[dict], list[dict], dict]:
    if not isinstance(raw_cases, list) or not isinstance(raw_methods, list):
        _fail("cases/methods", "必须是数组")
    cases, methods = copy.deepcopy(raw_cases), copy.deepcopy(raw_methods)
    source_map = {s["id"]: s for s in sources}
    concept_ids = {c["id"] for c in concepts}
    evidence_ids = {e["id"] for e in evidence}
    method_ids = {_id(m.get("id") if isinstance(m, dict) else None, f"methods[{i}].id")
                  for i, m in enumerate(methods)}
    if len(method_ids) != len(methods):
        _fail("methods", "ID 不得重复")
    case_ids: set[str] = set()
    child_ids: set[str] = set()
    findings: list[dict] = []
    for i, case in enumerate(cases):
        where = f"cases[{i}]"
        if not isinstance(case, dict):
            _fail(where, "必须是对象")
        cid = _id(case.get("id"), where + ".id")
        if cid in case_ids or cid in child_ids or cid in question_ids or cid in concept_ids or cid in method_ids:
            _fail(where + ".id", "ID 重复")
        case_ids.add(cid)
        _text(case.get("original_number"), where + ".original_number")
        sid = _id(case.get("source_id"), where + ".source_id")
        if source_map.get(sid, {}).get("role") != "question_bank":
            _fail(where + ".source_id", "必须引用 question_bank")
        case_pages = _pages(case.get("source_pages"), sid, where + ".source_pages", source_map)
        _text(case.get("scenario"), where + ".scenario")
        diagrams = case.get("diagram_images")
        if not isinstance(diagrams, list) or any(not isinstance(x, dict) for x in diagrams):
            _fail(where + ".diagram_images", "必须是对象数组")
        for j, diagram in enumerate(diagrams):
            page = diagram.get("page")
            if page is None or source_map[sid].get("page_count") is None:
                _fail(f"{where}.diagram_images[{j}].page", "图示必须引用 PDF 物理页")
            _pages([page], sid, f"{where}.diagram_images[{j}].page", source_map)
            if page not in case_pages:
                _fail(where + ".diagram_images", "图片页必须属于案例来源页")
        children = case.get("sub_questions")
        if not isinstance(children, list) or not children:
            _fail(where + ".sub_questions", "必须是非空数组")
        local_ids: set[str] = set()
        for j, child in enumerate(children):
            sub = f"{where}.sub_questions[{j}]"
            if not isinstance(child, dict):
                _fail(sub, "必须是对象")
            subid = _id(child.get("id"), sub + ".id")
            if subid in child_ids or subid in question_ids or subid in case_ids or subid in concept_ids or subid in method_ids:
                _fail(sub + ".id", "全局 ID 重复")
            child_ids.add(subid); local_ids.add(subid)
            _text(child.get("original_number"), sub + ".original_number")
            _text(child.get("type"), sub + ".type")
            _text(child.get("question"), sub + ".question")
            pages = _pages(child.get("source_pages"), sid, sub + ".source_pages", source_map)
            if not set(pages) <= set(case_pages):
                _fail(sub + ".source_pages", "小题来源页必须属于案例来源页")
            answer = child.get("reference_answer")
            if not isinstance(answer, dict):
                _fail(sub + ".reference_answer", "必须是对象")
            status = answer.get("status")
            if status not in {"verified", "missing", "unresolved"}:
                _fail(sub + ".reference_answer.status", "状态无效")
            _text(answer.get("text"), sub + ".reference_answer.text", required=status == "verified")
            if answer.get("sub_question_id") != subid:
                _fail(sub + ".reference_answer.sub_question_id", "必须精确匹配小题 ID")
            if status == "verified" or answer.get("source_id") is not None:
                answer_sid = _id(answer.get("source_id"), sub + ".reference_answer.source_id")
                if source_map.get(answer_sid, {}).get("role") != "question_bank":
                    _fail(sub + ".reference_answer.source_id", "必须引用 question_bank")
                _pages(answer.get("source_pages"), answer_sid,
                       sub + ".reference_answer.source_pages", source_map)
            elif answer.get("source_pages") not in (None, []):
                _fail(sub + ".reference_answer.source_pages", "无来源时不得填写页码")
            if status == "unresolved":
                _text(answer.get("reason"), sub + ".reference_answer.reason")
            if status != "verified":
                findings.append({"code": "CASE_REFERENCE_ANSWER_" + status.upper(), "id": subid})
            _text(child.get("generated_analysis"), sub + ".generated_analysis", required=False)
            if child.get("generated_analysis") and not child.get("evidence_ids"):
                findings.append({"code": "CASE_ANALYSIS_EVIDENCE_MISSING", "id": subid})
            for field in ("pitfalls",):
                if not isinstance(child.get(field), list) or any(not isinstance(v, str) for v in child[field]):
                    _fail(sub + "." + field, "必须是字符串数组")
            _ids(child.get("concept_ids"), sub + ".concept_ids", concept_ids)
            _ids(child.get("evidence_ids"), sub + ".evidence_ids", evidence_ids)
            _ids(child.get("method_ids"), sub + ".method_ids", method_ids)
            steps = child.get("calculation_steps")
            if not isinstance(steps, list):
                _fail(sub + ".calculation_steps", "必须是数组")
            for k, step in enumerate(steps):
                label = f"{sub}.calculation_steps[{k}]"
                if not isinstance(step, dict):
                    _fail(label, "必须是对象")
                _text(step.get("text"), label + ".text")
                basis = _basis(step.get("input_basis"), label + ".input_basis", source_map)
                if not basis:
                    findings.append({"code": "CASE_CALCULATION_INPUT_BASIS_MISSING", "id": subid, "step": k})
            score = child.get("score")
            if score is not None:
                if not isinstance(score, dict) or isinstance(score.get("max_points"), bool) or not isinstance(score.get("max_points"), (int, float)) or not math.isfinite(score["max_points"]) or score["max_points"] <= 0:
                    _fail(sub + ".score", "max_points 必须是正数")
                _scoring_basis([score], sub + ".score", source_map)
            points = child.get("scoring_points", [])
            if not isinstance(points, list):
                _fail(sub + ".scoring_points", "必须是数组")
            for k, point in enumerate(points):
                if not isinstance(point, dict):
                    _fail(f"{sub}.scoring_points[{k}]", "必须是对象")
                _text(point.get("text"), f"{sub}.scoring_points[{k}].text")
            _scoring_basis(points, sub + ".scoring_points", source_map)
        review = case.get("coverage_review")
        allowed_review = {"complete", "incomplete", "unverified"}
        if not isinstance(review, dict) or review.get("status") not in allowed_review:
            _fail(where + ".coverage_review", "缺少有效覆盖审查状态")
        for field in ("background_status", "diagrams_status"):
            if review.get(field) not in allowed_review:
                _fail(where + ".coverage_review." + field, "缺少有效覆盖审查状态")
        expected = _ids(review.get("expected_sub_question_ids"), where + ".coverage_review.expected_sub_question_ids")
        expected_diagrams = review.get("expected_diagram_pages")
        if not isinstance(expected_diagrams, list) or any(isinstance(p, bool) or not isinstance(p, int) for p in expected_diagrams):
            _fail(where + ".coverage_review.expected_diagram_pages", "必须是物理页码数组")
        if sid in source_map and source_map[sid].get("page_count") is not None:
            for page in expected_diagrams:
                _pages([page], sid, where + ".coverage_review.expected_diagram_pages", source_map)
        elif expected_diagrams:
            _fail(where + ".coverage_review.expected_diagram_pages", "非 PDF 不得声明图片物理页")
        _text(review.get("reason"), where + ".coverage_review.reason", required=False)
        actual_diagrams = {d["page"] for d in diagrams if d.get("page") is not None}
        if (set(expected) != local_ids or review["status"] != "complete"
                or review["background_status"] != "complete" or review["diagrams_status"] != "complete"
                or set(expected_diagrams) != actual_diagrams):
            findings.append({"code": "CASE_COVERAGE_INCOMPLETE", "id": cid,
                             "declared_status": review["status"], "expected": expected,
                             "actual": sorted(local_ids), "expected_diagram_pages": expected_diagrams,
                             "actual_diagram_pages": sorted(actual_diagrams)})
    all_ids = child_ids
    for i, method in enumerate(methods):
        where = f"methods[{i}]"
        if not isinstance(method, dict):
            _fail(where, "必须是对象")
        mid = method["id"]
        if mid in question_ids or mid in case_ids or mid in child_ids or mid in concept_ids:
            _fail(where + ".id", "全局 ID 重复")
        if method.get("type") not in {"calculation", "answering"}:
            _fail(where + ".type", "类型无效")
        for field in ("title", "applicability", "formula", "substitution", "units", "answer_structure"):
            _text(method.get(field), where + "." + field, required=field in {"title", "applicability"})
        for field in ("pitfalls", "steps"):
            if not isinstance(method.get(field), list) or any(not isinstance(v, str) for v in method[field]):
                _fail(where + "." + field, "必须是字符串数组")
        _basis(method.get("case_basis"), where + ".case_basis", source_map)
        _ids(method.get("sub_question_ids"), where + ".sub_question_ids", all_ids)
        _ids(method.get("concept_ids"), where + ".concept_ids", concept_ids)
        _ids(method.get("evidence_ids"), where + ".evidence_ids", evidence_ids)
        if not method["evidence_ids"]:
            findings.append({"code": "METHOD_EVIDENCE_MISSING", "id": mid})
        if method["type"] == "calculation" and not method["case_basis"]:
            findings.append({"code": "METHOD_CASE_BASIS_MISSING", "id": mid})
        if method["type"] == "calculation" and (not method["formula"].strip() or not method["steps"]):
            findings.append({"code": "METHOD_CALCULATION_INCOMPLETE", "id": mid})
    for case in cases:
        for child in case["sub_questions"]:
            for mid in child["method_ids"]:
                if child["id"] not in next(m for m in methods if m["id"] == mid)["sub_question_ids"]:
                    _fail(child["id"] + ".method_ids", "method.sub_question_ids 必须双向一致")
    for method in methods:
        for subid in method["sub_question_ids"]:
            child = next(s for c in cases for s in c["sub_questions"] if s["id"] == subid)
            if method["id"] not in child["method_ids"]:
                _fail(method["id"] + ".sub_question_ids", "小题 method_ids 必须双向一致")
    report = {"status": "passed" if not findings else "review_required",
              "validation": "deterministic_structural_only", "semantic_verification": "not_performed",
              "case_count": len(cases), "sub_question_count": len(child_ids),
              "method_count": len(methods), "findings": findings}
    return cases, methods, report
