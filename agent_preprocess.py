"""Local document handoff for an Agent when no structuring LLM is configured.

This module never calls an OCR or LLM provider.  It renders physical PDF pages
and writes an explicit, user/Agent-fillable question contract.  Resuming checks
the original file hash and physical page range before importing any answers.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from generator import ContractError, validate_questions


CONTRACT_VERSION = 1
CONTRACT_NAME = "agent-question-contract.json"
PAGES_NAME = "pages.json"
PAGES_DIR = "pages"
TEXT_BLOCKS_NAME = "text-blocks.json"


def source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_output_root(path: Path) -> Path:
    """Canonicalize the parent path while rejecting a symlink output root.

    macOS exposes ``/tmp`` as a system symlink to ``/private/tmp``. Resolving
    parents first keeps that normal path usable; the requested handoff root
    itself may not be a symlink, and every managed child is checked again.
    """
    candidate = path if path.is_absolute() else Path.cwd() / path
    candidate = Path(os.path.normpath(str(candidate)))
    if candidate.is_symlink():
        raise ContractError(f"交接输出路径不得是符号链接：{candidate}")
    candidate = candidate.resolve(strict=False)
    if candidate.exists() and not candidate.is_dir():
        raise ContractError("交接输出路径必须是目录")
    return candidate


def _check_managed_path(path: Path, root: Path) -> None:
    root = checked_output_root(root)
    candidate = path if path.is_absolute() else root / path
    candidate = Path(os.path.normpath(str(candidate)))
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError("受管输出路径越出交接目录") from exc
    current = candidate
    while True:
        if current.is_symlink():
            raise ContractError(f"受管输出路径不得是符号链接：{current.name}")
        if current == root:
            break
        current = current.parent


def prepare_agent_handoff(pdf_path: Path, output_dir: Path, *, dpi: int = 150) -> Path:
    """Render all physical pages and create/reuse a blank Agent contract.

    Existing output is reused only when it belongs to exactly the same source
    bytes. Existing page images and non-empty agent questions are never
    overwritten, allowing a human/Agent to continue an interrupted handoff.
    """
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PDF 预处理需要 PyMuPDF；请安装 requirements-import.txt") from exc

    pdf_path = pdf_path.resolve()
    output_dir = checked_output_root(output_dir)
    digest = source_sha256(pdf_path)
    contract_path = output_dir / CONTRACT_NAME
    pages_path = output_dir / PAGES_NAME
    _verify_existing_contract(contract_path, pdf_path.name, digest)

    output_dir.mkdir(parents=True, exist_ok=True)
    page_dir = output_dir / PAGES_DIR
    _check_managed_path(page_dir, output_dir)
    page_dir.mkdir(exist_ok=True)
    document = pymupdf.open(str(pdf_path))
    try:
        pages: list[dict[str, Any]] = []
        for index, page in enumerate(document):
            physical_page = index + 1
            filename = f"page-{physical_page:04d}.png"
            target = page_dir / filename
            _check_managed_path(target, output_dir)
            if not target.exists():
                _atomic_write_bytes(target, page.get_pixmap(dpi=dpi, alpha=False).tobytes("png"),
                                    root=output_dir, exclusive=True)
            elif not target.is_file():
                raise ContractError(f"页图目标不是普通文件：{filename}")
            native_text = page.get_text() or ""
            pages.append({
                "physical_page": physical_page,
                "image": f"{PAGES_DIR}/{filename}",
                # Informational only. It does not classify a page as scanned
                # or OCR-ready, and no OCR decision is made by this module.
                "native_text": native_text,
                "native_text_characters": len(native_text.strip()),
            })
    finally:
        document.close()

    pages_payload = {
        "format_version": CONTRACT_VERSION,
        "source_name": pdf_path.name,
        "source_sha256": digest,
        "pages": pages,
    }
    _write_json(pages_path, pages_payload)
    if not contract_path.exists():
        _write_json(contract_path, {
            "format_version": CONTRACT_VERSION,
            "status": "needs_agent_transcription",
            "source_kind": "pdf",
            "source_name": pdf_path.name,
            "source_sha256": digest,
            "page_manifest": PAGES_NAME,
            "questions": [],
            "instructions": [
                "根据 pages.json 和 pages/ 中的图片回填写 questions；不要臆造题目、答案、解析或页码。",
                "每题必须有稳定 id、题干、选项、至少一个 is_correct=true 的选项、source_page。",
                "source_page 必须是 pages.json 中的 physical_page（从 1 开始）。",
                "回填后使用 --resume-agent-contract 继续导入；该命令会校验源文件哈希和页码范围。",
            ],
        }, exclusive=True)
    return contract_path


def prepare_text_agent_handoff(source_path: Path, output_dir: Path, *, text: str,
                               blocks: list[dict[str, Any]]) -> Path:
    """Write deterministic text blocks and a no-page Agent contract.

    Text block segmentation is only an aid to review. It neither turns blocks
    into questions nor assigns pages, so the Agent must not add source_page.
    """
    source_path = source_path.resolve()
    output_dir = checked_output_root(output_dir)
    digest = source_sha256(source_path)
    contract_path = output_dir / CONTRACT_NAME
    _verify_existing_contract(contract_path, source_path.name, digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / TEXT_BLOCKS_NAME, {
        "format_version": CONTRACT_VERSION,
        "source_name": source_path.name,
        "source_sha256": digest,
        "text": text,
        "blocks": blocks,
    })
    if not contract_path.exists():
        _write_json(contract_path, {
            "format_version": CONTRACT_VERSION,
            "status": "needs_agent_transcription",
            "source_kind": "text",
            "source_name": source_path.name,
            "source_sha256": digest,
            "text_blocks": TEXT_BLOCKS_NAME,
            "questions": [],
            "instructions": [
                "根据 text-blocks.json 回填写 questions；不要臆造题目、答案或解析。",
                "每题必须有稳定 id、题干、选项和至少一个 is_correct=true 的选项。",
                "TXT/MD 没有可核验的物理页；不要填写 source_page 或 page_no。",
                "回填后使用 --resume-agent-contract 继续导入；该命令会校验源文件哈希。",
            ],
        }, exclusive=True)
    return contract_path


def prepare_docx_agent_handoff(source_path: Path, output_dir: Path, *, content: dict[str, Any]) -> Path:
    """Persist loss-aware DOCX content and create a no-page Agent contract."""
    source_path = source_path.resolve()
    output_dir = checked_output_root(output_dir)
    digest = source_sha256(source_path)
    contract_path = output_dir / CONTRACT_NAME
    _verify_existing_contract(contract_path, source_path.name, digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    content_name = "document-content.json"
    _write_json(output_dir / content_name, {
        "format_version": CONTRACT_VERSION,
        "source_name": source_path.name,
        "source_sha256": digest,
        **content,
    })
    if not contract_path.exists():
        _write_json(contract_path, {
            "format_version": CONTRACT_VERSION,
            "status": "needs_agent_transcription",
            "source_kind": "docx",
            "source_name": source_path.name,
            "source_sha256": digest,
            "document_content": content_name,
            "questions": [],
            "instructions": [
                "根据 document-content.json 的段落、表格和嵌入图片引用回填写 questions；不要臆造图中文字、题目、答案或解析。",
                "每题必须有稳定 id、题干、选项和至少一个 is_correct=true 的选项。",
                "DOCX 没有可核验的物理页；不要填写 source_page 或 page_no。",
                "回填后使用 --resume-agent-contract 继续导入；该命令会校验源文件哈希。",
            ],
        }, exclusive=True)
    return contract_path


def import_agent_contract(source_pdf: Path, output_dir: Path) -> Path:
    """Validate a filled handoff contract and produce normalized questions.json."""
    source_pdf = source_pdf.resolve()
    output_dir = checked_output_root(output_dir)
    contract_path = output_dir / CONTRACT_NAME
    contract = _read_json(contract_path, "Agent 中间契约")
    if contract.get("format_version") != CONTRACT_VERSION:
        raise ContractError("Agent 中间契约版本不支持")
    if contract.get("source_name") != source_pdf.name or contract.get("source_sha256") != source_sha256(source_pdf):
        raise ContractError("Agent 中间契约与当前输入文件不匹配，拒绝续跑")
    source_kind = contract.get("source_kind")
    if source_kind not in {"pdf", "text", "docx"}:
        raise ContractError("Agent 中间契约缺少受支持的 source_kind")
    expected_kind = "pdf" if source_pdf.suffix.lower() == ".pdf" else "docx" if source_pdf.suffix.lower() == ".docx" else "text"
    if source_kind != expected_kind:
        raise ContractError("Agent 中间契约类型与当前输入文件不匹配，拒绝续跑")
    pages_payload = _read_json(output_dir / PAGES_NAME, "页码清单") if source_kind == "pdf" else {}
    if source_kind == "pdf" and (
        pages_payload.get("source_name") != source_pdf.name
        or pages_payload.get("source_sha256") != source_sha256(source_pdf)
    ):
        raise ContractError("页码清单与当前输入文件不匹配，拒绝续跑")
    pages = pages_payload.get("pages") or []
    physical_pages = {item.get("physical_page") for item in pages if isinstance(item, dict)}
    if source_kind == "pdf":
        try:
            import pymupdf
            document = pymupdf.open(str(source_pdf))
            try:
                actual_page_count = len(document)
            finally:
                document.close()
        except ImportError as exc:  # pragma: no cover
            raise ImportError("PDF Agent 续跑需要 PyMuPDF；请安装 requirements-import.txt") from exc
        expected_pages = set(range(1, actual_page_count + 1))
        if physical_pages != expected_pages or len(pages) != actual_page_count:
            raise ContractError("页码清单与输入 PDF 的实际物理页不一致，拒绝续跑")
    questions = contract.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ContractError("Agent 中间契约尚未填写 questions，不能导入")
    for question in questions:
        if not isinstance(question, dict):
            raise ContractError("Agent 中间契约含无效题目")
        page = question.get("source_page")
        if source_kind == "pdf":
            if isinstance(page, bool) or not isinstance(page, int) or page not in physical_pages:
                raise ContractError("每题 source_page 必须是页码清单中的确定物理页")
        elif page not in (None, "") or question.get("page_no") not in (None, ""):
            raise ContractError("非 PDF Agent 中间契约不得填写 source_page 或 page_no")
        if question.get("source_file") not in (None, source_pdf.name):
            raise ContractError("Agent 中间契约的 source_file 必须与输入文件一致")
    # Copy, rather than alter contract data in place. source_file is a local
    # provenance fact known from the staged input; source_page remains Agent's
    # asserted physical page and has just been range-checked above.
    normalized = []
    for question in questions:
        item = dict(question, source_file=source_pdf.name)
        if source_kind != "pdf":
            item.pop("source_page", None)
            item.pop("page_no", None)
        normalized.append(item)
    payload = {"questions": normalized}
    validate_questions(payload)
    target = output_dir / "questions.json"
    _check_managed_path(target, output_dir)
    if target.exists() or target.is_symlink():
        raise ContractError("questions.json 已存在，拒绝覆盖")
    _write_json(target, payload, exclusive=True)
    return target


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ContractError(f"{label}不得是符号链接：{path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"缺少{label}：{path.name}") from exc
    except ValueError as exc:
        raise ContractError(f"{label}不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label}必须是 JSON 对象")
    return value


def _atomic_write_bytes(path: Path, content: bytes, *, root: Path, exclusive: bool = False) -> None:
    _check_managed_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _check_managed_path(path, root)
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ContractError(f"{path.name} 已存在，拒绝覆盖") from exc
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: dict[str, Any], *, exclusive: bool = False) -> None:
    root = checked_output_root(path.parent)
    _atomic_write_bytes(
        path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        root=root, exclusive=exclusive,
    )


def _verify_existing_contract(contract_path: Path, source_name: str, digest: str) -> None:
    if not contract_path.exists():
        return
    existing = _read_json(contract_path, "Agent 中间契约")
    if existing.get("source_sha256") != digest or existing.get("source_name") != source_name:
        raise ContractError("已有 Agent 中间契约不属于当前输入文件，拒绝覆盖")
