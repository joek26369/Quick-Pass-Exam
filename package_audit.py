"""Post-render source delivery checks. No semantic inference or file mutation."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from source_coverage import SourceCoverageError, audit_sources


REPAIR_INSTRUCTIONS = [
    "保持用户指定的原始目录与扫描范围，逐项处理 findings；不得改用筛选后的暂存目录掩盖漏项。",
    "漏读文件：回到原件完成读取/视觉或 OCR 核对，补写清单、sources 和可靠的 teaching_evidence。",
    "漏关联或漏渲染：修复 agent-content 或渲染器；原件/页图缺失或哈希不符：重新复制和渲染。",
    "不能可靠关联时明确说明原因；不得添加无关 supports、只改报告状态或删除检查项来过关。",
    "保留既有题目、案例、考点及证据 ID 和学习记录；在新目录重新生成并重跑前后两次核对。",
    "抽查新增教辅的节选、原页、原文件跳转以及错题/草稿；通过后才替换现有学习包。",
    "向用户补报逐文件处置、新增关联、未解决内容和实际验收证据；有未解决项不得称全部完成。",
]


def audit_package(package: Path, *, expected: dict[str, list] | None = None,
                  baseline: dict | None = None, inventory_path: Path | None = None,
                  verify_manifest: bool = False) -> dict[str, Any]:
    """Compare serialized data, actual HTML payload and copied source assets.

    During generation ``expected`` is the validated in-memory contract. For an
    existing package the manifest supplies the independent output hash baseline.
    A missing original-file baseline is reported explicitly as not_checked.
    """
    package = package.resolve()
    findings: list[dict] = []

    def fail(code: str, target: str, message: str) -> None:
        findings.append({"code": code, "target": target, "message": message})

    def read(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def asset(value: Any, *, web: bool = True) -> Path:
        if not isinstance(value, str) or not value or "#" in value or "?" in value:
            raise ValueError("资源路径无效")
        relative = Path(value)
        base = package / "web" if web else package
        path = base / relative
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink():
            raise ValueError("资源路径越界或为符号链接")
        if not path.resolve().is_relative_to(base) or not path.is_file() or not path.stat().st_size:
            raise ValueError("资源不存在、为空或越界")
        return path

    delivered: list[dict] = []
    original_status = "not_checked"
    scope_status = "not_checked"
    method_report = {"status": "limited"}
    try:
        data = {name: read(package / "data" / (filename + ".json")) for name, filename in (
            ("sources", "sources"), ("teaching_evidence", "teaching-evidence"),
            ("concepts", "concepts"), ("questions", "questions"),
            ("cases", "cases"), ("methods", "methods"))}
        from method_coverage import audit_method_coverage
        method_path = package / "data/method-coverage.json"
        data["method_coverage"] = read(method_path) if method_path.is_file() else None
        method_report = audit_method_coverage(data["questions"], data["cases"], data["methods"], data["method_coverage"])
        if method_report["status"] == "blocked":
            findings.extend(method_report["findings"])
        if expected is not None:
            for key, rows in expected.items():
                if data.get(key) != rows:
                    fail("SERIALIZED_DATA_MISMATCH", key, "落盘数据与校验通过的输入不一致")
        baseline = baseline or read(package / "reports/source-coverage.json")
        if baseline.get("input_scope"):
            scope_status = "declared"
        if baseline.get("status") == "passed":
            inv = inventory_path or package / "data/source-inventory.json"
            if baseline.get("inventory_sha256") and inv.is_file():
                try:
                    scopes = baseline.get("scopes", ["."])
                    current = audit_sources(Path(baseline["root"]), inv, data["sources"],
                                            data["teaching_evidence"], None if scopes == ["."] else scopes)
                    for key in ("root", "scopes", "inventory_sha256", "scanned_extensions", "files"):
                        if current.get(key) != baseline.get(key):
                            fail("ORIGINAL_INPUT_CHANGED", key, "原始目录、文件或清单相对生成前基线发生变化")
                    original_status = "passed"
                except SourceCoverageError as exc:
                    original_status = "blocked"
                    for error in exc.report["errors"]:
                        fail("ORIGINAL_COVERAGE_FAILED", "source-inventory", error)
                except (OSError, ValueError) as exc:
                    original_status = "blocked"
                    fail("ORIGINAL_RECHECK_FAILED", "source-inventory", str(exc))
            # Legacy packages have no frozen inventory/hash baseline. Do not
            # turn their former preflight-only pass into a postflight pass.
        html = (package / "web/index.html").read_text(encoding="utf-8")
        marker = "const DATA="
        start = html.index(marker) + len(marker)
        web, _ = json.JSONDecoder().raw_decode(html[start:])
        for key in ("questions", "concepts", "cases", "methods"):
            if Counter(x["id"] for x in web[key]) != Counter(x["id"] for x in data[key]):
                fail("WEB_IDS_MISMATCH", key, "页面数据遗漏或重复了记录")
        if Counter(s["id"] for c in web["cases"] for s in c.get("sub_questions", [])) != Counter(
                s["id"] for c in data["cases"] for s in c.get("sub_questions", [])):
            fail("WEB_IDS_MISMATCH", "case_sub_questions", "页面案例小问遗漏或重复")

        # Rendered method text and navigation must match the audited contract.
        web_methods = {m["id"]: m for m in web["methods"]}
        for method in data["methods"]:
            shown = web_methods.get(method["id"], {})
            for key in ("title", "type", "calculation_type", "applicability", "formula", "substitution",
                        "units", "steps", "pitfalls", "assumptions", "input_requirements",
                        "question_ids", "sub_question_ids", "concept_ids", "evidence_ids"):
                if shown.get(key) != method.get(key):
                    fail("WEB_METHOD_MISMATCH", method["id"], f"页面方法 {key} 与审核内容不一致")

        sources = {s["id"]: s for s in data["sources"] if s["role"] == "teaching_material"}
        if Counter(s["id"] for s in web["sources"]) != Counter(sources.keys()):
            fail("WEB_SOURCES_MISMATCH", "sources", "页面教辅来源遗漏或重复")
        for row in web["sources"]:
            sid = row["id"]
            if sid not in sources:
                continue
            try:
                path = asset(row.get("source_file"))
                actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual_hash != sources[sid].get("sha256"):
                    fail("COPIED_SOURCE_MISMATCH", sid, "包内原文件与已校验来源哈希不一致")
                delivered.append({"source_id": sid, "asset": row["source_file"], "sha256": actual_hash})
            except ValueError as exc:
                fail("SOURCE_ASSET_MISSING", sid, str(exc))

        expected_edges = Counter((e["id"], e["source_id"], cid)
                                 for e in data["teaching_evidence"] for cid in e["concept_ids"])
        actual_edges = Counter((e["id"], e["source_id"], e["concept_id"])
                               for e in web["teaching_evidence"])
        if actual_edges != expected_edges:
            fail("WEB_EVIDENCE_MISMATCH", "teaching_evidence", "页面证据与考点关联有遗漏、多余或重复")
        canonical = {e["id"]: e for e in data["teaching_evidence"]}
        web_sources = {s["id"]: s for s in web["sources"]}
        for row in web["teaching_evidence"]:
            eid = row["id"]
            raw = canonical.get(eid)
            if raw is None:
                continue
            loc = raw["locator"]
            for key, value in (("snippet", loc["excerpt"].strip()), ("page", loc.get("page")),
                               ("relation", raw["relation"]), ("status", raw["status"])):
                if row.get(key) != value:
                    fail("WEB_EVIDENCE_CONTENT_MISMATCH", eid, f"页面证据 {key} 与来源记录不一致")
            source_file = web_sources.get(row["source_id"], {}).get("source_file")
            expected_link = str(source_file) + (f"#page={loc['page']}" if loc.get("page") else "")
            if row.get("source_link") != expected_link or row.get("source_file") != source_file:
                fail("SOURCE_LINK_MISMATCH", eid, "页面原文件链接或页码不一致")
            if loc.get("page") or loc.get("page_image"):
                try:
                    asset(row.get("thumbnail"))
                except ValueError as exc:
                    fail("PAGE_ASSET_MISSING", eid, str(exc))
        for concept in data["concepts"]:
            ids = {e["id"] for e in data["teaching_evidence"] if concept["id"] in e["concept_ids"]}
            if set(concept.get("teaching_evidence_ids", [])) != ids:
                fail("CONCEPT_EVIDENCE_MISMATCH", concept["id"], "考点与证据双向关联不一致")
        if verify_manifest:
            manifest = read(package / "manifest.json")
            for name, digest in manifest["files"].items():
                try:
                    if hashlib.sha256(asset(name, web=False).read_bytes()).hexdigest() != digest:
                        fail("MANIFEST_HASH_MISMATCH", name, "文件与生成时 manifest 哈希不一致")
                except ValueError as exc:
                    fail("MANIFEST_FILE_MISSING", name, str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        fail("PACKAGE_UNREADABLE", str(package), str(exc))
    if any(f["code"] == "ORIGINAL_INPUT_CHANGED" for f in findings):
        original_status = "blocked"
    complete = original_status == "passed" and scope_status == "declared" and method_report["status"] == "passed"
    return {"status": "blocked" if findings else "passed" if complete else "limited",
            "delivery_status": "blocked" if findings else "passed",
            "original_coverage_status": original_status,
            "method_coverage": method_report,
            "input_scope_status": scope_status,
            "semantic_verification": "not_performed", "browser_status": "not_checked",
            "delivered_sources": delivered, "findings": findings,
            "repair_instructions": (REPAIR_INSTRUCTIONS if findings else []) + method_report.get("repair_instructions", []),
            "limitations": [] if complete else [
                "缺少完整原始资料基线或逐题方法覆盖审查；查看各分项状态，不得宣称全部资料与方法均已覆盖。"]}
