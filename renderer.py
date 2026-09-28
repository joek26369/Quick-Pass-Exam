"""Render a self-contained Quick Pass learning package with local study state.

The renderer has no server or model dependency.  It accepts already generated
content and copies only explicitly referenced, safe local resources below
``input_dir`` into the output package.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import re
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parent
_TEMPLATE = _ROOT / "templates" / "index.html"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_SOURCE_SUFFIXES = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
_WIKILINK_RE = re.compile(r"^!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]$")
_MARKDOWN_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$", re.MULTILINE)


def _safe_id(value: Any, kind: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{kind} 缺少稳定 id")
    return value


def _safe_relative_path(value: Any) -> Path | None:
    """Return a local relative path, rejecting URLs, absolute and traversal paths."""
    text = str(value or "").strip()
    match = _WIKILINK_RE.match(text)
    if match:
        text = match.group(1).strip()
    if not text or "://" in text or text.startswith(("data:", "javascript:", "file:")):
        return None
    path = Path(text.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


class _Resources:
    def __init__(self, output_dir: Path, input_dir: Path | None) -> None:
        self.output_dir = output_dir.resolve()
        self.input_dir = input_dir.resolve() if input_dir else None
        self.assets_dir = self.output_dir / "assets" / "content"
        self._copied: dict[tuple[Path, str], str] = {}

    def copy(self, value: Any, *, source: bool = False) -> str | None:
        relative = _safe_relative_path(value)
        if not relative or not self.input_dir:
            return None
        candidate = (self.input_dir / relative).resolve()
        try:
            candidate.relative_to(self.input_dir)
        except ValueError:
            return None
        suffix = candidate.suffix.lower()
        allowed = _SOURCE_SUFFIXES if source else _IMAGE_SUFFIXES
        if suffix not in allowed or not candidate.is_file():
            return None
        if suffix == ".svg" and not self._safe_svg(candidate):
            return None
        key = (candidate, "source" if source else "image")
        if key in self._copied:
            return self._copied[key]
        digest = hashlib.sha256(str(relative).encode("utf-8")).hexdigest()[:12]
        destination = self.assets_dir / f"{digest}{suffix}"
        if self.assets_dir.is_symlink() or destination.is_symlink():
            return None
        try:
            self.assets_dir.resolve().relative_to(self.output_dir)
        except ValueError:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, destination)
        result = destination.relative_to(self.output_dir).as_posix()
        self._copied[key] = result
        return result

    def copy_material(self, value: Any, *, source: bool = False) -> tuple[str, Path]:
        """Copy a declared material or fail closed instead of silently omitting it."""
        relative = _safe_relative_path(value)
        if relative is None or self.input_dir is None:
            raise ValueError("教辅资源必须是 input_dir 内的相对本地路径")
        candidate = self.input_dir / relative
        # resolve() alone follows symlinks. Materials are provenance-bearing
        # sources, so reject symlinks at every existing path component.
        current = self.input_dir
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"教辅资源不允许使用符号链接：{relative.as_posix()}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.input_dir)
        except ValueError as exc:
            raise ValueError(f"教辅资源路径越界：{relative.as_posix()}") from exc
        allowed = _SOURCE_SUFFIXES if source else _IMAGE_SUFFIXES
        if resolved.suffix.lower() not in allowed or not resolved.is_file():
            raise ValueError(f"教辅资源不存在或格式不受支持：{relative.as_posix()}")
        copied = self.copy(relative, source=source)
        if not copied:
            raise ValueError(f"教辅资源复制失败：{relative.as_posix()}")
        return copied, resolved

    def render_pdf_page(self, pdf: Path, page: int, source_key: str, *, dpi: int = 120) -> str:
        """Render one verified physical PDF page for offline source checking."""
        digest = hashlib.sha256(f"{source_key}#page={page}".encode("utf-8")).hexdigest()[:12]
        destination = self.assets_dir / f"{digest}-page-{page}.png"
        if self.assets_dir.is_symlink() or destination.is_symlink():
            raise ValueError("PDF 原页图输出路径不安全")
        try:
            self.assets_dir.resolve().relative_to(self.output_dir)
        except ValueError as exc:
            raise ValueError("PDF 原页图输出路径越界") from exc
        if destination.exists():
            return destination.relative_to(self.output_dir).as_posix()
        try:
            from pdf_backend import PdfDocument
            with PdfDocument(pdf) as document:
                if not 1 <= page <= len(document):
                    raise ValueError(f"PDF 物理页超出范围：第 {page} 页")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(document.render_page(page - 1, dpi=dpi))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"PDF 原页图渲染失败：第 {page} 页") from exc
        return destination.relative_to(self.output_dir).as_posix()

    @staticmethod
    def _safe_svg(path: Path) -> bool:
        """SVG is admitted only as a passive local image, never active content."""
        try:
            text = path.read_text(encoding="utf-8")
            if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                return False
            root = ET.fromstring(text)
        except (OSError, UnicodeError, ET.ParseError):
            return False
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            return False
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1].lower()
            if tag in {"script", "foreignobject", "iframe", "style", "animate", "set"}:
                return False
            for name, value in node.attrib.items():
                name = name.rsplit("}", 1)[-1].lower()
                value = value.strip().lower()
                if name.startswith("on") or "javascript:" in value or "url(" in value or "@import" in value:
                    return False
                if name in {"href", "src"} and not value.startswith("#"):
                    return False
        return True



def _normalise_questions(questions: list[dict[str, Any]], resources: _Resources) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in questions:
        q = dict(raw)
        qid = _safe_id(q.get("id"), "题目")
        if qid in seen:
            raise ValueError(f"题目 id 重复：{qid}")
        seen.add(qid)
        options = q.get("options") or []
        if not isinstance(options, list):
            raise ValueError(f"题目 {qid} 的 options 不是列表")
        correct = [o for o in options if isinstance(o, dict) and o.get("is_correct")]
        # Keep incomplete source records readable. They are deliberately marked
        # non-answerable instead of being silently discarded or treated as quiz
        # questions with a guessed answer.
        q["answerable"] = bool(options and correct)
        labels: set[str] = set()
        normal_options = []
        for option in options:
            if not isinstance(option, dict):
                raise ValueError(f"题目 {qid} 存在无效选项")
            label = str(option.get("label", "")).strip()
            if not label or label in labels:
                raise ValueError(f"题目 {qid} 的选项标签为空或重复")
            labels.add(label)
            normal_options.append({"label": label, "text": str(option.get("text") or option.get("text_zh") or option.get("text_en") or ""), "is_correct": bool(option.get("is_correct"))})
        diagrams = q.get("diagram_images") or ([q["diagram_image"]] if q.get("diagram_image") else [])
        inline_sources: list[str] = []
        for stem in (q.get("question_zh"), q.get("question_en")):
            if not isinstance(stem, str):
                continue
            for match in _MARKDOWN_IMAGE_RE.finditer(stem):
                source = match.group(1).strip()
                if source and source not in inline_sources:
                    inline_sources.append(source)

        # Keep original fields untouched. These package-only structures map a
        # source reference to a copied safe asset, so the UI never reads paths
        # outside input_dir and can say when a Markdown image was unavailable.
        copied_inline: dict[str, str | None] = {source: resources.copy(source) for source in inline_sources}
        q["inline_image_assets"] = [
            {"source": source, "asset": asset}
            for source, asset in copied_inline.items()
        ]
        q["unavailable_inline_images"] = [source for source, asset in copied_inline.items() if not asset]

        q["diagram_assets"] = []
        q["unavailable_diagrams"] = []
        for diagram in diagrams:
            # An image embedded in the stem is rendered in that exact reading
            # position, avoiding a second copy above the options.
            if str(diagram).strip() in copied_inline:
                continue
            asset = resources.copy(diagram)
            if asset:
                q["diagram_assets"].append(asset)
            else:
                q["unavailable_diagrams"].append(str(diagram))
        q["options"] = normal_options
        q["concept_ids"] = [str(v) for v in q.get("concept_ids", []) if str(v).strip()]
        q["id"] = qid
        result.append(q)
    return result


def _normalise_concepts(concepts: list[dict[str, Any]], resources: _Resources) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in concepts:
        c = dict(raw)
        cid = _safe_id(c.get("id"), "概念")
        if cid in seen:
            raise ValueError(f"概念 id 重复：{cid}")
        seen.add(cid)
        c["id"] = cid
        c["related_questions"] = [str(v) for v in c.get("related_questions", []) if str(v).strip()]
        c["source_questions"] = [str(v) for v in c.get("source_questions", []) if str(v).strip()]
        image_values = c.get("images", []) or []
        c["image_assets"] = [asset for asset in (resources.copy(v) for v in image_values) if asset]
        c["unavailable_images"] = [str(v) for v in image_values if not resources.copy(v)]
        result.append(c)
    return result


def _normalise_cases(cases: list[dict[str, Any]], methods: list[dict[str, Any]], resources: _Resources,
                     sources: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy the case-only assets into the package and keep the authored text inert.

    Case sources deliberately use the same declared-source boundary as teaching
    evidence.  A missing source is still readable, but it never grows a link to
    an arbitrary path or URL.
    """
    declared: dict[str, tuple[str, Path]] = {}
    for raw in sources or []:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("path"):
            continue
        try:
            copied, local = resources.copy_material(raw["path"], source=True)
        except ValueError:
            continue
        declared[str(raw["id"])] = (copied, local)
    out: list[dict[str, Any]] = []
    child_ids: set[str] = set()
    def attach_origin(item: dict[str, Any], owner: str) -> None:
        source = declared.get(str(item.get("source_id") or ""))
        item["source_file"] = source[0] if source else None
        raw_pages = item.get("source_pages", [])
        if not raw_pages and item.get("page") not in (None, ""):
            raw_pages = [item.get("page")]
        pages = [int(p) for p in raw_pages if _positive_page(p)]
        item["source_pages"] = pages
        item["source_page_assets"] = ([{"page": p, "asset": resources.render_pdf_page(source[1], p, owner, dpi=160)} for p in pages] if source else [])
    for raw in cases or []:
        if not isinstance(raw, dict):
            raise ValueError("cases 存在无效条目")
        row = copy.deepcopy(raw)
        row["id"] = _safe_id(row.get("id"), "案例")
        row["source_pages"] = [int(p) for p in row.get("source_pages", []) if _positive_page(p)]
        source = declared.get(str(row.get("source_id") or ""))
        row["source_file"] = source[0] if source else None
        row["source_warning"] = ("未找到案例来源文件，无法提供原页核对。" if row.get("source_id") and not source else None)
        row["source_page_assets"] = []
        if source:
            for page in row["source_pages"]:
                row["source_page_assets"].append({"page": page, "asset": resources.render_pdf_page(source[1], page, "case:" + row["id"], dpi=160)})
        diagram_values = row.get("diagram_images", []) or []
        row["diagram_assets"] = []
        row["unavailable_diagrams"] = []
        page_assets = {item["page"]: item["asset"] for item in row["source_page_assets"]}
        for diagram in diagram_values:
            if isinstance(diagram, dict):
                path = diagram.get("path")
                page = _positive_page(diagram.get("page")) if diagram.get("page") not in (None, "") else None
                asset = (resources.copy(path) if path else
                         (page_assets.get(page) or (resources.render_pdf_page(source[1], page, "case-diagram:" + row["id"], dpi=160) if source and page else None)))
                label = str(path or ("第 " + str(page) + " 页" if page else "未提供路径"))
            else:
                asset = resources.copy(diagram); label = str(diagram)
            if asset:
                row["diagram_assets"].append(asset)
            else:
                row["unavailable_diagrams"].append(label)
        # A photographed case has no PDF page number. Show its declared source
        # image directly so the original remains visible beside the transcript.
        if source and source[1].suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            if source[0] not in row["diagram_assets"]:
                row["diagram_assets"].insert(0, source[0])
        children = []
        for item in row.get("sub_questions", []):
            if not isinstance(item, dict):
                raise ValueError("案例子题存在无效条目")
            child = dict(item)
            child["id"] = _safe_id(child.get("id"), "案例子题")
            if child["id"] in child_ids:
                raise ValueError("案例子题 id 重复：" + child["id"])
            child_ids.add(child["id"])
            child["source_pages"] = [int(p) for p in child.get("source_pages", []) if _positive_page(p)]
            answer = child.get("reference_answer")
            if isinstance(answer, dict):
                answer = dict(answer); child["reference_answer"] = answer
                attach_origin(answer, "case-answer:" + child["id"])
            score = child.get("score")
            if isinstance(score, dict):
                score = dict(score); child["score"] = score
                attach_origin(score, "case-score:" + child["id"])
            for step in child.get("calculation_steps", []) or []:
                if not isinstance(step, dict):
                    continue
                for basis in step.get("input_basis", []) or []:
                    if isinstance(basis, dict): attach_origin(basis, "case-basis:" + child["id"])
            for point in child.get("scoring_points", []) or []:
                if isinstance(point, dict): attach_origin(point, "case-point:" + child["id"])
            children.append(child)
        row["sub_questions"] = children
        out.append(row)
    normalized_methods = []
    for raw in methods or []:
        if not isinstance(raw, dict):
            raise ValueError("methods 存在无效条目")
        row = copy.deepcopy(raw); row["id"] = _safe_id(row.get("id"), "方法")
        row["sub_question_ids"] = [str(v) for v in row.get("sub_question_ids", []) if str(v).strip()]
        row["concept_ids"] = [str(v) for v in row.get("concept_ids", []) if str(v).strip()]
        for basis in row.get("case_basis", []) or []:
            if isinstance(basis, dict):
                attach_origin(basis, "method-basis:" + row["id"])
        normalized_methods.append(row)
    return out, normalized_methods


