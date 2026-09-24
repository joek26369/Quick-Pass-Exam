"""Deterministic publication gate for one concept-generation batch.

Submitted questions are the required provenance. Textbooks are optional
enrichment and are intentionally absent from this contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

CONTRACT_VERSION = "question-origin-v1"


def _has_generated_content(concept: dict) -> bool:
    core = concept.get("core_concept")
    return bool(
        str(concept.get("one_liner") or "").strip()
        or (isinstance(core, dict) and any(str(value or "").strip() for value in core.values()))
    )


def evaluate_generation(
    concepts: Iterable[dict],
    question_ids: Iterable[str],
    *,
    generation_id: str,
    recipe: dict | None = None,
) -> dict:
    """Check the complete batch and retain concept-level retry units."""
    allowed = {str(qid) for qid in question_ids if str(qid).strip()}
    concept_results: list[dict] = []
    findings: list[dict] = []
    seen: set[str] = set()
    for position, raw in enumerate(concepts):
        concept = raw if isinstance(raw, dict) else {}
        concept_id = str(concept.get("id") or "").strip()
        sources = concept.get("source_questions")
        codes: list[str] = []
        if not isinstance(sources, list):
            sources = []
        normalized = list(dict.fromkeys(str(qid) for qid in sources if str(qid).strip()))
        if not concept_id:
            codes.append("CONCEPT_ID_MISSING")
        elif concept_id in seen:
            codes.append("CONCEPT_ID_DUPLICATE")
        seen.add(concept_id)
        if not normalized:
            codes.append("QUESTION_ORIGIN_MISSING")
        if any(qid not in allowed for qid in normalized):
            codes.append("QUESTION_ORIGIN_OUTSIDE_BATCH")
        generated_content_ok = _has_generated_content(concept)
        if not generated_content_ok:
            codes.append("GENERATED_CONTENT_EMPTY")
        status = "passed" if not codes else "review_required"
        concept_results.append({
            "concept_id": concept_id,
            "question_ids": normalized,
            "generated_content_ok": generated_content_ok,
            "note_id": concept_id,
            "note_version": hashlib.sha256(
                json.dumps(concept, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "status": status,
        })
        for code in codes:
            findings.append({
                "concept_id": concept_id or f"position:{position}",
                "code": code,
                "severity": "S1" if code.startswith("QUESTION_ORIGIN") else "S2",
            })
    if not concept_results:
        findings.append({"concept_id": "", "code": "GENERATION_EMPTY", "severity": "S1"})
    recipe_value = recipe or {}
    return {
        "contract_version": CONTRACT_VERSION,
        "generation_id": generation_id,
        "status": "passed" if not findings else "review_required",
        "recipe": recipe_value,
        "recipe_fingerprint": hashlib.sha256(
            json.dumps(recipe_value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "question_ids": sorted(allowed),
        "question_count": len(allowed),
        "concept_count": len(concept_results),
        "passed_count": sum(1 for item in concept_results if item["status"] == "passed"),
        "review_required_count": sum(1 for item in concept_results if item["status"] != "passed"),
        "concepts": concept_results,
        "findings": findings,
    }


def write_report(path: str | os.PathLike[str], report: dict) -> None:
    """Atomically expose the report to the parent web task."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


CARD_CONTENT_CONTRACT_VERSION = "card-content-v1"
LEARNING_SUPPORT_FIELDS = (
    "mnemonic", "visualization", "principle", "comparisons", "best_practices", "why_tested",
)


def _has_learning_support(card: dict, field: str) -> bool:
    core = card.get("core_concept")
    core = core if isinstance(core, dict) else {}
    if field == "comparisons":
        comparisons = core.get("comparisons")
        types = core.get("type_comparison")
        return (isinstance(comparisons, list) and any(
            isinstance(row, dict) and _has_meaningful_content(row.get("vs"))
            and _has_meaningful_content(row.get("difference")) for row in comparisons
        )) or (isinstance(types, list) and any(
            isinstance(row, dict) and _has_meaningful_content(row.get("type"))
            and (_has_meaningful_content(row.get("syntax_example"))
                 or _has_meaningful_content(row.get("key_rules"))) for row in types
        ))
    if field == "principle":
        return isinstance(core.get("principle"), str) and _has_meaningful_content(core.get("principle"))
    if field == "visualization":
        visual = card.get("visualization")
        return (isinstance(visual, dict) and visual.get("type") in {
                    "architecture", "flow", "hierarchy", "comparison", "table", "mindmap", "process", "quadrant"
                }
                and isinstance(visual.get("nodes"), list)
                and any(isinstance(node, str) and _card_text(node)
                        and not _card_placeholder(node) for node in visual["nodes"]))
    if field == "best_practices":
        value = card.get(field)
        return isinstance(value, list) and any(
            isinstance(item, str) and _has_meaningful_content(item) for item in value)
    value = card.get(field)
    return isinstance(value, str) and _has_meaningful_content(value)


def _has_meaningful_content(value: object) -> bool:
    return any(_card_text(text) and not _card_placeholder(text)
               for _, text in _card_leaves(value))


