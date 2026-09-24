#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 2: LLM 考点分类与概念归属

把 Phase 1 产出的 exam_point_summary 批量喂给 LLM，
一次性完成领域分类、章节映射和概念归属。
替代原 Phase 2-3 的 embedding+keyword 匹配。

输入：Phase 1 的 exam_point_summary 列表
输出：每题 → domain + chapter + concept_id + concept_title
"""
from __future__ import annotations

import json
import os
import hashlib
from typing import Any


SYSTEM_PROMPT = """你是一位{exam_subject}认证讲师。

任务：根据{exam_subject}考试大纲，对给定的考点摘要进行精确的领域划分、章节映射和概念提取的梳理。
-领域归类：标明该题属于哪个大的考试领域（从下方考试大纲领域中选取）。
-章节映射：对应到{exam_subject}官方教材的具体章节名称。
-概念提取：列出该题考核的核心技术概念（必须是该领域的专有名词）。

## 判断原则
- 考点的"主题"是主语，不是被提到的对象
- 一个考点归属到最核心的概念，不要因为顺带提到其他概念就归错
- concept_id 使用英文 snake_case
- 同一概念的考点应归到同一个 concept_id
<<SYLLABUS_BLOCK>>

## 输出 JSON 格式
{
  "assignments": [
    {
      "source_question": "Q0002",
      "domain": "考试领域名称",
      "chapter": "章节名称（中文）",
      "concept_id": "english_snake_case",
      "concept_title": "概念中文标题",
      "reason": "一句话说明为什么归属到这个概念"
    }
  ]
}

