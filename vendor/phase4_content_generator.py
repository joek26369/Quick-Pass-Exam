"""
Phase 4 Content Generator — LLM 生成概念内容

职责：对 Phase 3 产出的概念骨架，调 LLM 填充详细内容：
  - one_liner: 一句话理解
  - core_concept.{definition, principle, syntax, rules, comparisons}
  - mnemonic: 记忆口诀
  - why_tested: 为什么考这个
  - common_mistakes: 常见错误

设计要点：
- 每个概念只调 1 次 LLM，输入 = 概念标题 + 来源题（精简，~800 token）
- 输出 JSON，复用现有 exporter/renderer 的字段契约
- 支持缓存（避免重复调用）
- 支持批量并发
"""
import json
import os
import re
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

# 复用现有 LLM 客户端
try:
    from llm_client import LLMClient
except ImportError:
    LLMClient = None

from note_quality import normalize_cornell


class LLMBalanceError(Exception):
    """余额/额度/认证不可恢复错误，穿透中止。"""


_BALANCE_KEYWORDS = (
    "余额", "quota", "insufficient_quota", "billing", "credits",
    "exhausted", "402", "认证", "unauthorized", "invalid_api_key",
)


def _is_balance_error(msg: str) -> bool:
    return any(k.lower() in msg.lower() for k in _BALANCE_KEYWORDS)


def call_with_backoff(fn, *args, max_attempts: int = 2, base: int = 5, **kwargs):
    """LLM 调用 + 指数退避重试。

    - 429/rate limit → 退避重试（base * 2^i，上限 600s）
    - 余额/额度/认证错误 → 立即穿透中止
    - 其他异常 → 短退避重试（上限 300s）

    测试中设置环境变量 LLM_BACKOFF_NO_SLEEP=1 可跳过所有 sleep。
    """
    last = None
    _no_sleep = os.environ.get("LLM_BACKOFF_NO_SLEEP", "") == "1"
    for i in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            msg = str(e)
            if _is_balance_error(msg):
                raise LLMBalanceError(msg) from e
            if any(k in msg for k in ("429", "rate", "速率", "1302")):
                wait = min(base * (2 ** i), 600)
                print(f"  [backoff] 限流/429，{wait}s 后重试 ({i+1}/{max_attempts})")
            else:
                wait = min(base * (2 ** i), 300)
                print(f"  [backoff] LLM 错误: {msg[:120]}; {wait}s 后重试")
            if not _no_sleep:
                time.sleep(wait)
    raise last


