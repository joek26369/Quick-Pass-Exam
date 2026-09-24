#!/usr/bin/env python3
"""Loopback-only offline study library with persistent attempts and wrongbook."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import html
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen


@contextmanager
def _db(library: Path) -> Iterator[sqlite3.Connection]:
    library = library.expanduser().resolve()
    library.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(library / "learning.sqlite3", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS packages (
            id TEXT PRIMARY KEY, path TEXT NOT NULL, subject TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            subject TEXT NOT NULL, question_key TEXT NOT NULL, snapshot TEXT NOT NULL,
            last_package_id TEXT NOT NULL, last_qid TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0, wrong_count INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 0, mastered INTEGER NOT NULL DEFAULT 0,
            last_correct INTEGER, last_picked TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL,
            PRIMARY KEY(subject, question_key)
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, question_key TEXT NOT NULL,
            package_id TEXT NOT NULL, qid TEXT NOT NULL, picked TEXT NOT NULL,
            correct INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_progress (
            package_id TEXT NOT NULL, sub_question_id TEXT NOT NULL,
            draft TEXT NOT NULL DEFAULT '', self_assessment TEXT,
            review INTEGER NOT NULL DEFAULT 0, revealed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(package_id, sub_question_id)
        );
        CREATE TABLE IF NOT EXISTS collected_mistakes (
            package_id TEXT NOT NULL, qid TEXT NOT NULL,
            PRIMARY KEY(package_id, qid)
        );
        CREATE TABLE IF NOT EXISTS choice_bookmarks (
            subject TEXT NOT NULL, question_key TEXT NOT NULL,
            saved INTEGER NOT NULL DEFAULT 0, dismissed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(subject, question_key)
        );
        CREATE TABLE IF NOT EXISTS case_bookmarks (
            subject TEXT NOT NULL, package_id TEXT NOT NULL, case_id TEXT NOT NULL,
            snapshot TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(package_id, case_id)
        );
    """)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _package(conn: sqlite3.Connection, package_id: str) -> tuple[Path, str]:
    row = conn.execute("SELECT path,subject FROM packages WHERE id=?", (package_id,)).fetchone()
    if row is None:
        raise ValueError("学习包未注册")
    path = Path(row["path"])
    if not (path / "manifest.json").is_file() or not (path / "data/questions.json").is_file():
        raise ValueError("学习包文件已移动或删除；请重新注册")
    return path, row["subject"]