注意：
- domain 必须从{exam_domains}中选取
- chapter 为该领域下的具体知识点分类（中文）
- concept_id 为英文 snake_case，体现概念核心语义
- concept_title 为概念的中文标题
- reason 用一句话说明为什么归属到这个概念
- 只输出 JSON，不要输出其他内容"""


class Phase2Classifier:
    """Phase 2: LLM 考点分类与概念归属"""

    def __init__(self, llm_client: Any = None, exam_subject: str = "", exam_domains: str = "",
                 syllabus_tree: list[dict] | None = None):
        self.llm = llm_client
        self.exam_subject = exam_subject or ""
        self.exam_domains = exam_domains or ""
        self.syllabus_tree = syllabus_tree or []

    def classify(self, summaries: list[dict], batch_size: int = 10, empty_retry: int = 2) -> list[dict]:
        """对考点摘要列表做分类与概念归属。分批调用，空批次自动重试。"""
        if not self.llm or not summaries:
            return []

        all_assignments = []
        total_batches = (len(summaries) - 1) // batch_size + 1
        for i in range(0, len(summaries), batch_size):
            batch = summaries[i:i + batch_size]
            user_prompt = self._build_user_prompt(batch)
            system_prompt = self._build_system_prompt()

            batch_assignments = []
            for attempt in range(1 + empty_retry):
                from phase4_content_generator import call_with_backoff, LLMBalanceError
                try:
                    data = call_with_backoff(
                        self.llm.chat_json,
                        system_prompt,
                        user_prompt,
                        temperature=0.3,
                        timeout=120,
                    )
                except LLMBalanceError:
                    raise

                batch_assignments = data.get("assignments", [])
                if batch_assignments:
                    break
                if attempt < empty_retry:
                    print(f"  ⚠ 批次 {i//batch_size+1}/{total_batches} 返回空，重试 {attempt+1}/{empty_retry}")

            if not batch_assignments:
                print(f"  ⚠ 批次 {i//batch_size+1}/{total_batches} 重试后仍为空 (batch={len(batch)}题)")
            else:
                print(f"  批次 {i//batch_size+1}/{total_batches}: {len(batch_assignments)} 个归属")
            all_assignments.extend(batch_assignments)

        if not all_assignments:
            print("  ⚠ Phase 2 全部分类失败")
            return []

        return all_assignments

    def _build_system_prompt(self) -> str:
        prompt = SYSTEM_PROMPT
        prompt = prompt.replace("{exam_subject}", self.exam_subject + " ", 1) if self.exam_subject else prompt.replace("{exam_subject}", "", 1)
        # 第二个 {exam_subject}
        prompt = prompt.replace("{exam_subject}", self.exam_subject + " ", 1) if self.exam_subject else prompt.replace("{exam_subject}", "", 1)
        prompt = prompt.replace("{exam_domains}", self.exam_domains or "根据该考试的官方大纲领域", 2)
        # 考纲受控词表（A）：chapter/concept_title 必须从考纲章节树选取或派生
        if self.syllabus_tree:
            lines = []
            for d in self.syllabus_tree:
                # 两种历史格式：str "1.1 标题" 或 dict{chapter,sections[]}
                chs = "、".join(c if isinstance(c, str) else c.get("chapter", "")
                               for c in d.get("chapters", []) if c)
                lines.append(f"- {d.get('domain', '')}：{chs}" if chs else f"- {d.get('domain', '')}")
            block = ("\n## 考纲章节树（受控词表）\n"
                     "chapter 必须从下列章节中选取（或其下更细的知识点名称）；"
                     "concept_title 必须使用考纲中的标准术语（可以是章节名或其下知识点名），"
                     "禁止自造同义变体。多个考点同属一个知识点时必须归到同一个 concept_title。\n"
                     + "\n".join(lines))
            prompt = prompt.replace("<<SYLLABUS_BLOCK>>", block)
        else:
            prompt = prompt.replace("<<SYLLABUS_BLOCK>>", "")
        return prompt

    def _build_user_prompt(self, summaries: list[dict]) -> str:
        lines = [f"以下是为 {len(summaries)} 道题提取的考点摘要，请进行分类和概念归属：\n"]
        for s in summaries:
            qid = s.get("source_question", "")
            title = s.get("title", "")
            keywords = s.get("keywords", "")
            lines.append(f"{qid}\t{title}\t{keywords}")
        return "\n".join(lines)


def run_phase2(
    phase1_results: list[dict],
    llm_client: Any,
    exam_subject: str,
    exam_domains: str,
    cache_path: str = "data/index/phase2_assignments.json",
    syllabus_tree: list[dict] | None = None,
) -> list[dict]:
    """Phase 2 入口：从 Phase 1 结果跑分类。

    Args:
        phase1_results: Phase 1 的完整结果列表（每个含 exam_point_summary）
        llm_client: LLM 客户端
        exam_subject: 考试科目名称
        exam_domains: 考试大纲领域文本
        cache_path: 缓存文件路径
        syllabus_tree: 考纲章节树 [{domain, chapters[]}]（高质量模式受控词表）

    Returns:
        assignments 列表
    """
    # 检查缓存
    if os.path.exists(cache_path):
        print(f"  ⏭ Phase 2 使用缓存: {cache_path}")
        try:
            cached = json.load(open(cache_path, encoding="utf-8"))
            if isinstance(cached, list) and cached:
                return cached
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # 提取 exam_point_summary
    summaries = []
    for r in phase1_results:
        eps = r.get("exam_point_summary", {})
        if eps:
            summaries.append(eps)

    if not summaries:
        print("  ⚠ 无 exam_point_summary，跳过 Phase 2")
        return []

    print(f"  分类 {len(summaries)} 个考点摘要...")

    classifier = Phase2Classifier(
        llm_client=llm_client,
        exam_subject=exam_subject,
        exam_domains=exam_domains,
        syllabus_tree=syllabus_tree,
    )
    assignments = classifier.classify(summaries)

    # 过滤非法 concept_id
    valid = [a for a in assignments if a.get("concept_id") and a.get("source_question")]
    if len(valid) < len(assignments):
        print(f"  ⚠ 过滤 {len(assignments) - len(valid)} 个无效归属")

    # 保存缓存
    if valid:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(valid, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Phase 2 完成: {len(valid)} 个归属")

    return valid
