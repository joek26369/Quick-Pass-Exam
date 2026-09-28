"""Check the Agent's source decisions against the files the user supplied."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SUPPORTED = {".pdf", ".doc", ".docx", ".txt", ".md", ".xls", ".xlsx"}


class SourceCoverageError(ValueError):
    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


def _relative(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空相对路径")
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError(f"{field} 不得使用绝对路径或越界路径")
    return path


def audit_sources(root: Path, inventory_path: Path, sources: list[dict],
                  evidence: list[dict], scopes: list[str] | None = None) -> dict[str, Any]:
    """Require a decision for every source file in the selected original folders.

    The inventory is an Agent declaration, not a semantic relevance check.
    Included files must match an actual packaged source by SHA-256.
    """
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"原始资料目录不存在：{root}")
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取原始资料清单：{inventory_path}") from exc
    if not isinstance(inventory, dict) or not isinstance(inventory.get("files"), list):
        raise ValueError("原始资料清单必须包含 files 数组")

    folders = []
    for raw in scopes or []:
        rel = _relative(raw, "source-scope")
        folder = root / rel
        if folder.is_symlink() or not folder.is_dir() or not folder.resolve().is_relative_to(root):
            raise ValueError(f"source-scope 不是原始资料目录内的普通文件夹：{raw}")
        folders.append(folder)
    if not folders:
        folders = [root]

    discovered: dict[str, Path] = {}
    for folder in folders:
        for path in folder.rglob("*"):
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts) or path.suffix.lower() not in SUPPORTED:
                continue
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            discovered[relative.as_posix()] = path

    declared: dict[str, dict] = {}
    errors = []
    requested_scope = inventory.get("input_scope")
    if requested_scope is not None:
        if (not isinstance(requested_scope, dict)
                or requested_scope.get("root") != str(root)
                or requested_scope.get("scopes") != (scopes or ["."])):
            errors.append("命令行扫描范围与清单中锁定的用户 input_scope 不一致；不得缩小输入范围")
    for item in inventory["files"]:
        if not isinstance(item, dict):
            errors.append("files 条目必须是对象")
            continue
        try:
            name = _relative(item.get("path"), "files.path").as_posix()
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if name in declared:
            errors.append(f"重复登记：{name}")
        declared[name] = item

    source_by_id = {s["id"]: s for s in sources}
    evidence_count: dict[str, int] = {}
    for row in evidence:
        sid = row.get("source_id")
        evidence_count[sid] = evidence_count.get(sid, 0) + 1
    rows = []
    for name, path in sorted(discovered.items()):
        item = declared.get(name)
        row = {"path": name, "status": "undeclared", "source_id": None,
               "evidence_count": 0, "reason": None,
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if item is None:
            errors.append(f"未登记原始文件：{name}")
        elif item.get("decision") == "excluded":
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"排除文件缺少原因：{name}")
            row.update(status="excluded", reason=reason)
        elif item.get("decision") == "included":
            sid = item.get("source_id")
            source = source_by_id.get(sid)
            row.update(status="included", source_id=sid,
                       evidence_count=evidence_count.get(sid, 0))
            if source is None:
                errors.append(f"入包文件未关联有效 source_id：{name}")
            elif row["sha256"] != source.get("sha256"):
                errors.append(f"原始文件与入包 source 哈希不一致：{name}")
            elif source.get("role") == "teaching_material" and not evidence_count.get(sid):
                reason = item.get("no_evidence_reason")
                row["reason"] = reason
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(f"教辅已入包但没有关联证据，须说明原因：{name}")
        else:
            errors.append(f"文件必须声明 included 或 excluded：{name}")
        rows.append(row)
    for name in sorted(declared.keys() - discovered.keys()):
        errors.append(f"清单文件不在扫描范围或不存在：{name}")
    report = {"status": "passed" if not errors else "blocked", "root": str(root),
              "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
              "input_scope": requested_scope,
              "scanned_extensions": sorted(SUPPORTED),
              "scopes": scopes or ["."], "discovered_count": len(discovered),
              "included_count": sum(r["status"] == "included" for r in rows),
              "excluded_count": sum(r["status"] == "excluded" for r in rows),
              "files": rows, "errors": errors,
              "repair_instructions": [
                  "保持用户指定的 source-root/source-scope；不得缩小范围或删除漏项来通过检查。",
                  "逐项读取漏报原件，补充来源、教辅页码与考点关联；扫描件用视觉或 OCR 后核对。",
                  "确需排除时写具体理由；无法读取时报告未解决，不得把相关内容伪装为 supports。",
                  "修订清单和 agent-content 后重新生成，再通过生成后核对与浏览器验收。",
              ] if errors else []}
    if errors:
        raise SourceCoverageError(f"原始资料覆盖检查未通过：{len(errors)} 项；首项：{errors[0]}", report)
    return report
