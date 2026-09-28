"""One-shot local package generation for Quick Pass Exam."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import re
import copy
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))


class ContractError(ValueError):
    pass


AGENT_CONTENT_SCHEMA = "quick-pass-agent-content-v2"
_SOURCE_ROLES = {"question_bank", "teaching_material"}
_EVIDENCE_STATUSES = {"input_provided", "unverified"}
_EVIDENCE_RELATIONS = {"supports", "context", "related", "contradicts"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"无法读取 JSON：{path}: {exc}") from exc


def validate_questions(payload: Any) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        raise ContractError("输入根对象必须包含 questions 数组")
    questions = payload["questions"]
    if not questions and not (payload.get("schema_version") == AGENT_CONTENT_SCHEMA and payload.get("cases")):
        raise ContractError("questions 不能为空")
    seen: set[str] = set()
    for pos, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ContractError(f"questions[{pos}] 必须是对象")
        if not isinstance(q.get("id"), str):
            raise ContractError(f"questions[{pos}].id 必须是字符串")
        qid = q["id"].strip()
        if not qid or qid in seen:
            raise ContractError(f"questions[{pos}].id 缺失或重复：{qid!r}")
        seen.add(qid)
        if not str(q.get("question_zh") or q.get("question_en") or "").strip():
            raise ContractError(f"题目 {qid} 缺少题干")
        options = q.get("options")
        if not isinstance(options, list) or not options:
            raise ContractError(f"题目 {qid} 缺少 options")
        labels = [str(o.get("label") or "").strip().upper() for o in options if isinstance(o, dict)]
        if len(labels) != len(options) or any(not x for x in labels) or len(set(labels)) != len(labels):
            raise ContractError(f"题目 {qid} 的选项 label 缺失或重复")
        for index, option in enumerate(options):
            text = option.get("text") or option.get("text_zh") or option.get("text_en")
            if not isinstance(text, str) or not text.strip():
                raise ContractError(f"题目 {qid} 的选项 {labels[index]} 缺少非空文本")
        flags = [o.get("is_correct") for o in options]
        if any(not isinstance(flag, bool) for flag in flags):
            raise ContractError(f"题目 {qid} 的 is_correct 必须是 JSON boolean")
        correct = {labels[i] for i, flag in enumerate(flags) if flag}
        for field in ("correct_answer", "answer"):
            if field in q and q[field] is not None and not isinstance(q[field], str):
                raise ContractError(f"题目 {qid} 的 {field} 必须是字符串")
        if not correct:
            raise ContractError(f"题目 {qid} 没有 is_correct=true 的选项")
        supplied_answers = []
        for field in ("correct_answer", "answer"):
            if field not in q or q[field] is None:
                continue
            answer = {c for c in q[field].upper() if c in labels}
            residual = re.sub(r"[A-F、，,\s和及与跟]", "", q[field].upper())
            if not q[field].strip() or not answer or residual:
                raise ContractError(f"题目 {qid} 的 {field} 含空值或未知选项")
            if answer != correct:
                raise ContractError(f"题目 {qid} 的答案字段 {field} 与 is_correct 不一致")
            supplied_answers.append((field, answer))
        if len(supplied_answers) == 2 and supplied_answers[0][1] != supplied_answers[1][1]:
            raise ContractError(f"题目 {qid} 的 answer 与 correct_answer 不一致")
    return questions


def _stable_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} 必须是非空稳定字符串 ID")
    return value.strip()


def _source_path(value: Any, input_dir: Path, field: str) -> tuple[str, Path]:
    """Validate an Agent-declared local source path without following escapes."""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} 必须是非空相对路径")
    relative = Path(value.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError(f"{field} 不得使用绝对路径或越界路径")
    candidate = input_dir / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"{field} 指向的原始文件不存在或不是普通文件")
    resolved_root, resolved = input_dir.resolve(), candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ContractError(f"{field} 越出输入目录") from exc
    return relative.as_posix(), resolved


def _physical_pdf_page_count(path: Path) -> int:
    try:
        from pdf_backend import physical_page_count
        return physical_page_count(path)
    except ImportError as exc:  # pragma: no cover - requirements-import declares it
        raise ContractError("校验 PDF 物理页码需要 pypdfium2 和 Pillow") from exc
    except Exception as exc:
        raise ContractError(f"无法读取 PDF 原始文件以校验物理页码：{path.name}") from exc


def _validate_agent_content(payload: dict[str, Any], questions: list[dict],
                            concepts: list[dict], input_dir: Path) -> tuple[list[dict], list[dict]]:
    """Validate the sole Agent contract; never infer semantic support."""
    if "materials" in payload:
        raise ContractError("Agent v2 不接受旧 materials 字段；请使用 sources")
    raw_sources = payload.get("sources")
    raw_evidence = payload.get("teaching_evidence")
    if not isinstance(raw_sources, list):
        raise ContractError("sources 必须是数组")
    if not isinstance(raw_evidence, list):
        raise ContractError("teaching_evidence 必须是数组")

    sources: list[dict] = []
    by_source_id: dict[str, dict] = {}
    page_counts: dict[str, int] = {}
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            raise ContractError(f"sources[{index}] 必须是对象")
        source = copy.deepcopy(raw)
        if "source_file" in source:
            raise ContractError(f"sources[{index}] 不接受旧 source_file 字段；请使用 path")
        source_id = _stable_id(source.get("id"), f"sources[{index}].id")
        if source_id in by_source_id:
            raise ContractError(f"sources.id 重复：{source_id}")
        role = source.get("role")
        if role not in _SOURCE_ROLES:
            raise ContractError("sources.role 只能是 question_bank 或 teaching_material")
        relative, actual = _source_path(source.get("path"), input_dir, f"sources[{index}].path")
        if any(existing["path"] == relative for existing in sources):
            raise ContractError(f"sources.path 重复：{relative}")
        actual_hash = hashlib.sha256(actual.read_bytes()).hexdigest()
        supplied_hash = source.get("sha256")
        if supplied_hash is not None:
            if not isinstance(supplied_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_hash):
                raise ContractError(f"sources[{index}].sha256 必须是 SHA-256 十六进制串")
            if supplied_hash.lower() != actual_hash:
                raise ContractError(f"sources[{index}].sha256 与原始文件不一致")
        source["id"], source["path"], source["sha256"] = source_id, relative, actual_hash
        by_source_id[source_id] = source
        if actual.suffix.lower() == ".pdf":
            page_count = _physical_pdf_page_count(actual)
            supplied_count = source.get("page_count")
            if supplied_count is not None and supplied_count != page_count:
                raise ContractError(f"sources[{index}].page_count 与 PDF 实际物理页数不一致")
            source["page_count"] = page_count
            page_counts[source_id] = page_count
        sources.append(source)

    # The Agent declares only a stable source edge. The local source_file is a
    # derived renderer field, never a second input spelling or lookup signal.
    for question in questions:
        if "source_file" in question or "page_no" in question:
            raise ContractError(f"题目 {question['id']} 只能使用 source_id/source_page 声明来源")
        q_source_id = _stable_id(question.get("source_id"), f"题目 {question['id']}.source_id")
        if q_source_id not in by_source_id:
            raise ContractError(f"题目 {question['id']} 引用了不存在的 source_id：{q_source_id}")
        source = by_source_id[q_source_id]
        if source["role"] != "question_bank":
            raise ContractError(f"题目 {question['id']}.source_id 必须引用 role=question_bank 的 source")
        question["source_file"] = source["path"]
        page = question.get("source_page")
        if q_source_id in page_counts:
            if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= page_counts[q_source_id]:
                raise ContractError(f"题目 {question['id']}.source_page 必须是 question_bank PDF 的有效物理页")
        elif page not in (None, ""):
            raise ContractError(f"非 PDF 题目 {question['id']} 不得填写 source_page")

    known_concept_ids = {_stable_id(c.get("id"), "concept.id") for c in concepts}
    raw_cases = payload.get("cases", [])
    case_child_links: dict[str, set[str]] = {}
    if isinstance(raw_cases, list):
        for case in raw_cases:
            if not isinstance(case, dict) or not isinstance(case.get("sub_questions"), list):
                continue  # the case contract reports the precise shape error later
            for child in case["sub_questions"]:
                if isinstance(child, dict) and isinstance(child.get("id"), str):
                    ids = child.get("concept_ids", [])
                    if isinstance(ids, list):
                        case_child_links[child["id"]] = set(ids)
    question_links: dict[str, set[str]] = {}
    for question in questions:
        concept_ids = question.get("concept_ids")
        if not isinstance(concept_ids, list) or not concept_ids:
            raise ContractError(f"题目 {question['id']}.concept_ids 必须是非空数组")
        question_links[question["id"]] = {
            _stable_id(cid, f"题目 {question['id']}.concept_ids") for cid in concept_ids
        }
        unknown = question_links[question["id"]] - known_concept_ids
        if unknown:
            raise ContractError(f"题目 {question['id']} 引用了不存在的 concept：{sorted(unknown)}")
    concept_links: dict[str, set[str]] = {}
    known_question_ids = set(question_links) | set(case_child_links)
    for concept in concepts:
        source_questions = concept.get("source_questions")
        if not isinstance(source_questions, list) or not source_questions:
            raise ContractError(f"concept {concept['id']}.source_questions 必须是非空数组")
        linked = {_stable_id(qid, f"concept {concept['id']}.source_questions") for qid in source_questions}
        unknown = linked - known_question_ids
        if unknown:
            raise ContractError(f"concept {concept['id']} 引用了不存在的题目：{sorted(unknown)}")
        concept_links[concept["id"]] = linked
    for question_id, linked_concepts in question_links.items():
        reverse = {cid for cid, qids in concept_links.items() if question_id in qids}
        if linked_concepts != reverse:
            raise ContractError(f"题目 {question_id} 与 concept.source_questions 必须双向一致")
    for child_id, linked_concepts in case_child_links.items():
        reverse = {cid for cid, qids in concept_links.items() if child_id in qids}
        if linked_concepts != reverse:
            raise ContractError(f"案例小题 {child_id} 与 concept.source_questions 必须双向一致")

    evidence: list[dict] = []
    by_evidence_id: dict[str, dict] = {}
    concept_to_evidence: dict[str, set[str]] = {cid: set() for cid in known_concept_ids}
    for index, raw in enumerate(raw_evidence):
        if not isinstance(raw, dict):
            raise ContractError(f"teaching_evidence[{index}] 必须是对象")
        item = copy.deepcopy(raw)
        if "material_id" in item:
            raise ContractError(f"teaching_evidence[{index}] 不接受旧 material_id 字段；请使用 source_id")
        evidence_id = _stable_id(item.get("id"), f"teaching_evidence[{index}].id")
        if evidence_id in by_evidence_id:
            raise ContractError(f"teaching_evidence.id 重复：{evidence_id}")
        source_id = _stable_id(item.get("source_id"), f"teaching_evidence[{index}].source_id")
        if source_id not in by_source_id:
            raise ContractError(f"teaching_evidence[{index}] 引用了不存在的 source_id：{source_id}")
        if by_source_id[source_id]["role"] != "teaching_material":
            raise ContractError(f"teaching_evidence[{index}] 必须引用 role=teaching_material 的 source")
        status, relation = item.get("status"), item.get("relation")
        if status not in _EVIDENCE_STATUSES:
            raise ContractError(f"teaching_evidence[{index}].status 必须是 {sorted(_EVIDENCE_STATUSES)} 之一")
        if relation not in _EVIDENCE_RELATIONS:
            raise ContractError(f"teaching_evidence[{index}].relation 必须是 {sorted(_EVIDENCE_RELATIONS)} 之一")
        concept_ids = item.get("concept_ids")
        if not isinstance(concept_ids, list) or not concept_ids:
            raise ContractError(f"teaching_evidence[{index}].concept_ids 必须是非空数组")
        normalized_concept_ids = []
        for concept_id in concept_ids:
            concept_id = _stable_id(concept_id, f"teaching_evidence[{index}].concept_ids")
            if concept_id not in known_concept_ids:
                raise ContractError(f"teaching_evidence[{index}] 引用了不存在的 concept：{concept_id}")
            if concept_id not in normalized_concept_ids:
                normalized_concept_ids.append(concept_id)
                concept_to_evidence[concept_id].add(evidence_id)
        locator = item.get("locator")
        if not isinstance(locator, dict):
            raise ContractError(f"teaching_evidence[{index}].locator 必须是对象")
        page = locator.get("page")
        region = locator.get("region")
        excerpt = locator.get("excerpt")
        is_pdf = source_id in page_counts
        if is_pdf:
            if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= page_counts[source_id]:
                raise ContractError(f"teaching_evidence[{index}].locator.page 超出 PDF 物理页范围")
        elif page is not None:
            raise ContractError(f"teaching_evidence[{index}] 的非 PDF source 不得填写物理页码")
        if region is not None:
            if not is_pdf or not isinstance(region, dict):
                raise ContractError(f"teaching_evidence[{index}].locator.region 只能用于 PDF 且必须是对象")
            keys = ("x", "y", "width", "height")
            if set(region) != set(keys) or any(isinstance(region[k], bool) or not isinstance(region[k], (int, float)) for k in keys):
                raise ContractError(f"teaching_evidence[{index}].locator.region 必须包含归一化 x/y/width/height")
            if not (0 <= region["x"] < 1 and 0 <= region["y"] < 1
                    and 0 < region["width"] <= 1 and 0 < region["height"] <= 1
                    and region["x"] + region["width"] <= 1 and region["y"] + region["height"] <= 1):
                raise ContractError(f"teaching_evidence[{index}].locator.region 必须是 0..1 的有效矩形")
        if not isinstance(excerpt, str) or not excerpt.strip():
            raise ContractError(f"teaching_evidence[{index}].locator.excerpt 必须是供学习者查看的非空节选")
        item["id"], item["source_id"], item["concept_ids"] = evidence_id, source_id, normalized_concept_ids
        by_evidence_id[evidence_id] = item
        evidence.append(item)

    for concept in concepts:
        concept_id = concept["id"]
        declared = concept.get("teaching_evidence_ids", [])
        if not isinstance(declared, list):
            raise ContractError(f"概念 {concept_id}.teaching_evidence_ids 必须是数组")
        if len({_stable_id(value, f"概念 {concept_id}.teaching_evidence_ids") for value in declared}) != len(declared):
            raise ContractError(f"概念 {concept_id}.teaching_evidence_ids 不得重复")
        declared_ids = {_stable_id(value, f"概念 {concept_id}.teaching_evidence_ids") for value in declared}
        unknown = declared_ids - set(by_evidence_id)
        if unknown:
            raise ContractError(f"概念 {concept_id} 引用了不存在的 teaching_evidence：{sorted(unknown)}")
        if declared_ids != concept_to_evidence[concept_id]:
            raise ContractError(f"概念 {concept_id} 与 teaching_evidence 的关联不是双向一致")
        # Flatten only explicit Agent links for a renderer-friendly per-concept
        # projection. It is deliberately derived from IDs rather than from
        # titles, keywords, embeddings or any semantic matching rule.
        concept["teaching_evidence"] = [
            {
                "id": evidence_id,
                "source_id": by_evidence_id[evidence_id]["source_id"],
                "source_file": by_source_id[by_evidence_id[evidence_id]["source_id"]]["path"],
                "status": by_evidence_id[evidence_id]["status"],
                "relation": by_evidence_id[evidence_id]["relation"],
                "page": by_evidence_id[evidence_id]["locator"].get("page"),
                "snippet": by_evidence_id[evidence_id]["locator"]["excerpt"],
                "region": by_evidence_id[evidence_id]["locator"].get("region"),
            }
            for evidence_id in declared
        ]
    return sources, evidence


def _profile(name: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ContractError(f"非法 profile 名称：{name!r}")
    path = ROOT / "profiles" / f"{name}.json"
    if not path.is_file():
        raise ContractError(f"未知 profile：{name}")
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ContractError(f"profile 不是 JSON 对象：{name}")
    return data


def _client(config_path: Path):
    from llm_client import LLMClient

    cfg = _load_json(config_path)
    if not isinstance(cfg, dict):
        raise ContractError("LLM 配置必须是对象")
    if "api_key" in cfg or any(
        isinstance(value, dict) and "api_key" in value
        for value in (cfg.get("stages") or {}).values()
    ):
        raise ContractError("LLM 配置文件禁止包含明文 api_key；请使用 api_key_env")
    env_name = str(cfg.pop("api_key_env", "QPE_LLM_API_KEY"))
    cfg["api_key"] = os.environ.get(env_name, "")
    # Transport retry is bounded separately from stage-level retry. The
    # packaged default is two retries (three HTTP attempts total).
    cfg["_max_retries"] = max(0, min(2, int(cfg.get("max_transport_retries", 2))))
    stage = cfg.get("stages", {}).get("analyzer", {})
    model = stage.get("model") or cfg.get("model")
    api_url = stage.get("api_url") or cfg.get("api_url")
    parsed = urlsplit(str(api_url or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ContractError("LLM 配置的 api_url 必须是无凭据的 http/https URL")
    if not model or not cfg["api_key"]:
        raise ContractError(f"LLM 配置缺少 api_url/model，或环境变量 {env_name} 未设置")
    client = LLMClient(stage="analyzer", config=cfg)
    return client, {
        "provider": cfg.get("provider", "openai-compatible"),
        "api_url_host": parsed.hostname,
        "model": model, "transport_retry_limit": cfg["_max_retries"],
    }


def _concept_skeleton(assignments: list[dict]) -> list[dict]:
    result: dict[str, dict] = {}
    for item in assignments:
        cid = str(item.get("concept_id") or "").strip()
        qid = str(item.get("source_question") or "").strip()
        if not cid or not qid:
            continue
        concept = result.setdefault(cid, {
            "id": cid, "title": item.get("concept_title") or cid,
            "parent": item.get("domain") or "", "chapter": item.get("chapter") or "",
            "source_questions": [], "knowledge_points": [],
        })
        if qid not in concept["source_questions"]:
            concept["source_questions"].append(qid)
            concept["knowledge_points"].append({"id": qid, "statement": concept["title"]})
    return list(result.values())


def _groups(concepts: list[dict], assignments: list[dict], p1: list[dict]) -> list[dict]:
    p1_by_id = {r.get("question_id"): r for r in p1}
    return [{
        "chapter": c.get("chapter") or c["id"], "domain": c.get("parent") or "",
        "concept_id": c["id"], "concept_title": c.get("title") or c["id"],
        "phase1_results": [p1_by_id[q] for q in c.get("source_questions", []) if q in p1_by_id],
    } for c in concepts]


def _questions_export(p1: list[dict], questions: list[dict], assignments: list[dict]) -> list[dict]:
    by_id = {q["id"]: q for q in questions}
    links: dict[str, list[str]] = {}
    for a in assignments:
        if a.get("source_question") and a.get("concept_id"):
            links.setdefault(a["source_question"], []).append(a["concept_id"])
    out = []
    generated_fields = {
        "question_translation", "option_translations", "core_exam_points", "option_analyses",
        "memory_tips", "knowledge_expansion", "cornell_note", "exam_point_summary",
        "is_calculation", "calc_solution", "is_methodology", "method_extract", "quotes",
        "answer_mismatch", "error",
    }
    for row in p1:
        source = dict(by_id[row["question_id"]])
        # Preserve every enriched source field and the canonical answer. Model
        # output is supplementary and must not overwrite source truth.
        generated = {k: row[k] for k in generated_fields if k in row}
        # Keep model output in its own provenance boundary.  Copying these
        # fields into ``source`` made the renderer present one model Cornell
        # note twice: once as a misleading "题库" note and again as model help.
        # Existing source fields with the same names are retained unchanged.
        source["generated_analysis"] = generated
        source["llm_answer"] = row.get("answer", "")
        source["concept_ids"] = list(dict.fromkeys(links.get(source["id"], [])))
        out.append(source)
    return out


def _validate_package(questions: list[dict], concepts: list[dict], *, require_cornell_pairs: bool = False,
                      case_child_ids: set[str] | None = None) -> dict:
    from note_quality import normalize_cornell

    qlist = [q.get("id") for q in questions]
    clist = [c.get("id") if isinstance(c, dict) else None for c in concepts]
    qids, cids = set(qlist) | (case_child_ids or set()), set(clist)
    findings = []
    if len(set(qlist)) != len(qlist):
        findings.append({"code": "QUESTION_ID_DUPLICATE"})
    if len(cids) != len(clist) or None in cids or "" in cids:
        findings.append({"code": "CONCEPT_ID_MISSING_OR_DUPLICATE"})
    for q in questions:
        concept_ids = q.get("concept_ids", [])
        if not isinstance(concept_ids, list) or any(not isinstance(cid, str) or not cid.strip() for cid in concept_ids):
            findings.append({"code": "QUESTION_CONCEPT_LIST_TYPE", "id": q["id"]})
            concept_ids = []
        missing = [cid for cid in concept_ids if cid not in cids]
        if missing:
            findings.append({"code": "QUESTION_CONCEPT_MISSING", "id": q["id"], "targets": missing})
        if not concept_ids:
            findings.append({"code": "QUESTION_UNMAPPED", "id": q["id"]})
    for c in concepts:
        cid = c.get("id", "") if isinstance(c, dict) else ""
        if not isinstance(c, dict):
            findings.append({"code": "CONCEPT_NOT_OBJECT", "id": ""})
            continue
        for field in ("title", "one_liner", "parent", "chapter", "mnemonic", "why_tested"):
            if field in c and c[field] is not None and not isinstance(c[field], str):
                findings.append({"code": "CONCEPT_FIELD_TYPE", "id": cid, "field": field})
        for field in ("tags", "images", "source_questions", "related_questions"):
            if field in c and (
                not isinstance(c[field], list)
                or any(not isinstance(value, str) or not value.strip() for value in c[field])
            ):
                findings.append({"code": "CONCEPT_LIST_TYPE", "id": cid, "field": field})
        if "core_concept" in c and c["core_concept"] is not None and not isinstance(c["core_concept"], dict):
            findings.append({"code": "CONCEPT_FIELD_TYPE", "id": cid, "field": "core_concept"})
        cornell = c.get("cornell_note")
        if cornell is not None and not isinstance(cornell, dict):
            findings.append({"code": "CORNELL_TYPE", "id": cid})
        elif isinstance(cornell, dict):
            if "summary" in cornell and not isinstance(cornell["summary"], str):
                findings.append({"code": "CORNELL_FIELD_TYPE", "id": cid, "field": "summary"})
            declared = cornell.get("pairing_status")
            normalized = normalize_cornell(cornell)
            if declared is not None and declared not in {"paired", "unpaired", "empty"}:
                findings.append({"code": "CORNELL_STATUS_INVALID", "id": cid})
            elif declared is not None and declared != normalized["pairing_status"]:
                findings.append({"code": "CORNELL_STATUS_CONFLICT", "id": cid})
        if require_cornell_pairs:
            pairs = cornell.get("pairs") if isinstance(cornell, dict) else None
            if not isinstance(pairs, list) or not pairs:
                findings.append({"code": "CORNELL_PAIRS_REQUIRED", "id": c.get("id", "")})
            elif any(
                not isinstance(pair, dict)
                or not isinstance(pair.get("cue"), str)
                or not pair["cue"].strip()
                or not isinstance(pair.get("note"), str)
                or not pair["note"].strip()
                for pair in pairs
            ):
                findings.append({"code": "CORNELL_PAIR_INCOMPLETE", "id": c.get("id", "")})
        source_questions = c.get("source_questions", [])
        if not isinstance(source_questions, list):
            source_questions = []
        missing = [qid for qid in source_questions if qid not in qids]
        if missing:
            findings.append({"code": "CONCEPT_QUESTION_MISSING", "id": c["id"], "targets": missing})
        related_value = c.get("related_questions") or source_questions
        related = list(dict.fromkeys(related_value)) if isinstance(related_value, list) else []
        unknown_related = [qid for qid in related if qid not in qids]
        if unknown_related:
            findings.append({"code": "RELATED_QUESTION_MISSING", "id": c["id"], "targets": unknown_related})
        c["related_questions"] = related
        for qid in source_questions:
            q = next((item for item in questions if item["id"] == qid), None)
            if q is not None and c["id"] not in q.get("concept_ids", []):
                findings.append({"code": "LINK_NOT_BIDIRECTIONAL", "id": c["id"], "target": qid})
    return {"status": "passed" if not findings else "review_required", "findings": findings}


def _isolate_generated_references(questions: list[dict], concepts: list[dict],
                                  cases: list[dict] | None = None,
                                  sources: list[dict] | None = None) -> None:
    """Keep model-written citations out of canonical provenance.

    A model string may be useful as a lead for later review, but it is never a
    verified source. Canonical references are derived only from explicit input
    fields on linked questions. Stable question links remain separately visible
    even when the input has no paper/page metadata.
    """
    by_id = {q["id"]: q for q in questions}
    source_paths = {source["id"]: source["path"] for source in (sources or [])}
    for case in cases or []:
        for child in case["sub_questions"]:
            by_id[child["id"]] = {
                "id": child["id"], "source_file": source_paths.get(case["source_id"], ""),
                "source_pages": child["source_pages"],
            }
    for concept in concepts:
        generated = concept.pop("references", None)
        if generated:
            values = generated if isinstance(generated, list) else [generated]
            concept["unverified_generated_references"] = [
                {"text": str(value), "verification_status": "unverified_model_output"}
                for value in values if str(value).strip()
            ]
        origins = []
        canonical = []
        for qid in concept.get("source_questions", []) or []:
            question = by_id.get(qid)
            if question is None:
                continue
            origins.append({"question_id": qid})
            paper = str(question.get("source_paper") or "").strip()
            source_file = str(question.get("source_file") or "").strip()
            page = question.get("source_page", question.get("page_no"))
            pages = question.get("source_pages") if isinstance(question.get("source_pages"), list) else [page]
            source_url = str(question.get("source_url") or "").strip()
            if paper or source_file or source_url:
                item = {"question_id": qid, "verification_status": "input_provided"}
                if paper:
                    item["source_paper"] = paper
                if source_file:
                    item["source_file"] = source_file
                if len(pages) == 1 and isinstance(pages[0], int) and pages[0] > 0:
                    item["source_page"] = pages[0]
                elif pages and all(isinstance(p, int) and p > 0 for p in pages):
                    item["source_pages"] = pages
                if source_url:
                    item["source_url"] = source_url
                canonical.append(item)
        concept["question_origins"] = origins
        concept["canonical_references"] = canonical


def _summarize_usage(events: list[dict]) -> dict:
    """Summarize lifecycle events without counting sent+succeeded twice."""
    attempts = {(event.get("call_id"), event.get("attempt")) for event in events
                if event.get("call_id") and event.get("attempt") is not None}
    succeeded = {(event.get("call_id"), event.get("attempt")) for event in events
                 if event.get("status") == "succeeded"}
    failed = {(event.get("call_id"), event.get("attempt")) for event in events
              if event.get("status") in ("failed", "blocked")}
    succeeded_events = [event for event in events if event.get("status") == "succeeded"]
    return {
        "scope": "current_process_only",
        "event_count": len(events),
        "attempt_count": len(attempts),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "provider_usage_complete": bool(succeeded_events) and all(
            event.get("usage_source") == "provider" for event in succeeded_events),
        "cached_work_usage": "unknown",
    }


def _supplied_content(payload: dict, questions: list[dict], *, agent_content: bool,
                      input_dir: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Normalize an already structured question/concept graph without inference."""
    schema = payload.get("schema_version")
    if agent_content and schema != AGENT_CONTENT_SCHEMA:
        raise ContractError(f"Agent 内容输入 schema_version 必须是 {AGENT_CONTENT_SCHEMA!r}")
    raw_concepts = payload.get("concepts")
    if not isinstance(raw_concepts, list) or (not raw_concepts and not (agent_content and payload.get("cases"))):
        label = "--agent-content" if agent_content else "--fixture"
        raise ContractError(f"{label} 需要输入同时包含非空 concepts 数组")
    if any(not isinstance(concept, dict) for concept in raw_concepts):
        raise ContractError("concepts 的每一项必须是对象")
    final_questions = copy.deepcopy(questions)
    concepts = copy.deepcopy(raw_concepts)
    if agent_content:
        sources, evidence = _validate_agent_content(payload, final_questions, concepts, input_dir)
    else:
        known_qids = {q["id"] for q in final_questions}
        for concept in concepts:
            if not concept.get("source_questions"):
                related = concept.get("related_questions") or []
                if not isinstance(related, list):
                    raise ContractError("concept.related_questions 必须是数组")
                concept["source_questions"] = [qid for qid in related if qid in known_qids]
        for question in final_questions:
            if not question.get("concept_ids"):
                question["concept_ids"] = [
                    concept.get("id") for concept in concepts
                    if question["id"] in (concept.get("source_questions") or [])
                ]
        sources, evidence = [], []
    return final_questions, concepts, sources, evidence