def _positive_page(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("教辅证据 page 必须是正整数")
    if isinstance(value, str) and not value.isdigit():
        raise ValueError("教辅证据 page 必须是正整数")
    page = int(value)
    if page <= 0:
        raise ValueError("教辅证据 page 必须是正整数")
    return page


def _normalise_teaching_evidence(
    sources: list[dict[str, Any]] | None,
    teaching_evidence: list[dict[str, Any]] | None,
    concepts: list[dict[str, Any]],
    resources: _Resources,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the static textbook view from the canonical Agent contract.

    Source paths are copied from ``input_dir``. Evidence refers to sources
    and concepts by stable IDs; it can never introduce an arbitrary URL.
    """
    if sources is None and teaching_evidence is None:
        return [], []
    # A case package can declare a question-bank PDF solely for offline case
    # pages.  It has no teaching-evidence rows and should not be forced into
    # the teaching-material contract.
    if isinstance(sources, list) and teaching_evidence is None and not any(
        isinstance(row, dict) and row.get("role") == "teaching_material" for row in sources
    ):
        return [], []
    if not isinstance(sources, list) or not isinstance(teaching_evidence, list):
        raise TypeError("sources 与 teaching_evidence 必须同时是列表")
    source_rows: list[dict[str, Any]] = []
    source_map: dict[str, dict[str, Any]] = {}
    for raw in sources:
        if not isinstance(raw, dict):
            raise ValueError("sources 存在无效条目")
        if raw.get("role") != "teaching_material":
            continue
        source_id = _safe_id(raw.get("id"), "教辅 source")
        if source_id in source_map:
            raise ValueError(f"教辅 source id 重复：{source_id}")
        source_value = raw.get("path")
        copied, source_path = resources.copy_material(source_value, source=True)
        row = {
            "id": source_id,
            "title": str(raw.get("title") or Path(str(source_value)).name),
            "source_file": copied,
            "source_path": source_path,
        }
        source_map[source_id] = row
        source_rows.append({k: v for k, v in row.items() if k != "source_path"})

    concept_ids = {c["id"] for c in concepts}
    evidence_rows: list[dict[str, Any]] = []
    for raw in teaching_evidence:
        if not isinstance(raw, dict):
            raise ValueError("teaching_evidence 存在无效条目")
        source_id = _safe_id(raw.get("source_id"), "教辅证据 source_id")
        if source_id not in source_map:
            raise ValueError(f"教辅证据关联了不存在的教辅：{source_id}")
        linked_concepts = raw.get("concept_ids")
        if not isinstance(linked_concepts, list) or not linked_concepts:
            raise ValueError("teaching_evidence.concept_ids 必须是非空列表")
        locator = raw.get("locator")
        if not isinstance(locator, dict):
            raise ValueError("teaching_evidence.locator 必须是对象")
        page = _positive_page(locator.get("page"))
        material = source_map[source_id]
        thumbnail = None
        image_value = locator.get("page_image")
        if image_value:
            thumbnail, _ = resources.copy_material(image_value)
        elif page is not None:
            thumbnail = resources.render_pdf_page(material["source_path"], page, source_id)
        source_link = material["source_file"] + (f"#page={page}" if page else "")
        for concept_id in linked_concepts:
            cid = _safe_id(concept_id, "教辅证据 concept_id")
            if cid not in concept_ids:
                raise ValueError(f"教辅证据关联了不存在的概念：{cid}")
            evidence_rows.append({
                "id": raw.get("id"), "concept_id": cid, "source_id": source_id,
                "source_file": material["source_file"], "source_title": material["title"],
                "anchor": str(locator.get("anchor") or "").strip(),
                "snippet": str(locator.get("excerpt") or "").strip(), "page": page,
                "thumbnail": thumbnail, "source_link": source_link,
                "relation": str(raw.get("relation") or "").strip(),
                "status": str(raw.get("status") or "").strip(),
                "region": _normalise_region(locator.get("region")),
            })
    return source_rows, evidence_rows


def _normalise_region(value: Any) -> dict[str, float] | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        value = dict(zip(("x", "y", "width", "height"), value))
    if not isinstance(value, dict):
        raise ValueError("教辅证据 region 必须是归一化矩形")
    try:
        region = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("教辅证据 region 必须包含 x/y/width/height") from exc
    x, y, width, height = (region[k] for k in ("x", "y", "width", "height"))
    if not (0 <= x < 1 and 0 <= y < 1 and width > 0 and height > 0
            and x + width <= 1 and y + height <= 1):
        raise ValueError("教辅证据 region 必须位于 0-1 页面范围内")
    return region


def _validate_links(questions: list[dict[str, Any]], concepts: list[dict[str, Any]],
                    cases: list[dict[str, Any]] | None = None) -> None:
    qids = {q["id"] for q in questions}
    case_child_ids = {str(child.get("id")) for case in cases or []
                      for child in case.get("sub_questions", []) if isinstance(child, dict)}
    cids = {c["id"] for c in concepts}
    bad_concepts = sorted({cid for q in questions for cid in q["concept_ids"] if cid not in cids})
    bad_questions = sorted({qid for c in concepts for qid in (c["related_questions"] + c["source_questions"])
                            if qid not in qids and qid not in case_child_ids})
    if bad_concepts:
        raise ValueError("题目关联了不存在的概念：" + ", ".join(bad_concepts))
    if bad_questions:
        raise ValueError("概念关联了不存在的题目：" + ", ".join(bad_questions))
    reverse: dict[str, list[str]] = {cid: [] for cid in cids}
    for q in questions:
        for cid in q["concept_ids"]:
            reverse[cid].append(q["id"])
    for c in concepts:
        # `source_questions` is the more specific source relationship; retain
        # both existing sides and fill gaps from the question-side relation.
        c["question_ids"] = list(dict.fromkeys(c["source_questions"] + c["related_questions"] + reverse[c["id"]]))


def _source_link(question: dict[str, Any], resources: _Resources) -> str | None:
    page = question.get("source_page", question.get("page_no"))
    if isinstance(page, bool) or not isinstance(page, (int, str)):
        return None
    if isinstance(page, str) and not page.isdigit():
        return None
    page = int(page)
    if page <= 0:
        return None
    copied = resources.copy(question.get("source_file"), source=True)
    return f"{copied}#page={page}" if copied else None


def _escape_json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _client_script(payload: dict[str, Any]) -> str:
    data = _escape_json_for_script(payload)
    progress_script = (_ROOT / "templates" / "progress.js").read_text(encoding="utf-8")
    case_script = (_ROOT / "templates" / "case-learning.js").read_text(encoding="utf-8")
    group_script = (_ROOT / "templates" / "question-groups.js").read_text(encoding="utf-8")
    # Data stays JSON. All learner content passes through textContent in the UI,
    # preventing input text from becoming executable package content.
    return "\n".join((_ROOT / "templates" / name).read_text(encoding="utf-8") for name in ("cornell.js", "graph.js", "comparisons.js", "learning-details.js", "materials.js")) + f"""\nconst DATA={data};
const $=s=>document.querySelector(s), esc=v=>String(v??'');
const nullMap=entries=>Object.assign(Object.create(null),Object.fromEntries(entries));
const Q=DATA.questions, C=DATA.concepts, QMAP=nullMap(Q.map(x=>[x.id,x])), CMAP=nullMap(C.map(x=>[x.id,x]));
const state={{view:'notes',cid:C[0]?.id,qid:Q[0]?.id,answers:Object.create(null),picked:Object.create(null),wrongbook:[],savedChoices:[],dismissedChoices:[],caseBookmarks:[],storageStatus:'正在读取作答记录…'}};
{progress_script}
function el(tag, text, cls){{const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n}}
function add(parent,tag,text,cls){{const n=el(tag,text,cls);parent.append(n);return n}}
function button(text,fn,cls){{const n=el('button',text,cls);n.type='button';n.onclick=fn;return n}}
function linkButton(text,fn){{return button(text,fn,'') }}
function markdown(parent,text,inlineAssets=[]){{const lines=String(text||'').split(String.fromCharCode(10)),imageOnly=/^\\s*!\\[([^\\]]*)\\]\\(([^)]*)\\)\\s*$/,assetBySource=new Map((Array.isArray(inlineAssets)?inlineAssets:[]).filter(x=>x&&typeof x.source==='string').map(x=>[x.source,x.asset]));const cells=line=>line.trim().replace(/^\\|/,'').replace(/\\|$/,'').split('|').map(x=>x.trim());for(let i=0;i<lines.length;i++){{const line=lines[i],match=line.match(imageOnly);if(match){{const source=match[2].trim(),asset=assetBySource.get(source);if(asset)image(parent,asset,match[1]||'题干图片');else callout(parent,'题干图片不可用',source||'未提供图片路径','warning');continue}}if(line.includes('|')&&i+1<lines.length&&cells(lines[i+1]).every(x=>/^:?-{{3,}}:?$/.test(x))){{const table=el('table',undefined,'markdown-table');const head=table.createTHead().insertRow();cells(line).forEach(v=>add(head,'th',v));const body=table.createTBody();i+=2;while(i<lines.length&&lines[i].includes('|')){{const row=body.insertRow();cells(lines[i]).forEach(v=>add(row,'td',v));i++}}i--;parent.append(table)}}else if(line.trim()){{add(parent,'p',line)}}}}}}
function stats(){{const a=Object.values(state.answers), ok=a.filter(x=>x.ok).length; $('#stats').textContent=`选择题已做 ${{a.length}} · 答对 ${{ok}} · 答错 ${{a.length-ok}} · 待复习错题 ${{state.wrongbook.length}}`; const wrongbookButton=$('nav [data-view=wrongbook]');if(wrongbookButton)wrongbookButton.textContent=`错题本（${{state.wrongbook.length}}）`;}}
function sidebar(){{const s=$('#sidebar');s.replaceChildren();if(state.view==='wrongbook'){{StudyProgress.renderWrongbook(s);return}}if(state.view==='methods'){{add(s,'strong','方法卡');for(const m of METHODS)s.append(button(m.title||m.id,()=>{{state.methodId=m.id;render()}},state.methodId===m.id?'active':''));return}}const search=document.createElement('input');search.type='search';search.placeholder=state.view==='notes'?'搜索考点':'搜索题目或批次';search.value=state.search||'';s.append(search);const list=add(s,'div',undefined,'sidebar-list');const draw=()=>{{list.replaceChildren();const kw=(state.search||'').trim();if(state.view==='cases'||state.view==='quiz')renderGroupedSidebar(list,state.view,kw);else renderNotesSidebar(list,kw)}};search.oninput=()=>{{state.search=search.value;draw()}};draw()}}
function rail(){{const r=$('#rail');r.replaceChildren();if(state.view==='wrongbook'){{renderWrongbookRail(r);return}}if(state.view==='cases'){{renderCaseRail(r);return}}if(state.view==='methods'){{renderMethodRail(r);return}}const note=state.view==='notes';add(r,'strong',note?'关联真题':'本题考点');if(note)r.classList.add('related-question-rail');else r.classList.remove('related-question-rail');const ids=note?(CMAP[state.cid]?.question_ids||[]):(QMAP[state.qid]?.concept_ids||[]);for(const id of ids){{const open=()=>{{if(note){{if(QMAP[id]){{state.view='quiz';state.qid=id}}else if(CASES.some(c=>(c.sub_questions||[]).some(q=>q.id===id))){{state.view='cases';state.childId=id}}}}else{{state.view='notes';state.cid=id}}render()}};if(note){{const link=relatedQuestionButton(id,open);if(link)r.append(link)}}else r.append(button(CMAP[id]?.title||id,open))}}}}
function callout(parent,title,body,cls=''){{if(!body)return;const box=add(parent,'div',undefined,'callout '+cls);add(box,'strong',title);add(box,'div',body)}}
function textList(parent,title,values){{if(!Array.isArray(values)||!values.length)return;add(parent,'h3',title);const ul=add(parent,'ul');for(const v of values)add(ul,'li',typeof v==='string'?v:(v.text||v.tip||JSON.stringify(v)))}}
function image(parent,path,alt){{if(!path)return;const im=document.createElement('img');im.src=path;im.alt=alt;im.loading='lazy';im.className='image';im.onerror=()=>{{const warning=$('#save-warning');if(warning)warning.textContent=' · 图片资源加载失败；请让 Agent 使用电脑端学习库返回的 http:// 地址打开完整学习包。'}};parent.append(im)}}
function source(parent,q){{if(q.source_link){{const a=document.createElement('a');a.href=q.source_link;a.target='_blank';a.rel='noopener';a.textContent=`来源文件，第 ${{q.source_page}} 页`;parent.append(a)}}else if(q.source_file||q.source_page||q.page_no)callout(parent,'来源','未提供可复制、可定位的本地来源文件与确定物理页。','warning');if(q.source_page_asset){{const details=add(parent,'details',undefined,'question-source-page');/* Keep the source page collapsed across quiz redraws. Selecting an option redraws the question, and opening it here made the PDF pop open unexpectedly. */details.open=false;add(details,'summary',`查看原题所在第 ${{q.source_page}} 页（可能包含多题）`);const zoom=add(details,'a');zoom.href=q.source_page_asset;zoom.target='_blank';zoom.rel='noopener';image(zoom,q.source_page_asset,'原题 PDF 第 '+q.source_page+' 页');add(details,'p','点击页面图可放大核对图表与数字；也可用上方链接打开原 PDF。','muted')}}}}
{case_script}
{group_script}
function sameStructuredValue(left,right){{return JSON.stringify(left??null)===JSON.stringify(right??null)}}
function showNote(){{const c=CMAP[state.cid],out=$('#content');out.replaceChildren();const a=el('article');out.append(a);add(a,'h2',c.title||c.id);add(a,'p',c.one_liner||'', 'muted');const cc=c.core_concept||{{}};callout(a,'定义',cc.definition);callout(a,'原理',cc.principle);textList(a,'关键规则',cc.rules);if(cc.syntax){{add(a,'h3','公式/框架');add(a,'pre',cc.syntax,'formula')}} renderComparisons(a,c); textList(a,'最佳实践',c.best_practices);callout(a,'记忆口诀',c.mnemonic);callout(a,'为什么考',c.why_tested);if(Array.isArray(c.common_mistakes)&&c.common_mistakes.length){{add(a,'h3','易错点');for(const m of c.common_mistakes)callout(a,'易错：'+(m.mistake||''),m.correct||'', 'warning')}} const cn=c.cornell_note||{{}};renderCornell(a,cn);if(Array.isArray(c.tags)&&c.tags.length){{const tags=add(a,'div',undefined,'relation');for(const tag of c.tags)add(tags,'span',tag)}}if(Array.isArray(c.image_assets))for(const p of c.image_assets)image(a,p,'教辅原图');if((c.unavailable_images||[]).length)callout(a,'资源不可用','以下教辅图没有复制到学习包：'+c.unavailable_images.join('；'),'warning');renderMaterialEvidence(a,c.id,DATA.teaching_evidence||[]);renderKnowledgeGraph(a,c.visualization);renderConceptLearningLinks(a,c);renderConceptQuestionLinks(a,c);renderConceptFidelityDetails(a,c);}}
async function answer(q){{if(!q.answerable||state.saving)return;const pick=state.picked[q.id]||[];state.saving=true;try{{await StudyProgress.record(q,pick);render()}}catch(error){{state.storageStatus=error.message||'作答保存失败';render()}}finally{{state.saving=false}}}}
function showQuiz(){{const q=QMAP[state.qid],out=$('#content');out.replaceChildren();const a=el('article');out.append(a);add(a,'h2','第'+(QUIZ_GROUPS.byId.get(q.id)?.number||1)+'题');add(a,'p',q.question_zh||q.question_en||'');renderQuestionTrustWarning(a,q);source(a,q);a.append(button(state.savedChoices.includes(q.id)?'取消收藏':'收藏进错题本',()=>changeWrongbook('choice',q,!state.savedChoices.includes(q.id)),'button'));for(const p of q.diagram_assets||[])image(a,p,'题目图表');if((q.unavailable_diagrams||[]).length)callout(a,'资源不可用','以下题图/表格没有复制到学习包：'+q.unavailable_diagrams.join('；'),'warning');const picked=state.picked[q.id]||[],done=state.answers[q.id];const opts=add(a,'div',undefined,'options');for(const o of q.options){{const b=button(o.label+' · '+o.text,()=>{{if(done||!q.answerable)return;const multi=q.options.filter(x=>x.is_correct).length>1;if(multi){{const i=picked.indexOf(o.label);i<0?picked.push(o.label):picked.splice(i,1)}}else{{picked.splice(0,picked.length,o.label)}}state.picked[q.id]=picked;render()}},'option '+(picked.includes(o.label)?'selected ':'')+(done?(o.is_correct?'ok':picked.includes(o.label)?'bad':''):''));opts.append(b)}}if(!q.answerable)callout(a,'不可作答','来源题目缺少选项或确定答案；已保留为阅读材料，未猜测答案。','warning');else if(!done)a.append(button('提交答案',()=>answer(q),'button primary'));add(a,'h3','关联考点');const links=add(a,'div',undefined,'links');for(const cid of q.concept_ids||[])links.append(linkButton(CMAP[cid]?.title||cid,()=>{{state.view='notes';state.cid=cid;render()}}));if(done){{callout(a,done.ok?'答对':'答错',done.ok?'本题已答对。':'已保存到持久错题本，可从本地学习库跨包复习。',done.ok?'':'error');a.append(button('重做本题',()=>{{delete state.answers[q.id];delete state.picked[q.id];render()}},'button'));callout(a,'题库解析原文',q.explanation);if(q.answer_mismatch)renderAnswerMismatchDetails(a,q);if(Array.isArray(q.option_analyses)&&q.option_analyses.length){{add(a,'h3','已有选项分析');for(const x of q.option_analyses){{callout(a,(x.option||'')+(x.is_correct?' ✓':' ✗'),x.analysis||'');if(Array.isArray(x.quotes)&&x.quotes.length)callout(a,'引用摘录',x.quotes.join(String.fromCharCode(10)))}}}}renderQuestionLearningDetails(a,q);textList(a,'已有记忆辅助',q.memory_tips);const cn=q.cornell_note||{{}},ga=q.generated_analysis||{{}};if(cn.cues||cn.notes||cn.pairs){{if(!sameStructuredValue(cn,ga.cornell_note))renderCornell(a,cn,'题库康奈尔笔记')}}if(Object.keys(ga).length){{add(a,'h3','模型生成辅助解释');callout(a,'模型说明','以下内容由模型生成，用于学习辅助，不是题库原解析。','warning');renderAnswerMismatchDetails(a,q,ga);callout(a,'模型解释',ga.explanation||ga.analysis);if(Array.isArray(ga.option_analyses))for(const x of ga.option_analyses)callout(a,'模型选项 '+(x.option||''),x.analysis||'');renderQuestionLearningDetails(a,ga,'模型生成');textList(a,'模型记忆辅助',ga.memory_tips);renderCornell(a,ga.cornell_note,'模型辅助康奈尔笔记')}}}}}}
function showWrongbook(){{showWrongbookBody()}}
function render(){{if(state.view==='cases')selectedCase();if(state.view==='methods')selectedMethod();document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-selected',b.dataset.view===state.view));sidebar();state.view==='notes'?showNote():state.view==='wrongbook'?showWrongbook():state.view==='cases'?showCases():state.view==='methods'?showMethods():showQuiz();stats()}}
const _rawShowNote=showNote;showNote=function(){{if(!CMAP[state.cid]){{const out=$('#content');out.replaceChildren();const a=add(out,'article');add(a,'h2','暂无考点笔记');add(a,'p','此学习包当前仅包含案例题或方法卡。','muted');return}}_rawShowNote()}};
const _rawShowQuiz=showQuiz;showQuiz=function(){{if(!QMAP[state.qid]){{const out=$('#content');out.replaceChildren();const a=add(out,'article');add(a,'h2','暂无选择题');add(a,'p','此学习包当前仅包含案例题或方法卡。','muted');return}}_rawShowQuiz()}};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{{state.view=b.dataset.view;state.search='';render()}});const profileName=DATA.profile?.exam_name_zh||DATA.profile?.exam_full_name||DATA.profile?.exam_name||DATA.profile?.name||'未命名科目',profileId=DATA.profile?.exam_code||'unknown';$('#profile-name').textContent=profileName;$('#profile-id').textContent=profileId;document.body.dataset.profile=profileId;document.title=DATA.profile?.exam_full_name||DATA.profile?.exam_name||DATA.profile?.name||'Quick Pass Exam-快考通';
const _showQuiz=showQuiz;
showQuiz=function(){{_showQuiz();const q=QMAP[state.qid],article=$('#content article');if(!q)return;const group=QUIZ_GROUPS.byId.get(q.id),batch=group?.group||Q,qi=group?group.number-1:Q.findIndex(x=>x.id===q.id);const submit=[...article.querySelectorAll('button')].find(b=>b.textContent==='提交答案');if(submit)submit.disabled=!(state.picked[q.id]||[]).length;const bar=el('div',undefined,'qbar');bar.append(el('span',(qi+1)+' / '+batch.length+' · '+(group?.year||'')+(group?.half||'')+' '+(group?.batch||'')));const track=el('div',undefined,'track'),fill=el('i');fill.style.width=((qi+1)/batch.length*100)+'%';track.append(fill);bar.append(track);article.prepend(bar);const nav=el('div',undefined,'links');if(qi>0)nav.append(button('上一题',()=>{{state.qid=batch[qi-1].id;render()}},'button'));if(qi<batch.length-1)nav.append(button('下一题',()=>{{state.qid=batch[qi+1].id;render()}},'button'));article.append(nav);const dots=el('div',undefined,'qnav');batch.forEach((x,i)=>dots.append(button(String(i+1),()=>{{state.qid=x.id;render()}},i===qi?'current':'')));article.append(dots);const para=article.querySelector('p');if(para){{const block=el('div',undefined,'question-body');markdown(block,q.question_zh||q.question_en||'',q.inline_image_assets||[]);para.replaceWith(block)}}}};
const _showNote=showNote;showNote=function(){{_showNote();const c=CMAP[state.cid],a=$('#content article');if(!c)return;callout(a,'内容说明','考点笔记用于学习辅助；事实应以题库及输入中提供的来源为准。','warning');const relatedMethods=METHODS.filter(m=>(m.concept_ids||[]).includes(c.id));if(relatedMethods.length){{add(a,'h3','关联方法');const links=add(a,'div',undefined,'links');for(const m of relatedMethods)links.append(linkButton(m.title||m.id,()=>{{state.view='methods';state.methodId=m.id;render()}}));}}}};
const _render=render;render=function(){{_render();rail();const status=(state.view==='cases'||state.view==='methods')?state.caseStatus:state.storageStatus;$('#storage-status').title=status||'';$('#save-warning').textContent=/(失败|无法|未保存|不可用|单文件模式)/.test(status||'')?' · '+status:''}};
StudyProgress.load().then(render).catch(error=>{{state.storageStatus=error.message||'无法保存作答记录';render()}});
CaseProgress.load().then(render).catch(error=>{{state.caseStatus=error.message||'案例题记录无法读取';render()}});"""


def render_package(
    questions: list[dict[str, Any]],
    concepts: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    input_dir: str | Path | None = None,
    profile: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    teaching_evidence: list[dict[str, Any]] | None = None,
    quality_summary: dict[str, Any] | None = None,
    cases: list[dict[str, Any]] | None = None,
    methods: list[dict[str, Any]] | None = None,
) -> Path:
    """Create ``index.html`` and return its path.

    ``output_dir`` is created if necessary. Existing files may be replaced only
    inside that directory; input resources are always read from ``input_dir``.
    """
    if not isinstance(questions, list) or not isinstance(concepts, list):
        raise TypeError("questions 与 concepts 必须是列表")
    destination = Path(output_dir).resolve()
    source_root = Path(input_dir).resolve() if input_dir is not None else None
    if source_root and destination == source_root:
        raise ValueError("output_dir 不能与 input_dir 相同")
    destination.mkdir(parents=True, exist_ok=True)
    logo = _ROOT / "assets" / "logo-mark.png"
    if not logo.is_file():
        raise FileNotFoundError("缺少 Quick Pass 品牌图标：assets/logo-mark.png")
    logo_destination = destination / "assets" / "logo-mark.png"
    logo_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(logo, logo_destination)
    # Browser tabs reserve a square favicon slot. Use a tighter square viewport
    # around the recognisable Q/check so it remains legible at tab-icon size.
    # The embedded brand image keeps its native dimensions and proportions.
    logo_bytes = logo.read_bytes()
    if logo_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Quick Pass 品牌图标不是有效 PNG")
    logo_width, logo_height = struct.unpack(">II", logo_bytes[16:24])
    if not logo_width or not logo_height:
        raise ValueError("Quick Pass 品牌图标尺寸无效")
    icon_size = round(logo_height * 1.12)
    icon_x = (logo_width - icon_size) / 2
    icon_y = (logo_height - icon_size) / 2
    embedded_logo = base64.b64encode(logo_bytes).decode("ascii")
    (destination / "assets" / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
        f'viewBox="{icon_x:g} {icon_y:g} {icon_size} {icon_size}">'
        f'<image x="0" y="0" width="{logo_width}" '
        f'height="{logo_height}" preserveAspectRatio="xMidYMid meet" '
        f'href="data:image/png;base64,{embedded_logo}"/></svg>',
        encoding="utf-8",
    )
    resources = _Resources(destination, source_root)
    qs = _normalise_questions(questions, resources)
    cs = _normalise_concepts(concepts, resources)
    case_rows, method_rows = _normalise_cases(cases or [], methods or [], resources, sources)
    # Review/audit metadata belongs to package reports, not the learner-facing
    # web bundle. Keep learning content and explicit source warnings only.
    for concept in cs:
        concept.pop("content_review", None)
        concept.pop("learning_support_review", None)
    for case in case_rows:
        case.pop("coverage_review", None)
    _validate_links(qs, cs, case_rows)
    source_rows, evidence_rows = _normalise_teaching_evidence(
        sources, teaching_evidence, cs, resources
    )
    for q in qs:
        # source_link is a derived package field. Never trust an input URL or
        # stale path; only a copied local PDF plus a verified page can create it.
        q.pop("source_link", None)
        q.pop("source_page_asset", None)
        link = _source_link(q, resources)
        if link:
            q["source_link"] = link
            q["source_page"] = q.get("source_page", q.get("page_no"))
            copied_pdf = destination / link.split("#", 1)[0]
            q["source_page_asset"] = resources.render_pdf_page(
                copied_pdf, int(q["source_page"]),
                f"question:{q.get('source_file')}:dpi=160", dpi=160,
            )
    payload = {"questions": qs, "concepts": cs, "profile": profile or {},
               "sources": source_rows, "teaching_evidence": evidence_rows,
               "cases": case_rows, "methods": method_rows}
    page = _TEMPLATE.read_text(encoding="utf-8").replace("__QUICK_PASS_DATA__", _client_script(payload))
    index = destination / "index.html"
    index.write_text(page, encoding="utf-8")
    (destination / "question-assets.json").write_text(
        json.dumps({q["id"]: {
            "diagram_assets": q["diagram_assets"],
            "inline_image_assets": q["inline_image_assets"],
            "source_page_asset": q.get("source_page_asset"),
        } for q in qs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "case-assets.json").write_text(
        json.dumps({c["id"]: {"diagram_assets": c["diagram_assets"], "source_page_assets": c["source_page_assets"]}
                    for c in case_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {"format_version": 1, "questions": len(qs), "concepts": len(cs),
                "source_count": len(source_rows), "teaching_evidence_count": len(evidence_rows),
                "profile": profile or {}, "entry": "index.html",
                "cases": len(case_rows), "methods": len(method_rows)}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index