SYSTEM_PROMPT = """你是一个{exam_subject}技术专家。根据给定的章节信息和该章节下所有题目的完整分析，生成系统、全面、结构化、便于复习的概念知识笔记。
输出必须是 JSON 格式，字段如下：

{
  "concept_id": "英文 snake_case 概念ID",
  "category": "所属知识领域的名称",
  "one_liner": "一句话概括这个概念（15-30字）",
  "aliases": [
    {"text": "中文名/别名", "type": "synonym|abbreviation|translation"}
  ],
  "core_concept": {
    "definition": "概念定义：2-3 句话精准解释该概念是什么",
    "principle": "底层原理/为什么这样做（50-150字，讲清机制）",
    "syntax": "概念有计算公式→主公式行（<<FORMULA_STYLE>>；<<VAR_NOTE_STYLE>>；<<OPERATOR_STYLE>>；<<NO_LATEX_STYLE>>；<<PARAGRAPH_STYLE>>）；概念是命令/代码类→{code_format} 语法示例；两者皆无→过程框架",
    "rules": ["关键规则1", "关键规则2"],
    "comparisons": [
      {"vs": "对比对象", "difference": "核心区别（一句话）"}
    ],
    "type_comparison": [
      {
        "type": "类型名称（如 三角分布 / 贝塔分布、典型偏差 / 非典型偏差）",
        "syntax_example": "语法示例",
        "key_rules": "关键规则/区别"
      }
    ]
  },
  "best_practices": ["官方推荐做法或通用建议1", "官方推荐做法或通用建议2"],
  "visualization": {
    "type": "architecture|flow|hierarchy|comparison|table|mindmap|process|quadrant|none",
    "nodes": ["节点1", "节点2"],
    "relations": ["节点A → 节点B"]
  },
  "why_tested": "考试为什么考这个知识点（2-4句，考点方向）",
  "mnemonic": "记忆口诀或助记方法（≤30字，可选）",
  "common_mistakes": [
    {"mistake": "常见错误描述", "correct": "正确理解", "severity": "high|medium|low"}
  ],
  "learning": {"level": 2, "estimated_hours": 1.5, "path_note": "先理解X再学Y"},
  "related_questions": ["Q0069", "Q0141"],
  "images": ["![[assets/ref/29/images/page9_img0.png]]"],
  "cornell_note": {
    "pairs": [
      {"cue": "针对一个核心知识点提出的精准问题", "note": "直接回答左侧问题的完整笔记；保留定义、主公式、适用条件或关键区别，核心术语加粗。一个问题与对应答案组成一行。"}
    ],
    "summary": "2-3 句核心结论 + 一句朗朗上口的记忆口诀（涵盖最核心的易错点）"
  },
  "tags": ["标签1"],
  "difficulty_level": 2,
  "references": ["教辅来源文件路径"]
}

要求：
1. 内容必须准确、专业，基于{standard_label}和考试标准
2. 所有文本用中文，术语保留英文大写
3. 只输出 JSON，不要输出其他内容

输出必须包含以下 5 个核心部分：
4. **概念定义**（core_concept.definition）：2-3 句话精准解释该概念是什么
5. **核心分类/语法对比**（core_concept.type_comparison）：如概念包含多种类型/变体公式（如三角分布 vs 贝塔分布、典型偏差 vs 非典型偏差的 ETC），必须用 type_comparison 列出每种类型的 type（类型名称）、syntax_example（完整公式）、key_rules（关键规则/区别）。单一类型的概念可省略此字段。
6. **关键规则与限制**（core_concept.rules + common_mistakes）：rules 列出必须遵守的技术细节，common_mistakes 至少 1 条，列出易错点。rules 数量应不少于输入中考点的总数，不要遗漏任何考点。
7. **最佳实践与建议**（best_practices）：给出官方推荐做法或通用建议，至少 1 条
8. **知识关联**（related_questions）：标注与该概念相关的典型考题编号，从输入的题目列表中选取
8b. **教辅原图嵌入**（images）：教辅图表转写行首的 ![[…]] 原图路径，与该概念直接相关的才原样复制进 images 数组（≤3 张）；转写与概念无关或无图时省略此字段。禁止编造路径、禁止改写路径。
9. **康奈尔笔记**（cornell_note）：必须输出非空 pairs 数组，每项 cue 是左侧问题、note 是右侧直接回答，逐行语义对应；不要输出互不对应的 cues/notes 列表。将概念知识笔记转换为康奈尔笔记格式
   - cues（线索栏）：针对笔记区每个核心模块提出精准技术疑问句（"是什么？""有哪几种？""有什么区别？""关键限制是什么？"），禁止模糊提问
   - notes（笔记区）：从概念知识笔记中提炼要点（定义、类型、关键规则、核心区别、重要限制），保留主公式行，删除冗余过渡句，核心术语加粗。禁止引入外部知识
   - summary（总结区）：2-3 句核心结论 + 一句记忆口诀（涵盖最核心的易错点）
15. **公式一致性**：凡是公式（计算类概念必有）：①主公式行只能有一条，<<FORMULA_STYLE>>；②cornell_note、rules、type_comparison、common_mistakes 里引用公式时，必须与主公式行逐字一致，禁止同概念两种写法；③禁止只用缩写代号（如 EV/AC）不写全名——首次出现用「全名（缩写）」，公式行内直接用全名；④<<OPERATOR_STYLE>>；⑤<<NO_LATEX_STYLE>>。

其他规范：
10. **concept_id 命名**：英文 snake_case，2-4 个词，体现概念核心语义。禁止 concept_ 前缀。
11. **category**：从以下知识领域中选择最匹配的一个。<<DOMAIN_EXAMPLES>>
12. **visualization.type** 从受控词表选取。如确实无可视化类型选 none。
    visualization 必须从核心概念的定义、原理、type_comparison、comparisons 中派生，帮助理解和记忆概念。
    如输入含【教辅参考】，优先从教辅内容中提取结构（如教材的分类层级、流程步骤）派生 visualization 和 type_comparison，而不是从题目分析中凑节点。
    - hierarchy：类型间的包含/层级关系（如成本分类树、合同类型树）
    - flow：执行流程/数据流向（如立项流程、变更控制流程）
    - comparison：概念间对比关系（如关键路径法 vs PERT、静态 vs 动态投资回收期）
    - architecture：组件架构关系（如挣值管理的 PV/EV/AC 三值体系）
    - nodes 和 relations 必须直接来自上方已生成的内容，不得引入外部知识
13. **aliases** 至少给 1 个中文翻译或常用别名。
14. **comparisons**（对比矩阵）至少 3 个维度，覆盖关键区别。如该概念无对比对象可省略。"""