def generate_package(input_path: Path, output_dir: Path, *, profile_name: str,
                     llm_config: Path | None = None, fixture: bool = False,
                     agent_content: bool = False, source_root: Path | None = None,
                     source_inventory: Path | None = None,
                     source_scopes: list[str] | None = None) -> Path:
    """Generate into a fresh directory from agent content, fixture, or an LLM."""
    input_path, output_dir = input_path.resolve(), output_dir.resolve()
    if output_dir.exists():
        raise ContractError(f"输出目录已存在，拒绝覆盖：{output_dir}")
    payload = _load_json(input_path)
    questions = validate_questions(payload)
    profile = _profile(profile_name)
    if profile.get("agent_only") and not agent_content:
        raise ContractError("此 profile 仅支持 --agent-content，请由 Agent 按原资料完成内容编写")
    if fixture and agent_content:
        raise ContractError("--fixture 与 --agent-content 不能同时使用")
    if agent_content and llm_config is not None:
        raise ContractError("--agent-content 不接受 --llm-config；该路径不调用外部 LLM")
    if (source_root is None) != (source_inventory is None):
        raise ContractError("原始资料覆盖检查必须同时提供 --source-root 和 --source-inventory")
    if source_scopes and source_root is None:
        raise ContractError("--source-scope 必须配合 --source-root")
    if source_root is not None and not agent_content:
        raise ContractError("原始资料覆盖检查仅用于 --agent-content")
    if fixture or agent_content:
        final_questions, concepts, sources, teaching_evidence = _supplied_content(
            payload, questions, agent_content=agent_content, input_dir=input_path.parent
        )
        mode, model_info = ("agent" if agent_content else "fixture"), None
    else:
        if llm_config is None:
            raise ContractError("真实生成必须提供 --llm-config")
        llm, model_info = _client(llm_config)
        from exam_point_extractor import ExamPointExtractor
        from phase2_classifier import run_phase2
        from concept_relation_builder import ConceptRelationBuilder
        from phase4_content_generator import ContentGenerator
        recipe_digest = hashlib.sha256()
        for module in [Path(__file__), *sorted(VENDOR.glob("*.py"))]:
            recipe_digest.update(module.name.encode())
            recipe_digest.update(module.read_bytes())
        recipe_sha256 = recipe_digest.hexdigest()
        cache_key = hashlib.sha256((input_path.read_bytes() + json.dumps(profile, sort_keys=True).encode()
                                    + llm_config.read_bytes() + recipe_sha256.encode())).hexdigest()
        cache = output_dir.parent / ".qpe-cache" / cache_key
        p1 = [r.to_dict() for r in ExamPointExtractor(
            llm, str(cache / "phase1"), profile.get("exam_full_name") or profile.get("exam_name", ""),
            profile.get("standard_label", "")).extract_batch(questions)]
        domains = "\n".join(f"- {x}" for x in profile.get("domain_examples", []))
        assignments = run_phase2(p1, llm, profile.get("exam_full_name") or profile.get("exam_name", ""),
                                 domains, str(cache / "phase2.json"))
        concepts = ConceptRelationBuilder(llm, profile.get("exam_full_name") or profile.get("exam_name", "")).build(
            _concept_skeleton(assignments))
        gen = ContentGenerator(llm, str(cache / "phase4"), profile.get("domain_examples", []),
                               profile.get("exam_full_name") or profile.get("exam_name", ""),
                               profile.get("standard_label", ""), profile.get("content_style", {}).get("code_format", "text"))
        concepts = gen.merge_into_concepts(concepts, gen.generate_batch(_groups(concepts, assignments, p1)))
        final_questions = _questions_export(p1, questions, assignments)
        sources, teaching_evidence = [], []
        mode = "llm"
    source_coverage = {"status": "not_checked", "reason": "未提供原始资料目录与逐文件清单"}
    if source_root is not None:
        from source_coverage import SourceCoverageError, audit_sources
        try:
            source_coverage = audit_sources(source_root, source_inventory, sources,
                                            teaching_evidence, source_scopes)
        except SourceCoverageError as exc:
            failure_report = output_dir.with_name(output_dir.name + ".source-coverage.json")
            failure_report.parent.mkdir(parents=True, exist_ok=True)
            failure_report.write_text(json.dumps(exc.report, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
            raise ContractError(f"{exc}；报告：{failure_report}") from exc
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
    cases, methods = [], []
    case_quality = {"status": "passed", "validation": "deterministic_structural_only",
                    "semantic_verification": "not_performed", "case_count": 0,
                    "sub_question_count": 0, "method_count": 0, "findings": []}
    if agent_content:
        from case_contract import CaseContractError, validate_cases_methods
        try:
            cases, methods, case_quality = validate_cases_methods(
                payload.get("cases", []), payload.get("methods", []),
                sources=sources, concepts=concepts, evidence=teaching_evidence,
                question_ids={q["id"] for q in final_questions})
        except CaseContractError as exc:
            raise ContractError(str(exc)) from exc
    method_coverage = {"status": "not_checked"}
    if agent_content:
        from method_coverage import audit_method_coverage
        method_coverage = audit_method_coverage(final_questions, cases, methods,
                                                payload.get("method_coverage"), required=True)
        if method_coverage["status"] != "passed":
            failed = output_dir.with_name(output_dir.name + ".method-coverage.json")
            failed.parent.mkdir(parents=True, exist_ok=True)
            failed.write_text(json.dumps(method_coverage, ensure_ascii=False, indent=2), encoding="utf-8")
            raise ContractError(f"计算方法覆盖检查未通过；按报告逐题补齐后重新生成：{failed}")
    _isolate_generated_references(final_questions, concepts, cases, sources)
    report = _validate_package(
        final_questions, concepts, require_cornell_pairs=(mode in {"llm", "agent"}),
        case_child_ids={s["id"] for c in cases for s in c["sub_questions"]}
    )
    if mode == "agent":
        report["agent_content"] = {
            "schema_version": payload.get("schema_version"),
            "source_count": len(sources),
            "teaching_evidence_count": len(teaching_evidence),
            "validation": "local_structural_only",
        }
    failure_report = output_dir.with_name(output_dir.name + ".failed-quality.json")
    if report["status"] != "passed":
        failure_report.parent.mkdir(parents=True, exist_ok=True)
        failure_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise ContractError(f"学习包质量门未通过；报告：{failure_report}")
    from generation_quality_gate import evaluate_generation, evaluate_card_content
    origin_ids = [q["id"] for q in questions] + [s["id"] for c in cases for s in c["sub_questions"]]
    origin = evaluate_generation(concepts, origin_ids, generation_id="standalone") if concepts else {"status": "passed", "validation": "empty_concepts_case_only"}
    if origin["status"] != "passed":
        failure_report.parent.mkdir(parents=True, exist_ok=True)
        failure_report.write_text(json.dumps(origin, ensure_ascii=False, indent=2), encoding="utf-8")
        raise ContractError(f"生成来源质量门未通过；报告：{failure_report}")

    # Deterministic checks catch known defects. Agent review remains an explicit
    # declaration, never proof that a program verified the meaning of a source.
    content = evaluate_card_content(concepts, final_questions, teaching_evidence) if concepts else {
        "status": "review_required", "metrics": {}, "learning_support_coverage": {}, "concepts": []}
    if mode == "fixture":
        content = {**content, "status": "fixture", "validation": "demo_only"}
    quality_summary = {
        "structural_status": "passed",
        "source_coverage_status": source_coverage["status"],
        "method_coverage_status": method_coverage["status"],
        "content_status": content["status"],
        "case_status": case_quality["status"],
        "case_quality": case_quality,
        "semantic_verification": "not_performed",
        "browser_status": "not_checked",
        "metrics": content["metrics"],
        "learning_support_coverage": content["learning_support_coverage"],
        "concepts": content["concepts"],
    }
    quality_report = {"origin": origin, "package": report, "content": content,
                      "cases": case_quality, "browser": {"status": "not_checked"},
                      "source_coverage": source_coverage, "method_coverage": method_coverage}
    if content["status"] == "blocked":
        failure_report.parent.mkdir(parents=True, exist_ok=True)
        failure_report.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise ContractError(f"知识卡片内容质量门未通过；请修订报告中的卡片：{failure_report}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        data_dir, reports = temp / "data", temp / "reports"
        data_dir.mkdir(); reports.mkdir()
        data_items = [("questions.json", final_questions), ("concepts.json", concepts),
                      ("cases.json", cases), ("methods.json", methods)]
        if mode == "agent":
            data_items.append(("method-coverage.json", payload["method_coverage"]))
            data_items.extend((("sources.json", sources),
                               ("teaching-evidence.json", teaching_evidence)))
        for name, value in data_items:
            (data_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        (reports / "quality-report.json").write_text(json.dumps(
            quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
        (reports / "method-coverage.json").write_text(json.dumps(method_coverage, ensure_ascii=False, indent=2), encoding="utf-8")
        (reports / "source-coverage.json").write_text(json.dumps(
            source_coverage, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            from renderer import render_package
            # The renderer receives the validated explicit source/evidence
            # graph; this generator never fabricates display links or claims.
            render_package(
                final_questions, concepts, temp / "web", input_dir=input_path.parent,
                profile=profile, sources=sources, teaching_evidence=teaching_evidence,
                quality_summary=quality_summary, cases=cases, methods=methods,
            )
        except ImportError as exc:
            raise ContractError("renderer.py 尚不可用") from exc
        if mode == "agent":
            from package_audit import audit_package
            if source_inventory is not None:
                (data_dir / "source-inventory.json").write_bytes(source_inventory.read_bytes())
            postflight = audit_package(temp, expected={
                "questions": final_questions, "concepts": concepts, "sources": sources,
                "teaching_evidence": teaching_evidence, "cases": cases, "methods": methods,
                "method_coverage": payload["method_coverage"],
            }, baseline=source_coverage)
            if postflight["status"] == "blocked":
                failed = output_dir.with_name(output_dir.name + ".post-generation-check.json")
                failed.write_text(json.dumps(postflight, ensure_ascii=False, indent=2), encoding="utf-8")
                raise ContractError(f"生成后核对未通过；不得交付，请按修复指令补齐后重新生成：{failed}")
            quality_summary["post_generation_status"] = postflight["status"]
            quality_report["post_generation"] = postflight
            (reports / "post-generation-check.json").write_text(
                json.dumps(postflight, ensure_ascii=False, indent=2), encoding="utf-8")
            (reports / "quality-report.json").write_text(
                json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
        usage_attempts = list(llm.usage_attempts) if mode == "llm" else []
        usage_summary = _summarize_usage(usage_attempts)
        (reports / "usage-attempts.json").write_text(json.dumps(
            {"summary": usage_summary, "attempts": usage_attempts}, ensure_ascii=False, indent=2), encoding="utf-8")
        output_hashes = {}
        for path in sorted(p for p in temp.rglob("*") if p.is_file()):
            output_hashes[str(path.relative_to(temp))] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": "quick-pass-package-v1", "mode": mode, "profile": profile_name,
            "content_input_schema": payload.get("schema_version") if mode == "agent" else None,
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(llm_config.read_bytes()).hexdigest() if llm_config else None,
            "config_version": "standalone-llm-config-v1" if llm_config else None,
            "generated_at": datetime.now(timezone.utc).isoformat(), "question_count": len(final_questions),
            "concept_count": len(concepts), "case_count": len(cases),
            "sub_question_count": case_quality["sub_question_count"],
            "method_count": len(methods), "case_quality_status": case_quality["status"],
            "quality_status": ("review_required" if case_quality["status"] == "review_required"
                               else content["status"]),
            **quality_summary,
            # The current compatible client exposes the requested model only;
            # response_model remains explicit null instead of being guessed.
            "model": ({**model_info, "requested_model": model_info["model"], "response_model": None}
                      if model_info else None),
            "usage": usage_summary,
            "cache": ({"key": cache_key, "recipe_sha256": recipe_sha256, "usage_attribution": "unknown_when_cache_hit"}
                      if mode == "llm" else None),
            "files": output_hashes,
        }
        (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(output_dir)
    except Exception:
        import shutil
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return output_dir