def _card_text(value: object) -> str:
    """Normalize layout only; preserve punctuation, formulas and actual wording."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).strip()
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`",
                  lambda match: next(group for group in match.groups() if group is not None), text)
    return re.sub(r"\s+", "", text)


def _card_equivalence_text(value: object) -> str:
    """Ignore only terminal sentence punctuation in mechanical copy checks."""
    return re.sub(r"[。.!！?？;；:：,，、…]+$", "", _card_text(value))


def _near_duplicate(left: str, right: str) -> bool:
    # Conservative: short facts and formulas often need exact repetition.
    return min(len(left), len(right)) >= 40 and SequenceMatcher(
        None, left, right, autojunk=False,
    ).ratio() >= 0.94


def _card_leaves(value: object, prefix: str = ""):
    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _card_leaves(child, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _card_leaves(child, f"{prefix}[{index}]")


def _card_placeholder(value: object) -> bool:
    # Whole-field placeholders only: never reject a lesson that explains TODO.
    return bool(re.fullmatch(
        r"(?:todo|tbd|待补充|待完善|待填写|待生成|暂无内容|占位|占位文字|原文节选占位|placeholder)[。.!！:：…]*",
        _card_text(value), flags=re.IGNORECASE,
    ))


def evaluate_card_content(
    concepts: Iterable[dict], questions: Iterable[dict], teaching_evidence: Iterable[dict] = (),
) -> dict:
    """Detect mechanical defects and record (not independently verify) Agent review.

    No word-count or card/question-ratio thresholds certify teaching quality.
    Missing textbooks are an explicit coverage limitation, never a hard failure.
    The question-origin-v1 gate above deliberately retains its legacy behavior.
    """
    cards, question_rows, evidence_rows = list(concepts), list(questions), list(teaching_evidence)
    results, findings = [], []
    metrics = dict.fromkeys((
        "blocked_count", "review_required_count", "agent_reviewed_count", "limited_count",
        "triple_duplicate_count", "placeholder_count", "one_question_card_count",
        "concepts_with_supports", "concepts_with_related", "concepts_without_teaching_evidence",
        "concepts_without_supports",
    ), 0)
    metrics.update(concept_count=len(cards), question_count=len(question_rows))
    learning_counts = {field: {"present": 0, "missing": 0, "included": 0,
                               "not_applicable": 0, "insufficient_evidence": 0,
                               "unexplained_missing": 0} for field in LEARNING_SUPPORT_FIELDS}
    for position, raw in enumerate(cards):
        card = raw if isinstance(raw, dict) else {}
        cid = str(card.get("id") or f"position:{position}")
        local = []

        def finding(code, severity, message, field=None):
            item = dict(concept_id=cid, code=code, severity=severity, message=message)
            if field is not None:
                item["field"] = field
            local.append(item)
            findings.append(item)

        support_review = card.get("learning_support_review")
        support_review = support_review if isinstance(support_review, dict) else {}
        support_result = {}
        for field in LEARNING_SUPPORT_FIELDS:
            present = _has_learning_support(card, field)
            counts = learning_counts[field]
            counts["present" if present else "missing"] += 1
            decision = support_review.get(field)
            decision = decision if isinstance(decision, dict) else {}
            decision_status = decision.get("status")
            reason = decision.get("reason")
            valid_reason = (isinstance(reason, str) and bool(_card_text(reason))
                            and not _card_placeholder(reason))
            valid_status = decision_status in {"included", "not_applicable", "insufficient_evidence"}
            if valid_status:
                counts[decision_status] += 1
            support_result[field] = {"present": present, "status": decision_status if valid_status else None,
                                     "reason": reason if valid_reason else None}
            if not valid_status or not valid_reason:
                if not present:
                    counts["unexplained_missing"] += 1
                finding("CARD_LEARNING_SUPPORT_REVIEW_MISSING", "review",
                        "学习辅助模块缺少有效的逐卡适用性判断和具体理由。", field)
            elif decision_status == "included" and not present:
                counts["unexplained_missing"] += 1
                finding("CARD_LEARNING_SUPPORT_INCLUDED_EMPTY", "review",
                        "声明已纳入学习辅助模块，但对应展示字段为空。", field)
            elif decision_status != "included" and present:
                finding("CARD_LEARNING_SUPPORT_STATUS_CONFLICT", "review",
                        "字段已有内容，但逐卡判断未标为 included。", field)

        cornell = card.get("cornell_note")
        cornell = cornell if isinstance(cornell, dict) else {}
        pairs = cornell.get("pairs")
        pairs = pairs if isinstance(pairs, list) else []
        notes = [_card_equivalence_text(pair.get("note")) for pair in pairs if isinstance(pair, dict)]
        one, summary = _card_equivalence_text(card.get("one_liner")), _card_equivalence_text(cornell.get("summary"))
        if pairs and len(notes) == len(pairs) and one and all(note == one for note in notes) and summary == one:
            metrics["triple_duplicate_count"] += 1
            finding("CARD_TRIPLE_DUPLICATE", "blocker", "结论、全部 Cornell 解释和摘要整段重复，须重新编写。")
        elif (pairs and len(notes) == len(pairs) and one and summary
              and _near_duplicate(one, summary)
              and all(_near_duplicate(one, note) for note in notes)):
            finding("CARD_NEAR_DUPLICATE", "review", "结论、全部 Cornell 解释和摘要几乎是同一长段，请实质重写并复审。")

        for root in ("one_liner", "core_concept", "cornell_note", "mnemonic", "common_mistakes", "best_practices"):
            for field, value in _card_leaves(card.get(root), root):
                if _card_placeholder(value):
                    metrics["placeholder_count"] += 1
                    finding("CARD_PLACEHOLDER", "blocker", "教学字段仍为占位内容。", field)

        core = card.get("core_concept")
        repeated = {one, summary, _card_equivalence_text(card.get("title"))}
        repeated.update(_card_equivalence_text(pair.get("cue")) for pair in pairs if isinstance(pair, dict))
        generic = {"请记住此知识点", "请记住本知识点", "本卡介绍此知识点", "详见原题解析"}
        core_body = isinstance(core, dict) and any(
            (text := _card_equivalence_text(value)) and text not in repeated and text not in generic
            and not _card_placeholder(value) for _, value in _card_leaves(core)
        )
        note_body = any(
            (text := _card_equivalence_text(pair.get("note"))) and not _card_placeholder(pair.get("note"))
            and text not in repeated and text not in generic
            for pair in pairs if isinstance(pair, dict)
        )
        body_ok = bool(core_body or note_body)
        if not body_ok:
            finding("CARD_BODY_REVIEW_REQUIRED", "review", "未发现独立正文或区别于结论、自测题干和摘要的解释，请审查教学内容。")

        coverage = dict(supports=0, related=0, other=0, total=0)
        for evidence in evidence_rows:
            if not isinstance(evidence, dict) or cid not in evidence.get("concept_ids", []):
                continue
            coverage["total"] += 1
            relation = evidence.get("relation")
            coverage[relation if relation in {"supports", "related"} else "other"] += 1
        metrics["concepts_with_supports"] += bool(coverage["supports"])
        metrics["concepts_with_related"] += bool(coverage["related"])
        metrics["concepts_without_teaching_evidence"] += not coverage["total"]
        metrics["concepts_without_supports"] += not coverage["supports"]
        if not coverage["supports"]:
            finding("CARD_NO_DIRECT_TEACHING_SUPPORT", "info", "未关联标注为 supports 的教辅证据；须说明题库依据与支持范围，related 不等同直接支持。")
        sources = card.get("source_questions")
        if isinstance(sources, list) and len(set(map(str, sources))) == 1:
            metrics["one_question_card_count"] += 1
            finding("CARD_SINGLE_QUESTION", "info", "该卡关联一道题；请在知识点规划中判断是否有共享规则，数量本身不构成缺陷。")

        review = card.get("content_review")
        review_valid = (
            isinstance(review, dict) and review.get("reviewer") == "agent"
            and review.get("status") in {"reviewed", "needs_revision", "limited"}
            and bool(_card_text(review.get("rationale")))
            and not _card_placeholder(review.get("rationale"))
        )
        if not review_valid:
            finding("CARD_REVIEW_MISSING_OR_INVALID", "review", "缺少有效 Agent 审校声明：reviewer、status 及具体 rationale。")
        elif review["status"] == "needs_revision":
            finding("CARD_AGENT_REQUESTED_REVISION", "review", "Agent 审校声明仍需修订。")
        if any(item["severity"] == "blocker" for item in local):
            status = "blocked"
        elif any(item["severity"] == "review" for item in local):
            status = "review_required"
        else:
            status = "limited" if review["status"] == "limited" else "agent_reviewed"
        metrics[f"{status}_count"] += 1
        results.append(dict(concept_id=cid, status=status, has_substantive_body=body_ok,
                            review_metadata_valid=bool(review_valid), teaching_evidence=coverage,
                            learning_support=support_result,
                            findings=[item["code"] for item in local]))
    if not cards:
        findings.append(dict(concept_id="", code="CARD_BATCH_EMPTY", severity="review",
                             message="没有可审校的知识卡片。"))
    for field in ("mnemonic", "visualization"):
        if cards and not learning_counts[field]["present"]:
            findings.append(dict(concept_id="", code="PACKAGE_LEARNING_SUPPORT_ZERO", severity="review",
                                 field=field, message="整包此学习辅助模块为零，须复核每卡适用性及证据；单卡可以合理不适用。"))
    if cards and any(item["severity"] == "review" and not item["concept_id"] for item in findings):
        metrics["package_review_required"] = True
    status = next((value for value in ("blocked", "review_required", "limited")
                   if metrics[f"{value}_count"]), "agent_reviewed" if cards else "review_required")
    if status in {"agent_reviewed", "limited"} and metrics.get("package_review_required"):
        status = "review_required"
    return dict(contract_version=CARD_CONTENT_CONTRACT_VERSION, status=status,
                semantic_verification="not_performed", concepts=results,
                findings=findings, metrics=metrics, learning_support_coverage=learning_counts)