@dataclass
class GeneratedContent:
    """LLM 生成的概念内容"""
    concept_id: str
    category: str = ""
    one_liner: str = ""
    aliases: list = field(default_factory=list)
    core_concept: dict = field(default_factory=dict)
    best_practices: list = field(default_factory=list)
    visualization: dict = field(default_factory=dict)
    mnemonic: str = ""
    why_tested: str = ""
    common_mistakes: list = field(default_factory=list)
    learning: dict = field(default_factory=dict)
    related_questions: list = field(default_factory=list)
    images: list = field(default_factory=list)   # 教辅原图 ![[…]] 引用（LLM 从转写行复制）
    cornell_note: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    difficulty_level: int = 2
    references: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "one_liner": self.one_liner,
            "aliases": self.aliases,
            "core_concept": self.core_concept,
            "best_practices": self.best_practices,
            "visualization": self.visualization,
            "mnemonic": self.mnemonic,
            "why_tested": self.why_tested,
            "common_mistakes": self.common_mistakes,
            "learning": self.learning,
            "related_questions": self.related_questions,
            "images": self.images,
            "cornell_note": self.cornell_note,
            "tags": self.tags,
            "difficulty_level": self.difficulty_level,
            "references": self.references,
        }


class ContentGenerator:
    """Phase 4: 按章节生成概念笔记

    输入：按 chapter 聚合的 Phase 1 完整分析
    输出：每 chapter 下的概念知识笔记
    """

    def __init__(
        self,
        llm_client=None,
        cache_dir: str = "data/_generated_content",
        domain_examples: list[str] = None,
        exam_subject: str = "",
        standard_label: str = "",
        code_format: str = "sql",
        max_workers: int = 3,
        ref_context_fn: Callable | None = None,
    ):
        self.llm = llm_client
        self.cache_dir = cache_dir
        self.domain_examples = domain_examples or []
        self.exam_subject = exam_subject or ""
        self.standard_label = standard_label or ""
        self.code_format = code_format or "sql"
        self.max_workers = max_workers
        # 高质量模式：fn(concept_title) -> [{source, text}] | None
        self.ref_context_fn = ref_context_fn
        os.makedirs(cache_dir, exist_ok=True)

    def _system_prompt(self) -> str:
        if self.domain_examples:
            domain_text = "参考知识领域（选择最匹配的）：" + "、".join(self.domain_examples)
        else:
            domain_text = "根据本次考试科目的知识体系，选择最贴合的知识领域名称。"
        prompt = SYSTEM_PROMPT.replace("<<DOMAIN_EXAMPLES>>", domain_text)
        prompt = prompt.replace("{exam_subject}", self.exam_subject + " ", 1) if self.exam_subject else prompt.replace("{exam_subject}", "", 1)
        prompt = prompt.replace("{standard_label}", self.standard_label + " " if self.standard_label else "考试", 1)
        prompt = prompt.replace("{code_format}", self.code_format, 1)
        # 公式规范共享常量注入（与 ruankao/exporter.py _CALC85_SYSTEM_PROMPT 同源）
        import formula_style
        for ph, val in [("<<FORMULA_STYLE>>", formula_style.FORMULA_STYLE),
                        ("<<VAR_NOTE_STYLE>>", formula_style.VAR_NOTE_STYLE),
                        ("<<OPERATOR_STYLE>>", formula_style.OPERATOR_STYLE),
                        ("<<NO_LATEX_STYLE>>", formula_style.NO_LATEX_STYLE),
                        ("<<PARAGRAPH_STYLE>>", formula_style.PARAGRAPH_STYLE)]:
            prompt = prompt.replace(ph, val)
        return prompt

    def _build_user_prompt(self, chapter: str, domain: str, concept_title: str,
                           phase1_results: list[dict], ref_context: list[dict] | None = None) -> str:
        """构建按章节聚合的 user prompt。ref_context: [{source, text}] 教辅检索段落（高质量模式）。"""
        parts = [
            f"章节：{chapter}",
            f"领域：{domain}",
            f"概念：{concept_title}",
            "",
        ]
        if ref_context:
            parts.append("【教辅参考】以下段落检索自已上传教辅，内容更权威，优先采用其中的"
                         "分类体系、标准表述、公式与例子（references 字段标注实际用到的来源文件名）：")
            for rc in ref_context:
                parts.append(f"--- 来源：{rc.get('source', '')} ---")
                parts.append(rc.get("text", ""))
                img = rc.get("img_descs", "")
                if img:  # 教辅内嵌图转写（带 ![[图路径]] 引用）：网络图数值/表格数字，文本层看不到
                    parts.append("该教辅内嵌图表转写（图面数值以此为准；每行开头的 ![[…]] 是原图路径）：")
                    parts.append(img)
            parts.append("")
        else:
            parts.append("本次没有提供教辅或其他外部来源；references 必须返回空数组，禁止编造教材、章节、页码或来源名称。")
            parts.append("")
        parts += [
            "该章节下包含以下题目的完整分析：",
            "",
        ]
        for r in phase1_results:
            qid = r.get("question_id", "")
            parts.append(f"[{qid}]")
            # 题目翻译
            qt = r.get("question_translation", "")
            if qt:
                parts.append(f"题目：{qt}")
            # 核心考点
            for cp in r.get("core_exam_points", []):
                parts.append(f"  考点·{cp.get('title', '')}：{cp.get('body', '')[:200]}")
            # 记忆要点
            for mt in r.get("memory_tips", []):
                parts.append(f"  记忆：{mt}")
            # 扩展知识
            for ke in r.get("knowledge_expansion", []):
                parts.append(f"  扩展·{ke.get('topic', '')}：{ke.get('body', '')[:150]}")
            parts.append("")
        return "\n".join(parts)

    def _cache_key(self, chapter: str, concept_id: str, ref_context: list[dict] | None = None) -> str:
        raw = f"{chapter}:{concept_id}"
        if ref_context:
            # 教辅注入内容参与 hash：教辅更新/换教辅 → 缓存自动失效，无需人工清
            raw += ":" + hashlib.md5(json.dumps(ref_context, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return hashlib.md5(raw.encode()).hexdigest()

    def generate_chapter(
        self,
        chapter: str,
        domain: str,
        concept_id: str,
        concept_title: str,
        phase1_results: list[dict],
        ref_context: list[dict] | None = None,
    ) -> GeneratedContent:
        """为一个章节/概念生成笔记。ref_context: 教辅检索段落（高质量模式）。"""
        # 缓存
        key = self._cache_key(chapter, concept_id, ref_context)
        cache_path = os.path.join(self.cache_dir, f"{key}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    data = json.load(f)
                cached = self._parse_response(data, concept_id)
                if cached.one_liner or cached.core_concept:
                    return cached
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        if not self.llm:
            return GeneratedContent(concept_id=concept_id)

        # 调 LLM
        user_prompt = self._build_user_prompt(chapter, domain, concept_title, phase1_results, ref_context)
        system_prompt = self._system_prompt()

        try:
            data = call_with_backoff(
                self.llm.chat_json,
                system_prompt,
                user_prompt,
                temperature=0.3,
            )
        except LLMBalanceError:
            raise
        except Exception as e:
            print(f"  ⚠ 概念 {concept_id} 生成失败 ({type(e).__name__})")
            return GeneratedContent(concept_id=concept_id)

        content = self._parse_response(data, concept_id)

        # category
        if isinstance(data, dict):
            llm_cat = data.get("category", "").strip()
            if llm_cat:
                content.category = llm_cat

        if content.one_liner or content.core_concept:
            self._save_cache(cache_path, content)
        return content

    def _parse_response(self, data: dict, concept_id: str) -> GeneratedContent:
        """解析 LLM 返回的 JSON"""
        return GeneratedContent(
            concept_id=concept_id,
            category=data.get("category", ""),
            one_liner=data.get("one_liner", ""),
            aliases=data.get("aliases", []),
            core_concept=data.get("core_concept", {}),
            best_practices=data.get("best_practices", []),
            visualization=data.get("visualization", {}),
            mnemonic=data.get("mnemonic", ""),
            why_tested=data.get("why_tested", ""),
            common_mistakes=data.get("common_mistakes", []),
            learning=data.get("learning", {}),
            related_questions=data.get("related_questions", []),
            images=data.get("images", []),
            cornell_note=self._normalize_cornell(data.get("cornell_note", {})),
            tags=data.get("tags", []),
            difficulty_level=data.get("difficulty_level", 2),
            references=data.get("references", []),
        )

    @staticmethod
    def _normalize_cornell(cn) -> dict:
        """规范化 cornell_note：LLM 偶尔把 notes/cues 返回成字符串（会被逐字符迭代成单字列表），
        强制转成 [str]；条目非字符串的转 str。"""
        normalized = normalize_cornell(cn)
        # Preserve the historical fields and add explicit pairing metadata;
        # exporters can therefore reject ambiguous arrays without shifting
        # answers between cues.
        return normalized if normalized.get("pairing_status") != "empty" else {}

    def _save_cache(self, path: str, content: GeneratedContent):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content.to_dict(), f, ensure_ascii=False, indent=2)

    def generate_batch(
        self,
        chapter_groups: list[dict],
        progress_cb: Callable = None,
    ) -> dict[str, GeneratedContent]:
        """批量生成（多线程）

        Args:
            chapter_groups: [{chapter, domain, concept_id, concept_title, phase1_results}]
            progress_cb: fn(done, total, concept_id)

        Returns:
            {concept_id: GeneratedContent}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: dict[str, GeneratedContent] = {}
        total = len(chapter_groups)

        def process(g):
            ref_ctx = None
            if self.ref_context_fn:
                try:
                    ref_ctx = self.ref_context_fn(g["concept_title"])
                except Exception as e:
                    print(f"  ⚠ 教辅检索失败 {g['concept_id']} ({type(e).__name__})")
            return g["concept_id"], self.generate_chapter(
                g["chapter"], g["domain"], g["concept_id"],
                g["concept_title"], g["phase1_results"], ref_context=ref_ctx,
            )

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futs = {pool.submit(process, g): g for g in chapter_groups}
            done = 0
            for fut in as_completed(futs):
                cid, content = fut.result()
                results[cid] = content
                done += 1
                if progress_cb:
                    progress_cb(done, total, cid)

        return results

    def merge_into_concepts(
        self,
        concepts: list[dict],
        contents: dict[str, GeneratedContent],
    ) -> list[dict]:
        """把生成的内容合并回 concept dict 列表（原地修改）"""
        for concept in concepts:
            cid = concept.get("id", "")
            content = contents.get(cid)
            if not content:
                continue

            if content.category:
                # ponytail: category 只在 parent 为空时补充，不覆盖 Phase2 分类
                # （LLM 会把计算类概念分到"计算题"这种题型名，不是合法知识章节）
                if not concept.get("parent"):
                    concept["parent"] = content.category
            if content.one_liner:
                concept["one_liner"] = content.one_liner
            concept["core_concept"] = content.core_concept
            if content.best_practices:
                concept["best_practices"] = content.best_practices
            if content.visualization and content.visualization.get("type", "none") != "none":
                concept["visualization"] = content.visualization
            if content.mnemonic:
                concept["mnemonic"] = content.mnemonic
            if content.why_tested:
                concept["why_tested"] = content.why_tested
            if content.common_mistakes:
                concept["common_mistakes"] = content.common_mistakes
            if content.aliases:
                concept["aliases"] = content.aliases
            if content.learning:
                concept["learning"] = content.learning
            if content.related_questions:
                concept["related_questions"] = content.related_questions
            if content.cornell_note:
                concept["cornell_note"] = content.cornell_note
            if content.tags:
                concept["tags"] = content.tags
            if content.difficulty_level:
                concept["difficulty_level"] = content.difficulty_level
            if content.references:
                concept["references"] = content.references

        return concepts
