"""Deterministic, loss-aware document adapters for the Agent handoff path.

The adapters expose source order and local embedded assets. They never infer
questions, answers, OCR text, or source pages.
"""
from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def text_document_payload(path: Path) -> dict[str, Any]:
    """Return complete UTF-8 source text plus deterministic blank-line blocks."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    start: int | None = None
    current: list[str] = []
    for index, line in enumerate(lines, 1):
        if line.strip():
            if start is None:
                start = index
            current.append(line)
        elif current:
            blocks.append({"line_start": start, "line_end": index - 1, "text": "\n".join(current)})
            start, current = None, []
    if current:
        blocks.append({"line_start": start, "line_end": len(lines), "text": "\n".join(current)})
    return {"format_version": 1, "text": text, "blocks": blocks}


def docx_document_payload(path: Path, assets_dir: Path) -> dict[str, Any]:
    """Extract DOCX paragraphs/tables in body order and copy embedded images.

    This intentionally reads the DOCX package directly instead of applying a
    question-bank layout parser. Image references are preserved per paragraph
    or table cell; no visual text is invented for an image.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("DOCX 文件无法读取") from exc
    with archive:
        try:
            root = ET.fromstring(archive.read("word/document.xml"))
        except KeyError as exc:
            raise ValueError("DOCX 缺少 word/document.xml") from exc
        relationship_targets: dict[str, str] = {}
        try:
            rel_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            for rel in rel_root.findall(f"{_REL}Relationship"):
                target = rel.get("Target", "")
                if target.startswith("media/"):
                    relationship_targets[rel.get("Id", "")] = posixpath.normpath(posixpath.join("word", target))
        except KeyError:
            pass
        _safe_assets_directory(assets_dir)
        image_paths: dict[str, str] = {}
        warnings: list[dict[str, str]] = []

        def warn(code: str, message: str) -> None:
            item = {"code": code, "message": message}
            if item not in warnings:
                warnings.append(item)

        def inspect_unextractable(element: ET.Element) -> None:
            if any(node.tag in {f"{_M}oMath", f"{_M}oMathPara"} for node in element.iter()):
                warn("FORMULA_UNEXTRACTED", "检测到 Office 公式对象；未把公式视觉结构改写为文本。")
            if any(node.tag in {f"{_W}object", f"{_W}altChunk"} for node in element.iter()):
                warn("OBJECT_UNEXTRACTED", "检测到不可直接提取的嵌入对象；未臆造其内容。")

        def paragraph_text(element: ET.Element) -> str:
            values: list[str] = []
            for node in element.iter():
                if node.tag == f"{_W}t":
                    values.append(node.text or "")
                elif node.tag == f"{_W}tab":
                    values.append("\t")
                elif node.tag in {f"{_W}br", f"{_W}cr"}:
                    values.append("\n")
            return "".join(values)

        def copied_images(element: ET.Element) -> list[str]:
            result: list[str] = []
            for blip in element.iter(f"{_A}blip"):
                rel_id = blip.get(f"{_R}embed", "")
                member = relationship_targets.get(rel_id)
                if not member or member not in archive.namelist():
                    warn("IMAGE_REFERENCE_UNRESOLVED", "检测到无法解析的 DOCX 嵌图引用；未伪造图片。")
                    continue
                if member not in image_paths:
                    name = Path(member).name
                    target = assets_dir / f"{len(image_paths) + 1:03d}-{name}"
                    if target.is_symlink():
                        raise ValueError("DOCX 嵌图目标不能是符号链接")
                    content = archive.read(member)
                    if target.exists():
                        if target.read_bytes() != content:
                            raise ValueError("DOCX 嵌图目标已存在且内容不一致，拒绝覆盖")
                    else:
                        with target.open("xb") as handle:
                            handle.write(content)
                    image_paths[member] = target.name
                result.append(image_paths[member])
            return result

        def paragraph_item(element: ET.Element) -> dict[str, Any]:
            inspect_unextractable(element)
            text = paragraph_text(element)
            return {"kind": "paragraph", "text": text, "images": copied_images(element)}

        def table_item(element: ET.Element) -> dict[str, Any]:
            inspect_unextractable(element)
            if any(node is not element and node.tag == f"{_W}tbl" for node in element.iter()):
                warn("NESTED_TABLE_UNEXTRACTED", "检测到嵌套表格；外层表格已保留，嵌套表格结构未扁平化。")
            rows: list[list[dict[str, Any]]] = []
            for row in element.findall(f"{_W}tr"):
                cells = []
                for cell in row.findall(f"{_W}tc"):
                    text = "\n".join(paragraph_text(paragraph) for paragraph in cell.findall(f"{_W}p"))
                    cells.append({"text": text, "images": copied_images(cell)})
                rows.append(cells)
            return {"kind": "table", "rows": rows}

        body = root.find(f"{_W}body")
        items: list[dict[str, Any]] = []
        def walk(container: ET.Element) -> None:
            for child in container:
                if child.tag == f"{_W}p":
                    items.append(paragraph_item(child))
                elif child.tag == f"{_W}tbl":
                    items.append(table_item(child))
                elif child.tag == f"{_W}sectPr":
                    continue
                else:
                    # Content controls and tracked/other body wrappers can
                    # contain paragraphs/tables. Recurse in document order;
                    # unknown leaf objects are recorded rather than discarded.
                    if any(node.tag in {f"{_W}p", f"{_W}tbl"} for node in child.iter()):
                        walk(child)
                    else:
                        inspect_unextractable(child)
                        if child.tag not in {f"{_W}sdtPr", f"{_W}sdtEndPr"}:
                            warn("BODY_OBJECT_UNEXTRACTED", "检测到无法展开的 DOCX 文档对象；未臆造其内容。")
        if body is not None:
            walk(body)
    return {"format_version": 1, "items": items, "embedded_images_dir": assets_dir.name,
            "warnings": warnings}


def _safe_assets_directory(assets_dir: Path) -> None:
    if assets_dir.is_symlink():
        raise ValueError("DOCX 嵌图目录不能是符号链接")
    assets_dir.mkdir(parents=True, exist_ok=True)
    if assets_dir.is_symlink() or not assets_dir.is_dir():
        raise ValueError("DOCX 嵌图目录必须是普通目录")
