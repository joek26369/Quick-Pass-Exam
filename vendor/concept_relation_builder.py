"""
Phase 3.5: 概念关系构建器

一次 LLM 调用，为所有概念生成：
  - learning.level (1-3)
  - learning_relations.{prerequisites, next_concepts, related_concepts}
  - relationships[] (target + type + note)

产出同时驱动：
  - Obsidian Canvas (level 定坐标, prerequisites 画边)
  - 导出笔记中的"关联知识"和"学习路径"段
"""
from __future__ import annotations

from typing import Any

# 受控关系类型词表（与 quality_gates.py / obsidian_artifacts.py 对齐）
VALID_REL_TYPES = {"requires", "part_of", "contrasts_with", "used_by", "leads_to", "related"}

SYSTEM_PROMPT = """你是一位{exam_subject}知识体系架构师。你的任务是根据给定的概念列表，构建概念间的关系网络和学习路径。

## 输出格式要求

只返回一个 JSON 对象，含一个顶层键 "concepts"：

{
    "concepts": {
        "概念ID": {
            "level": 1,
            "prerequisites": ["前置概念ID"],
            "next_concepts": ["后续概念ID"],
            "related_concepts": ["关联概念ID"],
            "relationships": [
                {
                    "target": "目标概念ID",
                    "type": "requires|part_of|contrasts_with|used_by|leads_to|related",
                    "note": "一句话说明关系（20字以内）"
                }
            ]
        }
    }
}

## 关系类型说明
- requires: 学习本概念需要先掌握目标概念
- part_of: 本概念是目标概念的一部分
- contrasts_with: 本概念与目标概念容易混淆，需要对比
- used_by: 本概念被目标概念使用
- leads_to: 掌握本概念后自然进入目标概念
- related: 本概念与目标概念有关联但不属于以上类型

## 学习层级 (level)
- 1: 基础概念（入门必学）
- 2: 中级概念（需要基础前置）
- 3: 高级概念（需要多个中级前置）

## 硬性要求
- target / prerequisites / next_concepts / related_concepts 必须只使用输入中已有的概念 ID
- relationships.type 只能取受控词表中的值
- level 为 1-3 的整数
- 只返回 JSON，不要解释，不要 markdown 代码块
- 占位符（TODO/待补充）视为失败"""


class ConceptRelationBuilder:
    """概念关系构建器（一次 LLM 调用）"""

    def __init__(self, llm_client=None, exam_subject: str = ""):
        self.llm = llm_client
        self.exam_subject = exam_subject or ""

    def build(self, concepts: list[dict]) -> list[dict]:
        """为概念列表补充关系和学习路径信息。

        Args:
            concepts: Phase 3 产出的概念骨架列表

        Returns:
            补充了 relationships / learning / learning_relations 的概念列表（原地修改）
        """
        if not self.llm:
            return concepts
        if not concepts or len(concepts) < 2:
            # 单个概念无法构建关系，直接返回
            return concepts

        # 构建概念 ID → index 映射
        valid_ids = {c.get("id") for c in concepts if c.get("id")}
        if not valid_ids:
            return concepts

        # 构建 LLM prompt
        user_prompt = self._build_user_prompt(concepts)

        # 调用 LLM
        try:
            data = self.llm.chat_json(
                SYSTEM_PROMPT.replace("{exam_subject}", self.exam_subject + " ", 1) if self.exam_subject else SYSTEM_PROMPT.replace("{exam_subject}", "", 1),
                user_prompt, temperature=0.3, timeout=120
            )
        except Exception as e:
            print(f"  ⚠ 概念关系构建失败（{type(e).__name__}）")
            return concepts

        rel_data = data.get("concepts", {})
        if not rel_data:
            print("  ⚠ 概念关系构建失败（LLM 返回为空）")
            return concepts

        # 合并回概念列表
        for concept in concepts:
            cid = concept.get("id", "")
            if cid not in rel_data:
                continue

            rd = rel_data[cid]

            # learning.level
            level = rd.get("level", 2)
            if not isinstance(level, int) or level not in (1, 2, 3):
                level = 2
            concept["learning"] = concept.get("learning", {})
            concept["learning"]["level"] = level

            # learning_relations（过滤不存在的 ID）
            concept["learning_relations"] = {
                "prerequisites": self._filter_ids(rd.get("prerequisites", []), valid_ids),
                "next_concepts": self._filter_ids(rd.get("next_concepts", []), valid_ids),
                "related_concepts": self._filter_ids(rd.get("related_concepts", []), valid_ids),
            }

            # relationships（过滤非法 target 和非法 type）
            relationships = []
            for rel in rd.get("relationships", []):
                target = rel.get("target", "")
                rel_type = rel.get("type", "")
                if target in valid_ids and rel_type in VALID_REL_TYPES:
                    relationships.append({
                        "target": target,
                        "type": rel_type,
                        "note": rel.get("note", ""),
                    })
            concept["relationships"] = relationships

        return concepts

    def _filter_ids(self, ids: list, valid_ids: set) -> list[str]:
        """过滤掉不在 valid_ids 中的 ID，保持顺序去重。"""
        seen = set()
        result = []
        for cid in (ids or []):
            if cid in valid_ids and cid not in seen:
                seen.add(cid)
                result.append(cid)
        return result

    def _build_user_prompt(self, concepts: list[dict]) -> str:
        lines = ["## 概念列表（共 {} 个）\n".format(len(concepts))]
        for c in concepts:
            cid = c.get("id", "")
            title = c.get("title", cid)
            # knowledge_points may be list of KP-ID strings or list of dicts
            raw_kps = c.get("knowledge_points", [])
            kp_titles = []
            for kp in raw_kps:
                if isinstance(kp, dict):
                    kp_titles.append(kp.get("title", ""))
                elif isinstance(kp, str):
                    kp_titles.append(kp)
            kp_summary = "、".join(kp_titles[:4]) if kp_titles else "（无）"
            lines.append(f"- {cid}: {title}（知识点：{kp_summary}）")
        lines.append("\n请为以上概念构建关系网络和学习路径。")
        lines.append("每个概念都必须出现在输出中。")
        lines.append("relationships.target / prerequisites / next_concepts / related_concepts 只能使用上述列表中的概念 ID。")
        return "\n".join(lines)
