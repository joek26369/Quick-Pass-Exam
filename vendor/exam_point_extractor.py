"""
Exam Point Extractor — Phase 1: 逐题 LLM 分析

职责：对每道题，用 LLM 做全面分析：
1. 翻译英文题目/选项为中文
2. 判断正确答案（不传题库答案，LLM 自行判断）
3. 提取核心考点
4. 逐选项分析（含场景/输出分析）
5. 记忆要点
6. 扩展知识
7. 康奈尔笔记
8. 考点摘要（供 Phase 2 分类用）

设计要点：
- 每题只调 1 次 LLM，prompt 只含英文原题 + 英文选项
- 不传中文翻译、原始解析、正确答案——LLM 自行判断
- 可缓存到 data/_exam_points/{qid}.json，断点续跑
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Prompt 设计（通用版，占位符运行时替换）
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个{exam_subject}考试的资深讲师。你的任务是逐选项分析选择题，提取考点，并完善答案解析。

如果输入的题目和选项为英文，请先将其翻译为中文（保留英文术语），翻译结果放在 question_translation 和 option_translations 字段中。

{
  "answer": "正确答案（如 A,D）",
  "question_translation": "题目中文翻译（保留英文术语）",
  "option_translations": [
    {"option": "A", "text_zh": "选项A的中文翻译"}
  ],
  "core_exam_points": [
    {
      "title": "考点标题（中文）",
      "body": "考点的详细阐述（中文，2-5个要点）"
    }
  ],
  "option_analyses": [
    {
      "option": "A",
      "is_correct": true,
      "analysis": "为什么正确/错误（中文），标注 ✅ 或 ❌，附详细正误原因。针对题目中给出的命令输出/执行场景做逐行分析（如题目贴了一段 SHOW PARAMETER 的输出，解释每行的含义）；如题目没有输出内容，则退化为对选项描述的提取分析",
      "quotes": ["从题目原文或【题库解析】中逐字摘录的支撑句（没有则留空数组）"]
    }
  ],
  "memory_tips": [
    "记忆要点（中文口诀或对比规律）"
  ],
  "knowledge_expansion": [
    {
      "topic": "扩展知识主题（中文）",
      "body": "扩展内容（中文）"
    }
  ],
  "cornell_note": {
    "cues": [
      "从核心考点提取的关键名词或疑问词（如'V$TABLESPACE 来源是什么？'）"
    ],
    "notes": [
      "从题目解析中逐字引用的要点，用分号分隔，核心术语用加粗标注"
    ],
    "summary": "包含核心结论 + 一句记忆口诀 + 一句易错点警告"
  },
  "quotes": ["全题最关键的题库解析原文句（1-3 句，逐字摘自【题库解析】，供笔记锚定校验）"],
  "exam_point_summary": {
    "title": "考点名称（对象 + 功能/特性的短标题）",
    "source_question": "题目编号",
    "keywords": "1-2 个最核心的技术术语或对象名称"
  },
  "is_calculation": false,
  "calc_solution": null,
  "is_methodology": false,
  "method_extract": null
}

注意：
- answer 必须准确，基于{standard_label}和考试标准
- is_calculation：本题是否涉及数值计算（如挣值分析 PV/EV/AC/CPI/SPI、三点估算、关键路径/总时差、概率决策、费用优化等）。纯概念/判断题填 false。
- calc_solution：仅当 is_calculation 为 true 时填写，否则填 null。结构：
  {{
    "method_name": "计算方法名称（如'挣值分析-CPI/SPI'、'三点估算'、'关键路径法'）",
    "steps": "解题步骤和公式（中文，含公式和代入过程）",
    "common_patterns": "此类计算题的常见命题方式和易错点（中文，2-4句）",
    "related_concepts": ["相关概念标准名"]
  }}
- method_name 命名（calc_solution/method_extract 通用）：优先用考试教程的标准方法名（如挣值分析、三点估算）；
  教程查无对应条目时才用通行学术名，禁止自造缩写或变体名；同一方法多题出现必须用同一名称。
  同一道大题拆出的多个小题（题干相同、各填一空）属于同一道计算题：method_name 必须完全一致，
  不得按空位/求解目标各起一个名（如"成本最小化"与"图解法求最优解"是同一道线性规划题，只能共用一个名）。
- is_methodology：本题是否涉及通用管理方法论/标准流程（如 WBS 分解方法、变更控制流程、风险应对策略、挣值管理流程、需求变更管理流程等）。这类方法论不绑定具体公式，而是描述一类管理活动的标准流程/原则/套路。纯概念记忆题填 false。
- method_extract：仅当 is_methodology 为 true 时填写，否则填 null。结构：
  {{
    "method_name": "方法论名称（如'WBS分解'、'变更控制流程'、'风险应对策略'）",
    "description": "该方法论的核心描述（中文，1-2句）",
    "application": "实际应用要点/规则/步骤（中文，如'自上而下分解，8/80规则，最底层为工作包'）",
    "related_concepts": ["相关概念标准名"]
  }}
- core_exam_points 帮助学习和理解本题相关知识点。考点标题提炼规则：
  可以从题干抓取主题；当题干没有明确主题时，先看所有选项，找出重复出现频率最高的关键技术词。
  再结合正确答案所属的知识领域，组合成一个"对象 + 功能/特性"的短标题。
  标题中不得包含选项编号或具体数值，只保留核心概念。
- option_analyses 必须覆盖所有选项
- quotes 字段：逐字摘录题目原文（题干、选项、命令输出）或【题库解析】中支撑该分析的原句；
  程序会校验 quote 是否真的出现在原文里，改写、意译、编造的引用会被剔除——必须逐字复制。
  解析要点属于你自己的推理、原文没有对应句子时，quotes 留空数组，不要硬凑。
- memory_tips 精炼的口诀或要点，帮助快速理解记忆
- knowledge_expansion 可选的相关知识延伸
- cornell_note：
  线索栏（cues）：必须从核心考点中提取关键名词或生成疑问词（如"是什么"、"在哪里"）
  主笔记区（notes）：逐字引用题目解析原文，只允许三点转换：（1）删除语气助词；（2）长段落拆为分号分隔的要点；（3）核心术语加粗。禁止意译和大幅缩写。
  底部总结（summary）：必须包含三个固定元素——（1）核心结论；（2）一个记忆口诀；（3）一句易错点警告。
- exam_point_summary 只提取本题最核心的考点摘要。title 提炼规则同 core_exam_points。
  示例：题目问某工具的配置和参数 → title="该工具的配置与参数", keywords="工具名"
- 只输出 JSON，不要输出其他内容"""


