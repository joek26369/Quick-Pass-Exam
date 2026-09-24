import sys
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator import ContractError, validate_questions


def sample():
    return {"questions": [{"id": "q1", "question_zh": "测试题", "answer": "A",
                           "options": [{"label": "A", "text": "对", "is_correct": True},
                                       {"label": "B", "text": "错", "is_correct": False}]}]}


class GenerationContractTest(unittest.TestCase):
    def test_validate_questions_preserves_enriched_fields(self):
        payload = sample()
        payload["questions"][0]["memory_tips"] = ["保留我"]
        self.assertEqual(validate_questions(payload)[0]["memory_tips"], ["保留我"])

    def test_validate_questions_rejects_answer_disagreement(self):
        payload = sample()
        payload["questions"][0]["answer"] = "B"
        with self.assertRaisesRegex(ContractError, "答案字段"):
            validate_questions(payload)

    def test_validate_questions_rejects_duplicate_ids(self):
        payload = sample()
        payload["questions"].append(dict(payload["questions"][0]))
        with self.assertRaisesRegex(ContractError, "重复"):
            validate_questions(payload)

    def test_validate_questions_rejects_string_boolean(self):
        payload = sample()
        payload["questions"][0]["options"][0]["is_correct"] = "false"
        with self.assertRaisesRegex(ContractError, "JSON boolean"):
            validate_questions(payload)

    def test_validate_questions_rejects_answer_list(self):
        payload = sample()
        payload["questions"][0]["answer"] = ["A"]
        with self.assertRaisesRegex(ContractError, "answer 必须是字符串"):
            validate_questions(payload)

    def test_validate_questions_rejects_empty_option_text_and_conflicting_answer_fields(self):
        payload = sample()
        payload["questions"][0]["options"][0]["text"] = "  "
        with self.assertRaisesRegex(ContractError, "缺少非空文本"):
            validate_questions(payload)
        payload = sample()
        payload["questions"][0]["correct_answer"] = "A"
        payload["questions"][0]["answer"] = "B"
        with self.assertRaisesRegex(ContractError, "answer.*is_correct|不一致"):
            validate_questions(payload)

    def test_profile_path_is_not_accepted(self):
        from generator import _profile
        with self.assertRaisesRegex(ContractError, "非法 profile"):
            _profile("../../private")

    def test_mock_llm_chain_uses_real_module_signatures(self):
        from generator import generate_package
        import exam_point_extractor
        import phase2_classifier
        import concept_relation_builder
        import phase4_content_generator

        class Result:
            def to_dict(self):
                return {"question_id": "q1", "answer": "A", "memory_tips": ["口诀"],
                        "exam_point_summary": {"source_question": "q1", "title": "测试", "keywords": "测试"}}

        class Extractor:
            def __init__(self, *args, **kwargs): pass
            def extract_batch(self, questions): return [Result()]

        class Generator:
            def __init__(self, *args, **kwargs): pass
            def generate_batch(self, groups):
                return {"c1": type("C", (), {"to_dict": lambda self: {
                    "one_liner": "内容", "cornell_note": {
                        "pairs": [{"cue": "是什么？", "note": "这是内容。"}],
                        "summary": "小结", "pairing_status": "paired",
                    }}})()}
            def merge_into_concepts(self, concepts, contents):
                concepts[0].update(contents["c1"].to_dict())
                return concepts

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inp = root / "input.json"
            inp.write_text(json.dumps(sample(), ensure_ascii=False), encoding="utf-8")
            cfg = root / "config.json"
            cfg.write_text(json.dumps({"provider": "fake", "api_url": "https://example.invalid",
                                       "api_key_env": "QPE_TEST_KEY", "global": {"enabled": True},
                                       "stages": {"analyzer": {"model": "fake-model"}}}), encoding="utf-8")
            assignments = [{"source_question": "q1", "concept_id": "c1", "concept_title": "测试",
                            "domain": "领域", "chapter": "章节"}]
            with patch.dict("os.environ", {"QPE_TEST_KEY": "secret"}), \
                 patch.object(exam_point_extractor, "ExamPointExtractor", Extractor), \
                 patch.object(phase2_classifier, "run_phase2", return_value=assignments), \
                 patch.object(concept_relation_builder.ConceptRelationBuilder, "build", side_effect=lambda x: x), \
                 patch.object(phase4_content_generator, "ContentGenerator", Generator):
                out = generate_package(inp, root / "package", profile_name="ruankao-xitixiangmu", llm_config=cfg)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "llm")
            self.assertNotIn("secret", json.dumps(manifest))
            self.assertEqual(manifest["model"]["transport_retry_limit"], 2)
            self.assertEqual(manifest["usage"]["attempt_count"], 0)
            self.assertEqual(manifest["usage"]["scope"], "current_process_only")
            self.assertIn("reports/usage-attempts.json", manifest["files"])
            self.assertEqual(len(manifest["config_sha256"]), 64)
            self.assertEqual(json.loads((out / "data/questions.json").read_text())[0]["answer"], "A")

    def test_cli_masks_provider_exception_text(self):
        from cli import _safe_failure
        class LLMSecretError(Exception):
            __module__ = "llm_client"
        category, message = _safe_failure(LLMSecretError("Bearer secret provider body"))
        self.assertEqual(category, "PROVIDER")
        self.assertNotIn("secret", message)

    def test_generated_references_are_never_canonical(self):
        from generator import _isolate_generated_references
        questions = [{"id": "q1", "source_paper": "显式题库", "source_page": 3}]
        concepts = [{"id": "c1", "source_questions": ["q1"],
                     "references": ["模型声称的教材第99页"]}]
        _isolate_generated_references(questions, concepts)
        concept = concepts[0]
        self.assertNotIn("references", concept)
        self.assertEqual(concept["canonical_references"][0]["source_paper"], "显式题库")
        self.assertEqual(concept["unverified_generated_references"][0]["verification_status"],
                         "unverified_model_output")

    def test_generated_cornell_note_does_not_replace_or_duplicate_source_note(self):
        from generator import _questions_export
        source_note = {"cues": ["题库提示"], "notes": ["题库笔记"], "summary": "题库小结"}
        generated_note = {"cues": ["模型提示"], "notes": ["模型笔记"], "summary": "模型小结"}
        questions = [dict(sample()["questions"][0], cornell_note=source_note)]
        p1 = [{"question_id": "q1", "cornell_note": generated_note, "memory_tips": ["模型口诀"]}]
        exported = _questions_export(p1, questions, [])
        self.assertEqual(exported[0]["cornell_note"], source_note)
        self.assertEqual(exported[0]["generated_analysis"]["cornell_note"], generated_note)
        self.assertNotIn("memory_tips", exported[0])

    def test_client_accepts_valid_stage_url(self):
        from generator import _client
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"QPE_TEST_KEY": "secret"}):
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"api_key_env": "QPE_TEST_KEY", "stages": {"analyzer": {
                "api_url": "https://stage.example/v1", "model": "stage-model"}}}))
            client, meta = _client(path)
        self.assertEqual(client.api_url, "https://stage.example/v1/chat/completions")
        self.assertEqual(meta["api_url_host"], "stage.example")

    def test_client_rejects_invalid_url_and_plaintext_key(self):
        from generator import _client
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"QPE_TEST_KEY": "env"}):
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"api_key_env": "QPE_TEST_KEY", "api_url": "not-a-url",
                                        "model": "m"}))
            with self.assertRaisesRegex(ContractError, "http/https"):
                _client(path)
            path.write_text(json.dumps({"api_key_env": "QPE_TEST_KEY", "api_url": "https://example.test",
                                        "model": "m", "stages": {"analyzer": {"api_key": "file-secret"}}}))
            with self.assertRaisesRegex(ContractError, "禁止包含明文"):
                _client(path)

    def test_usage_summary_counts_events_and_unique_attempts_separately(self):
        from generator import _summarize_usage
        events = [
            {"call_id": "a", "attempt": 1, "status": "sent", "usage_source": "unknown"},
            {"call_id": "a", "attempt": 1, "status": "succeeded", "usage_source": "provider"},
            {"call_id": "b", "attempt": 1, "status": "sent", "usage_source": "unknown"},
            {"call_id": "b", "attempt": 1, "status": "failed", "usage_source": "unknown"},
        ]
        summary = _summarize_usage(events)
        self.assertEqual(summary["event_count"], 4)
        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["succeeded_count"], 1)
        self.assertEqual(summary["failed_count"], 1)
        self.assertTrue(summary["provider_usage_complete"])

    def test_real_generation_gate_requires_complete_cornell_pairs(self):
        from generator import _validate_package
        questions = [{"id": "q1", "concept_ids": ["c1"]}]
        base = {"id": "c1", "source_questions": ["q1"], "one_liner": "内容"}
        missing = _validate_package(questions, [dict(base)], require_cornell_pairs=True)
        self.assertIn("CORNELL_PAIRS_REQUIRED", {x["code"] for x in missing["findings"]})
        incomplete = dict(base, cornell_note={"pairs": [{"cue": "问题", "note": ""}]})
        report = _validate_package(questions, [incomplete], require_cornell_pairs=True)
        self.assertIn("CORNELL_PAIR_INCOMPLETE", {x["code"] for x in report["findings"]})
        for invalid in (None, 7, {"text": "伪答案"}):
            wrong_type = dict(base, cornell_note={"pairs": [{"cue": "问题", "note": invalid}]})
            report = _validate_package(questions, [wrong_type], require_cornell_pairs=True)
            self.assertIn("CORNELL_PAIR_INCOMPLETE", {x["code"] for x in report["findings"]})
        complete = dict(base, cornell_note={"pairs": [{"cue": "问题", "note": "答案"}]})
        self.assertEqual(_validate_package(questions, [complete], require_cornell_pairs=True)["status"], "passed")

    def test_fixture_gate_keeps_legacy_cornell_compatible(self):
        from generator import _validate_package
        questions = [{"id": "q1", "concept_ids": ["c1"]}]
        concepts = [{"id": "c1", "source_questions": ["q1"],
                     "cornell_note": {"cues": ["旧提示"], "notes": ["旧笔记"]}}]
        self.assertEqual(_validate_package(questions, concepts)["status"], "passed")

    def test_concept_shape_and_cornell_status_are_checked_before_rendering(self):
        from generator import _validate_package
        questions = [{"id": "q1", "concept_ids": ["c1"]}]
        concept = {
            "id": "c1", "source_questions": ["q1"], "one_liner": {"bad": "shape"},
            "tags": 1, "cornell_note": {
                "pairs": [{"cue": "问题", "note": "答案"}],
                "pairing_status": "unpaired", "summary": "小结",
            },
        }
        report = _validate_package(questions, [concept], require_cornell_pairs=True)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("CONCEPT_FIELD_TYPE", codes)
        self.assertIn("CONCEPT_LIST_TYPE", codes)
        self.assertIn("CORNELL_STATUS_CONFLICT", codes)


if __name__ == "__main__":
    unittest.main()