def _questions(path: Path) -> list[dict]:
    value = json.loads((path / "data/questions.json").read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("学习包题目数据无效")
    return value


def _cases(path: Path) -> list[dict]:
    file = path / "data/cases.json"
    if not file.is_file():
        return []
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("学习包案例数据无效")
    return value


def _case_progress(conn: sqlite3.Connection, package_id: str) -> dict:
    path, _ = _package(conn, package_id)
    ids = {sq["id"] for case in _cases(path) for sq in case.get("sub_questions", [])}
    rows = conn.execute("SELECT * FROM case_progress WHERE package_id=?", (package_id,)).fetchall()
    items = {row["sub_question_id"]: {
        "draft": row["draft"], "self_assessment": row["self_assessment"],
        "review": bool(row["review"]), "revealed": bool(row["revealed"]),
        "updated_at": row["updated_at"],
    } for row in rows if row["sub_question_id"] in ids}
    stats = {state: sum(item["self_assessment"] == state for item in items.values())
             for state in ("mastered", "partial", "unmastered")}
    stats.update(total=len(ids), assessed=sum(stats.values()),
                 drafted=sum(bool(item["draft"].strip()) for item in items.values()),
                 review=sum(item["review"] for item in items.values()))
    return {"items": items, "stats": stats}


def _save_case_progress(conn: sqlite3.Connection, package_id: str, payload: dict) -> dict:
    # Case self-assessment never writes objective attempts or computes a score.
    path, _ = _package(conn, package_id)
    ids = {sq["id"] for case in _cases(path) for sq in case.get("sub_questions", [])}
    qid = payload.get("sub_question_id")
    if not isinstance(qid, str) or qid not in ids:
        raise ValueError("案例小问不存在")
    allowed = {"sub_question_id", "draft", "self_assessment", "review", "revealed"}
    if set(payload) - allowed or len(payload) == 1:
        raise ValueError("案例保存字段无效")
    if "draft" in payload and (not isinstance(payload["draft"], str) or len(payload["draft"]) > 20000):
        raise ValueError("作答必须是文本且不超过 20000 字")
    if "self_assessment" in payload and payload["self_assessment"] not in (None, "mastered", "partial", "unmastered"):
        raise ValueError("自评状态无效")
    for key in ("review", "revealed"):
        if key in payload and type(payload[key]) is not bool:
            raise ValueError("复习与展开状态必须是布尔值")
    conn.execute("BEGIN IMMEDIATE")
    old = conn.execute("SELECT * FROM case_progress WHERE package_id=? AND sub_question_id=?", (package_id, qid)).fetchone()
    state = dict(old) if old else {"draft": "", "self_assessment": None, "review": False, "revealed": False}
    state.update(payload)
    conn.execute("""INSERT INTO case_progress(package_id,sub_question_id,draft,self_assessment,review,revealed,updated_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(package_id,sub_question_id) DO UPDATE SET
                    draft=excluded.draft,self_assessment=excluded.self_assessment,review=excluded.review,
                    revealed=excluded.revealed,updated_at=excluded.updated_at""",
                 (package_id,qid,state["draft"],state["self_assessment"],int(state["review"]),
                  int(state["revealed"]),datetime.now(timezone.utc).isoformat()))
    return _case_progress(conn, package_id)


def _question_key(question: dict) -> str:
    """Match the same question across regenerated packages, independent of Agent IDs."""
    def norm(value: object) -> str:
        return " ".join(str(value or "").split()).casefold()
    shape = {
        "stem": norm(question.get("question_zh") or question.get("question_en")),
        "options": [(norm(o.get("label")), norm(o.get("text") or o.get("text_zh") or o.get("text_en")),
                     bool(o.get("is_correct"))) for o in question.get("options", [])],
    }
    return hashlib.sha256(json.dumps(shape, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _snapshot(path: Path, question: dict) -> dict:
    concepts = json.loads((path / "data/concepts.json").read_text(encoding="utf-8"))
    linked = set(question.get("concept_ids") or [])
    methods_file = path / "data/methods.json"
    methods = json.loads(methods_file.read_text(encoding="utf-8")) if methods_file.is_file() else []
    asset_index = path / "web/question-assets.json"
    assets = json.loads(asset_index.read_text(encoding="utf-8")).get(question["id"], {}) if asset_index.is_file() else question
    image_paths = [*(assets.get("diagram_assets") or []),
                   *(item.get("asset") for item in (assets.get("inline_image_assets") or [])
                     if isinstance(item, dict)), assets.get("source_page_asset")]
    return {
        "stem": question.get("question_zh") or question.get("question_en") or "",
        "options": [{"label": o.get("label"), "text": o.get("text") or o.get("text_zh") or o.get("text_en"),
                     "is_correct": bool(o.get("is_correct"))} for o in question["options"]],
        "explanation": question.get("explanation") or "",
        "concepts": [{"id": c.get("id"), "title": c.get("title") or c.get("id"),
                      "one_liner": c.get("one_liner") or "",
                      "summary": (c.get("cornell_note") or {}).get("summary") or ""}
                     for c in concepts if c.get("id") in linked],
        "methods": [{"id": m.get("id"), "title": m.get("title") or m.get("id")}
                    for m in methods if linked.intersection(m.get("concept_ids") or [])],
        "images": list(dict.fromkeys(
            asset for asset in image_paths
            if isinstance(asset, str) and asset.startswith("assets/content/")
            and (path / "web" / asset).is_file()
        )),
    }


def _case_bookmark_snapshot(path: Path, case: dict) -> dict:
    children = case.get("sub_questions") or []
    concept_ids = {cid for child in children for cid in child.get("concept_ids") or []}
    method_ids = {mid for child in children for mid in child.get("method_ids") or []}
    concepts_file, methods_file = path / "data/concepts.json", path / "data/methods.json"
    concepts = json.loads(concepts_file.read_text(encoding="utf-8")) if concepts_file.is_file() else []
    methods = json.loads(methods_file.read_text(encoding="utf-8")) if methods_file.is_file() else []
    asset_file = path / "web/case-assets.json"
    assets = json.loads(asset_file.read_text(encoding="utf-8")).get(case["id"], {}) if asset_file.is_file() else {}
    image_paths = [*(assets.get("diagram_assets") or []),
                   *(item.get("asset") for item in assets.get("source_page_assets") or []
                     if isinstance(item, dict))]
    return {
        "id": case["id"], "original_number": case.get("original_number") or case["id"],
        "scenario": case.get("scenario") or "",
        "sub_questions": [{
            "id": child.get("id"), "original_number": child.get("original_number") or child.get("id"),
            "type": child.get("type"), "question": child.get("question") or "",
            "reference_answer": child.get("reference_answer") or {},
            "generated_analysis": child.get("generated_analysis") or "",
        } for child in children],
        "concepts": [{"id": c.get("id"), "title": c.get("title") or c.get("id")}
                     for c in concepts if c.get("id") in concept_ids],
        "methods": [{"id": m.get("id"), "title": m.get("title") or m.get("id")}
                    for m in methods if m.get("id") in method_ids],
        "images": list(dict.fromkeys(
            asset for asset in image_paths
            if isinstance(asset, str) and asset.startswith("assets/content/")
            and (path / "web" / asset).is_file()
        )),
    }


def register(library: Path, package: Path) -> tuple[str, str]:
    package = package.resolve(strict=True)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("quality_status") in {"blocked", "failed"}:
        raise ValueError("学习包内容检查未通过，不能注册；请先修订后重新生成")
    subject = manifest.get("profile")
    if not isinstance(subject, str) or not subject or not (package / "web/index.html").is_file():
        raise ValueError("需要已完成的学习包目录（含 manifest.json 与 web/index.html）")
    if not _questions(package) and not _cases(package):
        raise ValueError("学习包没有题目")
    package_id = hashlib.sha256(str(package).encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat()
    with _db(library) as conn:
        conn.execute("INSERT INTO packages(id,path,subject,created_at) VALUES(?,?,?,?) "
                     "ON CONFLICT(id) DO UPDATE SET path=excluded.path,subject=excluded.subject",
                     (package_id, str(package), subject, now))
    return package_id, subject


def _library_id(library: Path) -> str:
    return hashlib.sha256(str(library.expanduser().resolve()).encode()).hexdigest()


def _server_status(library: Path, port: int) -> str:
    """Return same, absent, or occupied; never reuse an unrelated port."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.3) as response:
            data = json.loads(response.read(1024))
        return "same" if data.get("library_id") == _library_id(library) else "occupied"
    except OSError as exc:
        from urllib.error import HTTPError, URLError
        if isinstance(exc, HTTPError):
            return "occupied"
        if isinstance(exc, URLError) and isinstance(exc.reason, ConnectionRefusedError):
            return "absent"
        return "occupied"
    except (ValueError, AttributeError, TypeError):
        return "occupied"


def ensure_server(library: Path, port: int, *, require_cases: bool = False,
                  require_wrongbook_details: bool = False,
                  require_asset_ranges: bool = False) -> bool:
    """Start the local library once, or reuse the one for this library."""
    library = library.expanduser().resolve()
    status = _server_status(library, port)
    if status == "same":
        if require_cases or require_wrongbook_details or require_asset_ranges:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                capabilities = json.loads(response.read(4096)).get("capabilities", [])
            if require_cases and "case-progress-v1" not in capabilities:
                raise RuntimeError("该端口的旧版学习服务不支持案例保存；请用本版本 study_server.py 和新的 --port 打开现有学习包")
            if require_wrongbook_details and "mixed-wrongbook-v1" not in capabilities:
                raise RuntimeError("该端口的旧版学习服务不支持选择题与案例混合错题本；请用本版本 study_server.py 并换一个 --port 打开学习包")
            if require_asset_ranges and "asset-range-v1" not in capabilities:
                raise RuntimeError("该端口的旧版学习服务不支持手机端图片/PDF分段读取；请用本版本 study_server.py 并换一个 --port 打开学习包")
        return False
    if status == "occupied":
        raise RuntimeError(f"本机端口 {port} 已被其他服务或学习库占用；请换用 --port")
    library.mkdir(parents=True, exist_ok=True)
    # The long-lived local reader needs no model credentials from the Agent.
    service_env = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "PYTHONPATH"}
                   or key.startswith("LC_")}
    with (library / "service.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--library", str(library),
             "--port", str(port), "serve"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
            env=service_env,
        )
    for _ in range(50):
        status = _server_status(library, port)
        if status == "same":
            return True
        if status == "occupied":
            raise RuntimeError(f"本机端口 {port} 被其他服务占用；请换用 --port")
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError(f"本地学习库未能启动；请查看 {library / 'service.log'}")


def package_url(package_id: str, port: int) -> str:
    return f"http://127.0.0.1:{port}/packages/{package_id}/web/index.html"


def _progress(conn: sqlite3.Connection, package_id: str) -> dict:
    path, subject = _package(conn, package_id)
    current = {_question_key(q): q["id"] for q in _questions(path)}
    rows = conn.execute("SELECT * FROM questions WHERE subject=? ORDER BY updated_at DESC", (subject,)).fetchall()
    flags = {row["question_key"]: row for row in conn.execute(
        "SELECT * FROM choice_bookmarks WHERE subject=?", (subject,)).fetchall()}
    answers: dict[str, dict] = {}
    wrongbook: list[dict] = []
    saved_choices: list[str] = []
    for row in rows:
        qid = current.get(row["question_key"])
        flag = flags.get(row["question_key"])
        saved = bool(flag and flag["saved"])
        dismissed = bool(flag and flag["dismissed"])
        if qid is not None and saved:
            saved_choices.append(qid)
        if qid is not None and row["last_correct"] is not None:
            answers[qid] = {
                "ok": bool(row["last_correct"]), "picked": json.loads(row["last_picked"]),
                "attempt_count": row["attempt_count"], "wrong_count": row["wrong_count"],
                "streak": row["streak"], "mastered": bool(row["mastered"]),
            }
        if saved or (row["wrong_count"] and not row["mastered"] and not dismissed):
            snapshot = json.loads(row["snapshot"])
            wrongbook.append({
                "kind": "choice", "question_key": row["question_key"], "qid": qid,
                "stem": snapshot.get("stem", ""), "wrong_count": row["wrong_count"],
                "streak": row["streak"],
                "picked": json.loads(row["last_picked"]) if row["last_picked"] else [],
                "snapshot": snapshot, "source_package_id": row["last_package_id"],
                "saved": saved, "updated_at": row["updated_at"],
                "history_url": "/history/" + quote(subject, safe="") + "/" + row["question_key"],
            })
    current_cases = {case["id"] for case in _cases(path)}
    case_bookmarks: list[str] = []
    for row in conn.execute("SELECT * FROM case_bookmarks WHERE subject=?", (subject,)).fetchall():
        snapshot = json.loads(row["snapshot"])
        if row["package_id"] == package_id and row["case_id"] in current_cases:
            case_bookmarks.append(row["case_id"])
        wrongbook.append({
            "kind": "case", "case_id": row["case_id"],
            "source_package_id": row["package_id"], "snapshot": snapshot,
            "stem": snapshot.get("original_number") or row["case_id"],
            "updated_at": row["updated_at"],
        })
    wrongbook.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"answers": answers, "wrongbook": wrongbook,
            "saved_choices": saved_choices, "case_bookmarks": case_bookmarks,
            "attempt_count": sum(row["attempt_count"] for row in rows)}


def _bookmark(conn: sqlite3.Connection, package_id: str, payload: dict) -> dict:
    path, subject = _package(conn, package_id)
    kind, action = payload.get("kind"), payload.get("action")
    if kind not in {"choice", "case"} or action not in {"add", "remove"}:
        raise ValueError("收藏类型或操作无效")
    now = datetime.now(timezone.utc).isoformat()
    if kind == "choice":
        if action == "add":
            if set(payload) != {"kind", "action", "qid"}:
                raise ValueError("选择题收藏字段无效")
            question = next((q for q in _questions(path) if q.get("id") == payload["qid"]), None)
            if question is None:
                raise ValueError("选择题不存在")
            key = _question_key(question)
            snapshot = json.dumps(_snapshot(path, question), ensure_ascii=False)
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                conn.execute("""INSERT INTO questions(subject,question_key,snapshot,last_package_id,last_qid,updated_at)
                             VALUES(?,?,?,?,?,?) ON CONFLICT(subject,question_key) DO UPDATE SET
                             snapshot=excluded.snapshot,last_package_id=excluded.last_package_id,
                             last_qid=excluded.last_qid,updated_at=excluded.updated_at""",
                             (subject, key, snapshot, package_id, question["id"], now))
                conn.execute("""INSERT INTO choice_bookmarks(subject,question_key,saved,dismissed,updated_at)
                             VALUES(?,?,1,0,?) ON CONFLICT(subject,question_key) DO UPDATE SET
                             saved=1,dismissed=0,updated_at=excluded.updated_at""", (subject, key, now))
        else:
            if set(payload) == {"kind", "action", "qid"}:
                question = next((q for q in _questions(path) if q.get("id") == payload["qid"]), None)
                if question is None:
                    raise ValueError("选择题不存在")
                key = _question_key(question)
            elif set(payload) == {"kind", "action", "question_key"} and re.fullmatch(
                    r"[a-f0-9]{64}", str(payload["question_key"])):
                key = payload["question_key"]
            else:
                raise ValueError("选择题移除字段无效")
            if not conn.execute("SELECT 1 FROM questions WHERE subject=? AND question_key=?",
                                (subject, key)).fetchone():
                raise ValueError("错题不存在")
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                conn.execute("""INSERT INTO choice_bookmarks(subject,question_key,saved,dismissed,updated_at)
                             VALUES(?,?,0,1,?) ON CONFLICT(subject,question_key) DO UPDATE SET
                             saved=0,dismissed=1,updated_at=excluded.updated_at""", (subject, key, now))
    elif action == "add":
        if set(payload) != {"kind", "action", "case_id"}:
            raise ValueError("案例收藏字段无效")
        case = next((c for c in _cases(path) if c.get("id") == payload["case_id"]), None)
        if case is None:
            raise ValueError("案例题不存在")
        snapshot = json.dumps(_case_bookmark_snapshot(path, case), ensure_ascii=False)
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            conn.execute("""INSERT INTO case_bookmarks(subject,package_id,case_id,snapshot,updated_at)
                         VALUES(?,?,?,?,?) ON CONFLICT(package_id,case_id) DO UPDATE SET
                         snapshot=excluded.snapshot,updated_at=excluded.updated_at""",
                         (subject, package_id, case["id"], snapshot, now))
    else:
        if set(payload) not in ({"kind", "action", "case_id"},
                                {"kind", "action", "case_id", "source_package_id"}):
            raise ValueError("案例移除字段无效")
        source_id = payload.get("source_package_id") or package_id
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{16}", source_id):
            raise ValueError("案例来源无效")
        row = conn.execute("SELECT 1 FROM case_bookmarks WHERE subject=? AND package_id=? AND case_id=?",
                           (subject, source_id, payload["case_id"])).fetchone()
        if row is None:
            raise ValueError("案例收藏不存在")
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            conn.execute("DELETE FROM case_bookmarks WHERE subject=? AND package_id=? AND case_id=?",
                         (subject, source_id, payload["case_id"]))
    return _progress(conn, package_id)


def _answer(conn: sqlite3.Connection, package_id: str, payload: dict) -> dict:
    path, subject = _package(conn, package_id)
    qid, picked = payload.get("qid"), payload.get("picked")
    if not isinstance(qid, str) or not isinstance(picked, list) or not picked:
        raise ValueError("qid 与非空 picked 数组必填")
    question = next((q for q in _questions(path) if q.get("id") == qid), None)
    if question is None:
        raise ValueError("题目不存在")
    labels = [o.get("label") for o in question.get("options", [])]
    if any(not isinstance(p, str) or p not in labels for p in picked) or len(set(picked)) != len(picked):
        raise ValueError("选项无效或重复")
    right = [o["label"] for o in question["options"] if o.get("is_correct") is True]
    if not right:
        raise ValueError("题目不可作答")
    correct = sorted(picked) == sorted(right)
    key = _question_key(question)
    snapshot = _snapshot(path, question)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    previous = conn.execute("SELECT wrong_count,streak,mastered,attempt_count FROM questions "
                            "WHERE subject=? AND question_key=?", (subject, key)).fetchone()
    wrong_count = (previous["wrong_count"] if previous else 0) + (not correct)
    streak = (previous["streak"] if previous else 0) + 1 if correct and wrong_count else 0
    mastered = int(streak >= 3) if wrong_count else 0
    with conn:
        conn.execute("INSERT INTO attempts(subject,question_key,package_id,qid,picked,correct,created_at) "
                     "VALUES(?,?,?,?,?,?,?)", (subject, key, package_id, qid, json.dumps(picked), int(correct), now))
        conn.execute("""INSERT INTO questions(subject,question_key,snapshot,last_package_id,last_qid,
                     attempt_count,wrong_count,streak,mastered,last_correct,last_picked,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(subject,question_key) DO UPDATE SET
                     snapshot=excluded.snapshot,last_package_id=excluded.last_package_id,
                     last_qid=excluded.last_qid,attempt_count=excluded.attempt_count,
                     wrong_count=excluded.wrong_count,streak=excluded.streak,mastered=excluded.mastered,
                     last_correct=excluded.last_correct,last_picked=excluded.last_picked,
                     updated_at=excluded.updated_at""",
                     (subject, key, json.dumps(snapshot, ensure_ascii=False), package_id, qid,
                      (previous["attempt_count"] if previous else 0) + 1, wrong_count, streak,
                      mastered, int(correct), json.dumps(picked), now))
        if not correct:
            conn.execute("""INSERT INTO choice_bookmarks(subject,question_key,saved,dismissed,updated_at)
                         VALUES(?,?,0,0,?) ON CONFLICT(subject,question_key) DO UPDATE SET
                         dismissed=0,updated_at=excluded.updated_at""", (subject, key, now))
    return {"correct": correct, "right": right, **_progress(conn, package_id)}


def collect_mistake(library: Path, package: Path, qid: str, picked: list[str] | None = None) -> str:
    """Collect an Agent-structured question without inventing a learner attempt."""
    package_id, subject = register(library, package)
    with _db(library) as conn:
        path, _ = _package(conn, package_id)
        if conn.execute("SELECT 1 FROM collected_mistakes WHERE package_id=? AND qid=?",
                        (package_id, qid)).fetchone():
            return package_id
        question = next((q for q in _questions(path) if q.get("id") == qid), None)
        if question is None:
            raise ValueError("待收录题目不存在")
        if picked:
            labels = {o.get("label") for o in question.get("options", [])}
            if len(picked) != len(set(picked)) or any(label not in labels for label in picked):
                raise ValueError("照片识别的作答选项无效")
            right = {o["label"] for o in question["options"] if o.get("is_correct") is True}
            if set(picked) == right:
                raise ValueError("给定作答与正确答案相同；不能作为错题收录")
            _answer(conn, package_id, {"qid": qid, "picked": picked})
            with conn:
                conn.execute("INSERT INTO collected_mistakes(package_id,qid) VALUES(?,?)", (package_id, qid))
            return package_id
        key = _question_key(question)
        snapshot = json.dumps(_snapshot(path, question), ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute("""INSERT INTO questions(subject,question_key,snapshot,last_package_id,last_qid,
                         wrong_count,streak,mastered,last_correct,last_picked,updated_at)
                         VALUES(?,?,?,?,?,1,0,0,NULL,'[]',?)
                         ON CONFLICT(subject,question_key) DO UPDATE SET
                         snapshot=excluded.snapshot,last_package_id=excluded.last_package_id,
                         last_qid=excluded.last_qid,wrong_count=questions.wrong_count+1,
                         streak=0,mastered=0,last_correct=NULL,last_picked='[]',updated_at=excluded.updated_at""",
                         (subject, key, snapshot, package_id, qid, now))
            conn.execute("""INSERT INTO choice_bookmarks(subject,question_key,saved,dismissed,updated_at)
                         VALUES(?,?,0,0,?) ON CONFLICT(subject,question_key) DO UPDATE SET
                         dismissed=0,updated_at=excluded.updated_at""", (subject, key, now))
            conn.execute("INSERT INTO collected_mistakes(package_id,qid) VALUES(?,?)", (package_id, qid))
        return package_id


def make_handler(library: Path, port: int):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value: dict, status: int = 200) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _send_file(self, file: Path, mime: str, *, head_only: bool = False) -> None:
            """Stream package assets and support the single byte range mobile PDF viewers request."""
            size = file.stat().st_size
            start, end, status = 0, max(size - 1, 0), 200
            raw_range = self.headers.get("Range")
            if raw_range:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", raw_range.strip())
                if not match or size == 0 or (not match.group(1) and not match.group(2)):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if match.group(1):
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else size - 1
                else:
                    length = int(match.group(2))
                    start, end = max(size - length, 0), size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end, status = min(end, size - 1), 206
            length = end - start + 1 if size else 0
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if mime == "application/pdf":
                self.send_header("Content-Disposition", f'inline; filename="{quote(file.name)}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if head_only or not length:
                return
            remaining = length
            with file.open("rb") as source:
                source.seek(start)
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _package_web_file(self, path: str) -> Path:
            parts = path.strip("/").split("/")
            if len(parts) < 4 or parts[0] != "packages" or parts[2] != "web":
                raise ValueError("页面不存在")
            with _db(library) as conn:
                package, _ = _package(conn, parts[1])
            web = (package / "web").resolve()
            file = web.joinpath(*parts[3:]).resolve()
            if not file.is_relative_to(web) or not file.is_file() or file.is_symlink():
                raise ValueError("资源不存在")
            return file

        def do_HEAD(self) -> None:
            try:
                file = self._package_web_file(unquote(urlsplit(self.path).path))
                self._send_file(file, mimetypes.guess_type(file.name)[0] or "application/octet-stream", head_only=True)
            except (ValueError, OSError, sqlite3.Error):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def do_GET(self) -> None:
            path = unquote(urlsplit(self.path).path)
            try:
                if path == "/api/health":
                    self._json({"status": "ok", "library_id": _library_id(library),
                                "capabilities": ["case-progress-v1", "wrongbook-snapshot-v1", "mixed-wrongbook-v1", "asset-range-v1"]})
                    return
                with _db(library) as conn:
                    if path == "/":
                        rows = conn.execute("SELECT id,path,subject FROM packages ORDER BY created_at DESC").fetchall()
                        links = "".join(f'<li><a href="/packages/{row["id"]}/web/index.html">'
                                        f'{html.escape(Path(row["path"]).name)}</a> · '
                                        f'{html.escape(row["subject"])}</li>' for row in rows)
                        page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>快考通本地学习库</title>' \
                               '<h1>快考通本地学习库</h1><ul>' + links + '</ul></html>'
                        self._send(200, page.encode(), "text/html; charset=utf-8")
                        return
                    parts = path.strip("/").split("/")
                    if len(parts) == 5 and parts[:2] == ["api", "packages"] and parts[3:] == ["cases", "progress"]:
                        self._json(_case_progress(conn, parts[2]))
                        return
                    if len(parts) == 4 and parts[:2] == ["api", "packages"] and parts[3] == "progress":
                        self._json(_progress(conn, parts[2]))
                        return
                    if len(parts) >= 4 and parts[0] == "packages" and parts[2] == "web":
                        file = self._package_web_file(path)
                        mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                        self._send_file(file, mime)
                        return
                    if len(parts) == 3 and parts[0] == "history" and len(parts[2]) == 64:
                        row = conn.execute("SELECT snapshot,wrong_count,streak,last_package_id FROM questions "
                                           "WHERE subject=? AND question_key=?", (parts[1], parts[2])).fetchone()
                        if row is None:
                            raise ValueError("历史题目不存在")
                        q = json.loads(row["snapshot"])
                        options = "".join('<li>' + html.escape(str(o.get("label"))) + ' · ' +
                                          html.escape(str(o.get("text"))) +
                                          (' ✓' if o.get("is_correct") else '') + '</li>' for o in q["options"])
                        knowledge = "".join('<h3>' + html.escape(str(c.get("title"))) + '</h3><p>' +
                                            html.escape(str(c.get("one_liner"))) + '</p><p>' +
                                            html.escape(str(c.get("summary"))) + '</p>' for c in q.get("concepts", []))
                        images = "".join('<img style="max-width:100%" src="/packages/' +
                                         html.escape(row["last_package_id"]) + '/web/' +
                                         html.escape(asset, quote=True) + '">' for asset in q.get("images", []))
                        page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>历史错题</title>'
                                '<style>body{max-width:800px;margin:40px auto;padding:20px;font:18px/1.7 system-ui}</style>'
                                '<h1>历史错题</h1><p>' + html.escape(q["stem"]) + '</p>' + images + '<ul>' + options + '</ul><h2>解析</h2><p>' +
                                html.escape(q["explanation"]) + '</p><h2>相关知识点</h2>' + knowledge +
                                '<p>累计答错 ' + str(row["wrong_count"]) +
                                ' 次 · 连续答对 ' + str(row["streak"]) + ' 次</p><a href="/">返回学习库</a></html>')
                        self._send(200, page.encode(), "text/html; charset=utf-8")
                        return
                raise ValueError("页面不存在")
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 404)

        def do_POST(self) -> None:
            path = unquote(urlsplit(self.path).path)
            parts = path.strip("/").split("/")
            is_case = len(parts) == 5 and parts[:2] == ["api", "packages"] and parts[3:] == ["cases", "progress"]
            is_answer = len(parts) == 4 and parts[:2] == ["api", "packages"] and parts[3] == "answer"
            is_bookmark = len(parts) == 4 and parts[:2] == ["api", "packages"] and parts[3] == "wrongbook"
            if not (is_case or is_answer or is_bookmark):
                self._json({"error": "接口不存在"}, 404)
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{port}":
                self._json({"error": "来源不允许"}, 403)
                return
            if self.headers.get_content_type() != "application/json":
                self._json({"error": "只接受 JSON"}, 415)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= (131_072 if is_case else 16_384):
                    raise ValueError("请求大小无效")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是对象")
                with _db(library) as conn:
                    operation = _save_case_progress if is_case else _bookmark if is_bookmark else _answer
                    result = operation(conn, parts[2], payload)
                self._json(result)
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="快考通离线学习库；只监听本机")
    parser.add_argument("--library", type=Path, default=Path.home() / ".quick-pass-study")
    parser.add_argument("--port", type=int, default=8766)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    open_package = commands.add_parser("open", help="注册学习包并自动启动或复用本地学习库")
    open_package.add_argument("package", type=Path)
    add = commands.add_parser("register")
    add.add_argument("package", type=Path)
    collect = commands.add_parser("collect")
    collect.add_argument("package", type=Path)
    collect.add_argument("--qid", required=True)
    collect.add_argument("--picked", action="append", default=[])
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port 必须是 1..65535")
    if args.command == "register":
        package_id, _ = register(args.library, args.package)
        print(package_url(package_id, args.port))
    elif args.command == "open":
        package_id, _ = register(args.library, args.package)
        ensure_server(args.library, args.port, require_cases=bool(_cases(args.package)),
                      require_wrongbook_details=True, require_asset_ranges=True)
        print(package_url(package_id, args.port))
    elif args.command == "collect":
        package_id = collect_mistake(args.library, args.package, args.qid, args.picked or None)
        ensure_server(args.library, args.port, require_wrongbook_details=True, require_asset_ranges=True)
        print(f"已收录错题：{package_url(package_id, args.port)}")
    else:
        with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.library, args.port)) as server:
            print(f"本地学习库：http://127.0.0.1:{args.port}/", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()
