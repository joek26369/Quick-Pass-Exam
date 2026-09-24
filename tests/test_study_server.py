"""Persistent offline study state across regenerated packages and Agent intake."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import study_server
from study_server import _answer, _bookmark, _db, _progress, collect_mistake, ensure_server, make_handler, register


def _package(root: Path, name: str, qid: str, *, subject: str = "ruankao-xitixiangmu",
             stem: str = "CPI 如何计算？") -> Path:
    package = root / name
    (package / "data").mkdir(parents=True)
    (package / "web").mkdir()
    (package / "web/index.html").write_text("<h1>学习包</h1>", encoding="utf-8")
    (package / "manifest.json").write_text(json.dumps({"profile": subject}), encoding="utf-8")
    (package / "data/questions.json").write_text(json.dumps([{
        "id": qid, "question_zh": stem, "concept_ids": ["c1"], "explanation": "CPI=EV/AC。",
        "options": [{"label": "A", "text": "EV/AC", "is_correct": True},
                    {"label": "B", "text": "AC/EV", "is_correct": False}],
    }], ensure_ascii=False), encoding="utf-8")
    (package / "data/concepts.json").write_text(json.dumps([{
        "id": "c1", "title": "成本绩效指数", "one_liner": "衡量成本效率。",
        "cornell_note": {"summary": "EV 除以 AC。"},
    }], ensure_ascii=False), encoding="utf-8")
    return package


def test_attempts_and_wrongbook_survive_restart_and_follow_same_question_into_new_package(tmp_path):
    library = tmp_path / "library"
    first, second = _package(tmp_path, "first", "old-id"), _package(tmp_path, "second", "new-id")
    first_id, _ = register(library, first)
    second_id, _ = register(library, second)
    with _db(library) as conn:
        result = _answer(conn, first_id, {"qid": "old-id", "picked": ["B"]})
        assert not result["correct"]
    with _db(library) as conn:  # reopened SQLite connection simulates server restart
        saved = _progress(conn, second_id)
        assert saved["answers"]["new-id"]["picked"] == ["B"]
        assert saved["wrongbook"][0]["qid"] == "new-id"
        for _ in range(3):
            _answer(conn, second_id, {"qid": "new-id", "picked": ["A"]})
        final = _progress(conn, first_id)
        assert final["answers"]["old-id"]["attempt_count"] == 4
        assert final["answers"]["old-id"]["wrong_count"] == 1
        assert final["wrongbook"] == []  # copied WebApp rule: 3 correct reviews mark mastered


def test_other_package_wrongbook_remains_visible_and_agent_photo_collection_has_no_fake_attempt(tmp_path):
    library = tmp_path / "library"
    photo = _package(tmp_path, "photo", "photo-q")
    (photo / "data/methods.json").write_text(json.dumps([{
        "id": "method-cpi", "title": "CPI 计算方法", "concept_ids": ["c1"]
    }], ensure_ascii=False), encoding="utf-8")
    other = _package(tmp_path, "other", "other-q", stem="另一个题目")
    photo_id = collect_mistake(library, photo, "photo-q")
    assert collect_mistake(library, photo, "photo-q") == photo_id
    other_id, _ = register(library, other)
    with _db(library) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert _progress(conn, photo_id)["answers"] == {}
        wrong = _progress(conn, other_id)["wrongbook"]
        assert len(wrong) == 1 and wrong[0]["qid"] is None
        assert wrong[0]["wrong_count"] == 1
        assert wrong[0]["stem"] == "CPI 如何计算？"
        assert wrong[0]["history_url"].startswith("/history/")
        assert wrong[0]["source_package_id"] == photo_id
        assert wrong[0]["snapshot"]["options"][0]["text"] == "EV/AC"
        assert wrong[0]["snapshot"]["methods"] == [{"id": "method-cpi", "title": "CPI 计算方法"}]
        snapshot = json.loads(conn.execute("SELECT snapshot FROM questions").fetchone()[0])
        assert snapshot["concepts"][0]["summary"] == "EV 除以 AC。"


def test_manual_choice_and_case_bookmarks_share_wrongbook_and_can_be_removed(tmp_path):
    library = tmp_path / "library"
    first = _package(tmp_path, "first", "q1")
    second = _package(tmp_path, "second", "q2", stem="另一道题")
    (first / "data/cases.json").write_text(json.dumps([{
        "id": "case1", "original_number": "案例一", "scenario": "共享背景",
        "sub_questions": [{"id": "case1-q1", "original_number": "问题一",
                           "question": "计算 CPI", "concept_ids": ["c1"], "method_ids": ["m1"]}],
    }], ensure_ascii=False), encoding="utf-8")
    (first / "data/methods.json").write_text(json.dumps([{
        "id": "m1", "title": "CPI 计算方法", "concept_ids": ["c1"]
    }], ensure_ascii=False), encoding="utf-8")
    first_id, _ = register(library, first)
    second_id, _ = register(library, second)
    with _db(library) as conn:
        saved = _bookmark(conn, first_id, {"kind": "choice", "action": "add", "qid": "q1"})
        assert saved["saved_choices"] == ["q1"]
        assert [(x["kind"], x["wrong_count"]) for x in saved["wrongbook"]] == [("choice", 0)]
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0

        saved = _bookmark(conn, first_id, {"kind": "case", "action": "add", "case_id": "case1"})
        assert saved["case_bookmarks"] == ["case1"]
        assert {x["kind"] for x in saved["wrongbook"]} == {"choice", "case"}
        case_entry = next(x for x in _progress(conn, second_id)["wrongbook"] if x["kind"] == "case")
        assert case_entry["snapshot"]["scenario"] == "共享背景"
        assert case_entry["snapshot"]["sub_questions"][0]["question"] == "计算 CPI"
        assert case_entry["snapshot"]["methods"] == [{"id": "m1", "title": "CPI 计算方法"}]

        _bookmark(conn, second_id, {"kind": "case", "action": "remove",
                                    "case_id": "case1", "source_package_id": first_id})
        assert all(x["kind"] != "case" for x in _progress(conn, first_id)["wrongbook"])
        choice_key = next(x["question_key"] for x in _progress(conn, second_id)["wrongbook"])
        _bookmark(conn, second_id, {"kind": "choice", "action": "remove", "question_key": choice_key})
        assert _progress(conn, first_id)["wrongbook"] == []
        assert not _answer(conn, first_id, {"qid": "q1", "picked": ["B"]})["correct"]
        assert [x["kind"] for x in _progress(conn, first_id)["wrongbook"]] == ["choice"]


def test_collected_mistake_keeps_rendered_source_page_for_history(tmp_path):
    library = tmp_path / "library"
    package = _package(tmp_path, "scanned", "scan-q")
    asset = "assets/content/source-page-2.png"
    image = package / "web" / asset
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    (package / "web/question-assets.json").write_text(
        json.dumps({"scan-q": {"diagram_assets": [], "source_page_asset": asset}}), encoding="utf-8"
    )
    package_id = collect_mistake(library, package, "scan-q")
    with _db(library) as conn:
        snapshot = json.loads(conn.execute("SELECT snapshot FROM questions").fetchone()[0])
        assert snapshot["images"] == [asset]
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(library, 0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with _db(library) as conn:
            history_url = _progress(conn, package_id)["wrongbook"][0]["history_url"]
        with urlopen(f"http://127.0.0.1:{server.server_port}{history_url}") as response:
            assert asset.encode() in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_answers_and_correct_photo_mark_are_rejected_without_writing(tmp_path):
    library = tmp_path / "library"
    package = _package(tmp_path, "first", "q1")
    package_id, _ = register(library, package)
    with _db(library) as conn:
        with pytest.raises(ValueError, match="选项无效"):
            _answer(conn, package_id, {"qid": "q1", "picked": ["Z"]})
    with pytest.raises(ValueError, match="正确答案相同"):
        collect_mistake(library, package, "q1", ["A"])
    with _db(library) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0


def test_loopback_http_serves_registered_package_and_rejects_cross_origin_post(tmp_path):
    library = tmp_path / "library"
    package = _package(tmp_path, "first", "q1")
    asset = package / "web/assets/content/lesson.pdf"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"%PDF-mobile-range-test")
    package_id, _ = register(library, package)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(library, 0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + f"/packages/{package_id}/web/index.html") as response:
            assert response.read() == b"<h1>\xe5\xad\xa6\xe4\xb9\xa0\xe5\x8c\x85</h1>"
        asset_url = base + f"/packages/{package_id}/web/assets/content/lesson.pdf"
        with urlopen(Request(asset_url, method="HEAD")) as response:
            assert response.status == 200
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.headers["Content-Length"] == str(len(asset.read_bytes()))
            assert response.read() == b""
        with urlopen(Request(asset_url, headers={"Range": "bytes=5-10"})) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes 5-10/{len(asset.read_bytes())}"
            assert response.read() == asset.read_bytes()[5:11]
        with pytest.raises(HTTPError) as range_error:
            urlopen(Request(asset_url, headers={"Range": "bytes=999-"}))
        assert range_error.value.code == 416
        with urlopen(base + f"/api/packages/{package_id}/progress") as response:
            assert json.load(response)["wrongbook"] == []
        request = Request(base + f"/api/packages/{package_id}/answer",
                          data=b'{"qid":"q1","picked":["B"]}', method="POST",
                          headers={"Content-Type": "application/json", "Origin": "https://other.test"})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
        with urlopen(base + f"/api/packages/{package_id}/progress") as response:
            assert json.load(response)["wrongbook"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_generated_package_open_reuses_library_and_returns_live_url(tmp_path, monkeypatch, capsys):
    import cli

    library = tmp_path / "library"
    package = _package(tmp_path, "first", "q1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(library, 0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert ensure_server(library, server.server_port) is False
        monkeypatch.setattr(cli, "generate_package", lambda *args, **kwargs: package)
        monkeypatch.setattr(sys, "argv", ["cli.py", "--input", str(tmp_path / "input.json"),
                                      "--output", str(package), "--agent-content", "--open",
                                      "--library", str(library), "--port", str(server.server_port)])
        # The normal CLI refuses existing outputs before generation; use a fresh
        # output name while the generator stub returns the prepared package.
        sys.argv[sys.argv.index("--output") + 1] = str(tmp_path / "new-output")
        assert cli.main() == 0
        url = capsys.readouterr().out.strip().splitlines()[-1]
        assert url.startswith(f"http://127.0.0.1:{server.server_port}/packages/")
        with urlopen(url) as response:
            assert response.status == 200
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/health") as response:
            assert json.load(response)["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_open_rejects_port_serving_another_library(tmp_path):
    first, second = tmp_path / "first-library", tmp_path / "second-library"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(first, 0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(RuntimeError, match="端口.*占用"):
            ensure_server(second, server.server_port)
        assert not (second / "learning.sqlite3").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_open_starts_library_once_and_reuses_it(tmp_path, monkeypatch):
    library = tmp_path / "library"
    launched = []
    popen = study_server.subprocess.Popen

    def capture(*args, **kwargs):
        process = popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(study_server.subprocess, "Popen", capture)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    try:
        assert ensure_server(library, port) is True
        assert ensure_server(library, port) is False
        assert len(launched) == 1
        with urlopen(f"http://127.0.0.1:{port}/api/health") as response:
            assert json.load(response)["status"] == "ok"
    finally:
        for process in launched:
            process.terminate()
            process.wait(timeout=3)