def build_user_prompt(question: dict) -> str:
    """构建单题的 user prompt：传题目 + 选项（zh-only 回退当 en 不存在）"""
    lines = []
    qid = question.get('id', '')
    q_en = question.get('question_en', '')
    q_zh = question.get('question_zh', '')
    q_text = q_en or q_zh  # ponytail: zh-only exams (ruankao_web)
    lines.append(f"[Question ID: {qid}]")
    lines.append(f"Question: {q_text}")
    lines.append("\nOptions:")
    for opt in question.get("options", []):
        label = opt.get("label", "")
        text_en = opt.get("text_en", "")
        text = opt.get("text", "")  # ponytail: single-text format
        opt_text = text_en or text  # zh-only 回退
        lines.append(f"  {label}. {opt_text}")
    explanation = (question.get("explanation") or "").strip()
    if explanation:
        lines.append("\n【题库解析】")
        lines.append(explanation)
        lines.append("（quotes 必须逐字摘自题干、选项或以上题库解析原文）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 答案校验
# ---------------------------------------------------------------------------

def _normalize_answer(answer_str: str) -> set:
    """将答案字符串规范化为大写字母集合。"""
    return set(re.findall(r'[A-F]', (answer_str or "").upper()))


def check_answer_mismatch(
    llm_answer: str,
    bank_answer: str,
) -> tuple[bool, str]:
    """比对 LLM 答案和题库答案。

    Returns:
        (is_mismatch, error_message)
    """
    bank_letters = _normalize_answer(bank_answer)
    llm_letters = _normalize_answer(llm_answer)

    if bank_letters and llm_letters and bank_letters != llm_letters:
        return True, f"答案不一致: LLM={sorted(llm_letters)}, 题库={sorted(bank_letters)}"
    return False, ""


# ---------------------------------------------------------------------------
# 提取器
# ---------------------------------------------------------------------------

class ExamPointExtractor:
    """考点提取器

    用法：
        extractor = ExamPointExtractor(llm_client=client, exam_subject="Oracle OCP 1Z0-082")
        result = extractor.extract(question_dict)
    """

    def __init__(
        self,
        llm_client: Any = None,
        cache_dir: str = "data/_exam_points",
        exam_subject: str = "",
        standard_label: str = "",
    ):
        self.llm = llm_client
        self.cache_dir = cache_dir
        self.exam_subject = exam_subject or ""
        self.standard_label = standard_label or ""

    def extract(self, question: dict) -> "ExtractionResult":
        """从单道题提取考点 + 增强解析"""
        qid = question.get("id", "")
        cache_path = os.path.join(self.cache_dir, f"{qid}.json")

        # 1. 缓存
        if os.path.exists(cache_path):
            try:
                cached = json.load(open(cache_path, encoding="utf-8"))
                cached_result = ExtractionResult.from_dict(cached)
                if not cached_result.error:
                    return cached_result
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        # 2. 无 LLM（测试模式）
        if self.llm is None:
            return ExtractionResult(question_id=qid)

        # 3. 构建 prompt
        user_prompt = build_user_prompt(question)
        system_prompt = self._system_prompt()

        # 4. 调 LLM（复用 phase4 的 backoff）
        from phase4_content_generator import call_with_backoff, LLMBalanceError
        try:
            raw = call_with_backoff(
                self.llm.chat_json,
                system_prompt,
                user_prompt,
                temperature=0.3,
                timeout=120,
            )
        except LLMBalanceError:
            raise
        except Exception as e:
            code = type(e).__name__
            print(f"  ⚠ [{qid}] LLM 调用失败 ({code})")
            return ExtractionResult(question_id=qid, error=code)

        # 5. 答案比对
        llm_answer = raw.get("answer", "")
        bank_answer = question.get("answer", "")
        mismatch, mismatch_msg = check_answer_mismatch(llm_answer, bank_answer)
        if mismatch:
            print(f"  ⚠ [{qid}] {mismatch_msg}")

        # 6. 构建 result
        result = ExtractionResult(
            question_id=qid,
            answer=llm_answer,
            question_translation=raw.get("question_translation", ""),
            option_translations=raw.get("option_translations", []),
            core_exam_points=raw.get("core_exam_points", []),
            option_analyses=raw.get("option_analyses", []),
            memory_tips=raw.get("memory_tips", []),
            knowledge_expansion=raw.get("knowledge_expansion", []),
            cornell_note=raw.get("cornell_note", {}),
            exam_point_summary={
                **raw.get("exam_point_summary", {}),
                "source_question": qid,
            },
            is_calculation=raw.get("is_calculation", False),
            calc_solution=raw.get("calc_solution") or {},
            is_methodology=raw.get("is_methodology", False),
            method_extract=raw.get("method_extract") or {},
            quotes=raw.get("quotes") or [],
            answer_mismatch=mismatch,
            error=mismatch_msg,
        )

        # 7. 缓存
        if not result.error:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

        return result

    def extract_batch(
        self,
        questions: list[dict],
        progress_cb: Callable[[int, int, str], None] = None,
        max_workers: int = 5,
    ) -> list["ExtractionResult"]:
        """批量提取（多线程）

        Args:
            questions: 题目列表
            progress_cb: 进度回调 fn(done, total, qid)
            max_workers: 最大并发数
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: dict[str, ExtractionResult] = {}
        total = len(questions)

        def process(q):
            return q["id"], self.extract(q)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(process, q): q for q in questions}
            done = 0
            for fut in as_completed(futs):
                qid, result = fut.result()
                results[qid] = result
                done += 1
                if progress_cb:
                    progress_cb(done, total, qid)

        # 保持原始顺序
        return [results.get(q["id"]) for q in questions if q["id"] in results]

    def _system_prompt(self) -> str:
        prompt = SYSTEM_PROMPT
        prompt = prompt.replace("{exam_subject}", self.exam_subject + " ", 1) if self.exam_subject else prompt.replace("{exam_subject}", "", 1)
        prompt = prompt.replace("{standard_label}", self.standard_label + " " if self.standard_label else "考试", 1)
        return prompt


# ---------------------------------------------------------------------------
# 结果数据模型
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    """单题的提取结果"""
    question_id: str
    answer: str = ""
    question_translation: str = ""
    option_translations: list[dict] = field(default_factory=list)
    core_exam_points: list[dict] = field(default_factory=list)
    option_analyses: list[dict] = field(default_factory=list)
    memory_tips: list[str] = field(default_factory=list)
    knowledge_expansion: list[dict] = field(default_factory=list)
    cornell_note: dict = field(default_factory=dict)
    exam_point_summary: dict = field(default_factory=dict)
    is_calculation: bool = False
    calc_solution: dict = field(default_factory=dict)
    is_methodology: bool = False
    method_extract: dict = field(default_factory=dict)
    quotes: list[str] = field(default_factory=list)
    answer_mismatch: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "answer": self.answer,
            "question_translation": self.question_translation,
            "option_translations": self.option_translations,
            "core_exam_points": self.core_exam_points,
            "option_analyses": self.option_analyses,
            "memory_tips": self.memory_tips,
            "knowledge_expansion": self.knowledge_expansion,
            "cornell_note": self.cornell_note,
            "exam_point_summary": self.exam_point_summary,
            "is_calculation": self.is_calculation,
            "calc_solution": self.calc_solution,
            "is_methodology": self.is_methodology,
            "method_extract": self.method_extract,
            "quotes": self.quotes,
            "answer_mismatch": self.answer_mismatch,
            "error": self.error,
        }

    @staticmethod
    def from_dict(d: dict) -> "ExtractionResult":
        return ExtractionResult(
            question_id=d.get("question_id", ""),
            answer=d.get("answer", ""),
            question_translation=d.get("question_translation", ""),
            option_translations=d.get("option_translations", []),
            core_exam_points=d.get("core_exam_points", []),
            option_analyses=d.get("option_analyses", []),
            memory_tips=d.get("memory_tips", []),
            knowledge_expansion=d.get("knowledge_expansion", []),
            cornell_note=d.get("cornell_note", {}),
            exam_point_summary=d.get("exam_point_summary", {}),
            is_calculation=d.get("is_calculation", False),
            calc_solution=d.get("calc_solution", {}),
            is_methodology=d.get("is_methodology", False),
            method_extract=d.get("method_extract", {}),
            quotes=d.get("quotes") or [],
            answer_mismatch=d.get("answer_mismatch", False),
            error=d.get("error", ""),
        )
