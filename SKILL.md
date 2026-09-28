---
name: quick-pass-exam
display_name: Quick-Pass-Exam
display_name_en: Quick-Pass-Exam
description: 处理题库、真题、教辅、选择题、案例题、错题本或离线学习包生成请求；由 Agent 读取原文件并建立题目、知识点与教辅证据关联。
description_zh: 针对IT认证和软考备考，把分散的题库和教辅资料系统整理成考点知识笔记，一键查看关联内容，刷题的同时高效掌握考点。
description_en: Build an offline exam study package from original question banks and teaching materials, with evidence-linked choice questions, case studies, knowledge cards, methods, and review records.
version: 1.0.0-beta.6
author: Quick Pass Exam
user-invocable: true
disable-model-invocation: false
---

# Quick-Pass-Exam 单机学习包

这是 Quick-Pass-Exam OSS WorkBuddy Skill v1.0.0-beta.6 公开测试版。本 Skill 自有代码、文档和合成验收示例采用 Apache License 2.0，完整文本与权利边界见根目录 `LICENSE`、`NOTICE.md` 和 `THIRD_PARTY_NOTICES.md`；用户导入资料和第三方依赖不因此被重新授权。开始前读取 @references/validation.md，了解实际验证范围和待验项。下文路径均相对于本 Skill 目录；从其他工作目录运行命令时，先解析为正确路径。

## WorkBuddy 资源与执行入口

- `references/` 存放按需读取的领域规则和验证说明；仅在相应任务需要时读取本文明确指向的参考文件。
- `scripts/quick-pass.py` 是生成、导入和打开学习包的标准入口；参数继续传给底层 CLI。
- `scripts/study-library.py` 是注册学习包、启动本地学习库和收录选择题错题的标准入口。
- `templates/` 存放生成离线 Web 学习包所需的页面与交互模板，不把其中内容当作用户输入或事实证据。
- 从 Skill 根目录运行命令。需要文档导入时安装 `requirements-import.txt`；普通打包安装 `requirements.txt`。

## 默认流程：Agent-first

处理用户目录或修复漏包前，必须读取 @references/source-coverage.md。先按用户明确指定的目录锁定 `source-inventory.json.input_scope`，再遍历和筛选资料；不得用筛选后的工作目录代替用户输入范围。发现漏包时，按该规范完成补读、补关联、重新生成、复核和向用户补报，不能只指出问题或只改报告。

默认流程把语义工作交给运行本 Skill 的 Agent：

1. 接收用户提供的全部题库和教辅原文件。原文件是第一手输入，本地提取出的文本不能替代原文件。
2. Agent 完成全部语义工作：识别题目、选项、答案及其来源；归纳知识点；建立题目与知识点的多对多关联；定位相关教辅段落和页面；建立知识点与证据的多对多关联；结合题目和教辅证据编写知识卡。
3. 本地代码只做确定性预处理和校验：检查安全相对路径、可选哈希、PDF 物理页数、稳定 ID、双向引用、归一化区域、资源复制和引用页渲染。代码不得判断某段是否为题目、猜答案、生成知识点、检索教辅或臆造关联。
4. 本地代码渲染静态学习包。每个知识点显示 Agent 选定的教辅节选和页面缩略图；点击卡片可以查看原页和包内原文件。题目若关联到已核验的 PDF 物理页，也要生成完整原页的离线图像；刷题页提供可展开的原页入口。
   渲染后代码还会核对原始范围是否变化、落盘数据与 HTML 的教辅关联、原文件哈希和页图；失败时不发布正式输出目录，并输出带修复指令的失败报告。Agent 修复后必须重新生成和核对，不能手动把报告改为 passed。
5. 生成成功时向 CLI 传入 `--open`。CLI 会注册学习包、启动或复用本地学习库、检查服务响应并打印可用 URL。把该 URL 返回给学习者；不要让用户自行安装 SQLite、注册学习包或启动服务。

交付或替换现有包前，运行 `python3 scripts/verify-package.py <package-directory>`，并完成新增教辅的浏览器抽查。仅原始覆盖与生成后检查均 passed 才可宣称本次范围内无未处置漏项；OCR、公式和关联语义仍需 Agent 对照原件核验，不能用结构检查替代。

Agent 应生成 `agent-content.json`，其中包含 `schema_version: "quick-pass-agent-content-v2"`、`sources`、`questions`、`concepts` 和 `teaching_evidence`，再通过 `--agent-content` 执行确定性校验和打包。`sources` 必须把每个入包原文件明确标为 `question_bank` 或 `teaching_material`；每条证据必须携带稳定的来源 ID、知识点 ID、PDF 物理页、节选内容和可选归一化区域。JSON 应与入包原文件放在同一目录，并使用相对路径。

处理用户资料目录时，先盘点全部原文件，再制作 `source-inventory.json`，不能仅列出已经挑中的教辅。每条记录使用相对用户原始资料根目录的 `path`；`decision: "included"` 时填写对应 `sources.id` 的 `source_id`，`decision: "excluded"` 时填写具体 `reason`。教辅虽入包但没有关联证据时填写 `no_evidence_reason`。对扫描页使用视觉读取或 OCR；无法可靠识别时写明原因，不把无文字层当成“无内容”。不要为了覆盖率伪造 `supports`；主题相关但不足以支持卡片主张时使用 `related`。

生成时同时传入 `--source-root <用户原始资料根目录> --source-inventory <source-inventory.json>`。可重复传入 `--source-scope <相对子目录>`，只检查本次用户要求处理的文件夹；省略 scope 则检查整个根目录。程序逐文件核对清单、入包 source 的哈希和教辅证据数量，漏登记或无理由排除时阻止生成，并输出 `<输出目录>.source-coverage.json`。成功包内的 `reports/source-coverage.json` 可供交付验收。未提供原始目录和清单时，报告状态为 `not_checked`，不得宣称“全部教辅已处理”。

`--agent-content` 不调用模型，但会执行严格的 contract、Cornell pair、provenance 和 bidirectional link quality gates。通过这些检查只说明结构合规，不代表内容在语义上真实，也不能替代人工审阅。

文档识别没有独立 parser 或隐藏 OCR provider 路径。Agent 使用当前可用的文档与视觉工具直接阅读 PDF、DOCX、TXT 和 Markdown 原件。旧的 `--import-only` 仅作为诊断兼容工具保留，不是默认流程，也不是语义解析器。旧的 `--llm-config` 仅用于从已校验的 questions JSON 生成知识内容。

## 计算方法覆盖

生成或修复题目内容前必须读取 @references/method-coverage.md，逐题建立 `method_coverage` 清单；选择题和案例小问均需分类。按真实算法拆分并补齐方法，禁止只用考点标签批量关联或固定卡片数量。生成前后检查与浏览器验收通过后，按该规范向用户补报。

## 案例题与自评

遇到共享背景、多问、计算题或简答题时，必须读取 @references/case-authoring.md。v2 可在选择题之外接受 `cases` 和 `methods`；仅有案例题时使用 `questions: []`。

Agent 必须从原件检查完整背景、图表、续页和答案归属：

- 保留案例原编号、背景材料、图表、原页和每个小问的稳定编号、题型与原文。
- 把参考答案原文逐问对应；原文答案与 Agent 生成的解析、计算步骤和易错点必须清楚区分。
- 只有来源明确时才填写分值和评分要点。没有评分细则时，不生成看似精确的分数。
- 缺失或错位答案保留为 unresolved/missing，并写明核验状态，不能根据常识补写为原答案。
- 案例草稿、自评和待复习记录与选择题正确率分别保存。

交付前按案例题规范检查计算案例、多问简答案例、跨页带图案例、缺失或错位答案案例，以及选择题与案例题混合学习包，并验证原页跳转。

## 编写和审阅知识卡

编写真实 Agent 内容前，必须读取 @references/card-authoring.md 和 @references/card-quality-examples.md。`--agent-content` 不运行旧内容生成器的 prompt，因此 Agent 必须主动落实其中的教学质量要求。README 中的最小 JSON 只演示接口，不是合格知识卡的质量目标。

每张真实知识卡都要完成规范中的六项 `learning_support_review`。逐项判断 principle、comparison、practice、exam rationale、mnemonic 和 visualization 是否有助于理解当前知识点；有可靠内容时写入，没有时记录具体省略原因。交付前检查 package-wide coverage report；若整个包没有 diagram 或 mnemonic，必须进行全包级复核。只有经过检查的学习关系才能写入 `learning_relations`，章节相邻不自动构成 prerequisite。

先把题目要求归纳为可复用知识点，再收集证据，最后编写卡片。按规范执行 standalone review 和 transfer check：一道题的 worked solution 不能替代可迁移的方法卡。扩展相邻知识时必须有明确学习目的，使用已有字段区分 core 和 extension，并逐条验证新增内容；不得为了扩展而伪造题目关联。

保留简洁的工作清单，记录知识点范围、题目 ID、归组理由、支持段落和未解决主张。不要按模板机械地“一题一卡”，也不要强行合并无关题目或追求固定卡片数量。单一事实或确实独立的题目可以形成短卡。

批量编写前，先选择具有代表性的样本与原件核对，覆盖实际存在的不同卡片类型和困难证据情形。自行审阅并修订样本，无需再次向用户请求许可，然后逐卡对照关联题目和证据完成审校。公式适用条件、图表、冲突和证据缺失必须单独检查。计算和图表题要独立复算中间值与约束，不能只凭答案一致判定正确。

把同一段题目解析整段复制到 takeaway、Cornell answer 和 summary 属于不合格卡片；增加字数或重复更多 pair 不能修复该问题。

### 概念对比统一使用表格

知识卡中的概念对比不得再写成连续段落或并列卡片。Agent 应把对比内容写入 `core_concept.comparisons`，页面统一显示为表格。每个对比对象必须提供以下结构，同时保留用于摘要和兼容质量门的 `difference`：

```json
{
  "vs": "对比概念",
  "difference": "两者最核心的区别",
  "commonality": "确有共同点时填写；没有则省略",
  "dimensions": [
    {"dimension": "核心定义", "current": "当前概念的定义", "compared": "对比概念的定义"},
    {"dimension": "适用条件", "current": "当前概念的条件", "compared": "对比概念的条件"}
  ]
}
```

`dimensions` 不使用固定模板，应根据概念关系选择真正能形成差异的维度：

| 概念类型 | 优先选择的对比维度 |
| --- | --- |
| 流程类 | 目的、输入、主要活动、输出、发生阶段 |
| 方法类 | 适用条件、操作步骤、结果、限制 |
| 指标类 | 计算方式、数值含义、判断标准、常见误用 |
| 角色类 | 职责、权限、参与阶段、交付物 |
| 分类类 | 分类依据、范围、典型示例、排除项 |
| 相近术语 | 核心定义、关注对象、关键区别、题目判断线索 |

表头固定为“对比维度｜当前概念｜对比概念”，对比对象必须位于纵向列中；表格主体每行只比较一个维度。只保留有助于区分概念的行，不得为凑表格机械填满全部维度。两者相同的内容合并写入 `commonality`，不要在两列重复粘贴。差异关键词可用现有 Markdown 加粗语法突出，但不得用强调格式代替事实说明。对比对象超过两个、导致列宽过窄时，拆成多张三列表，或改用“维度｜对象｜说明”的纵向表格。页面必须保留表头；手机端允许横向滚动，不能压缩到无法阅读。

严格区分以下来源：

- question-bank explanation：题库原有解析；
- teaching evidence：直接支持具体主张的教辅证据；
- related passage：主题相关但不能直接证明该主张的段落；
- Agent-derived illustration：Agent 为教学生成的说明或示例。

教辅支持缺失或内容冲突时，要在卡片可见文本和交付报告中保留。某张卡存在一条 `supports` 关系，不代表其全部主张已经核验。语义审阅由 Agent 负责；确定性代码不能证明内容真实。

## 根据用户请求选择入口

- **“用样例生成学习包”**：运行 `python3 scripts/quick-pass.py --input examples/learning-package-input.json --profile ruankao-xitixiangmu --fixture --output <new-directory> --open`。该命令只打包仓库样例，不调用模型，必须说明这是 fixture/demo mode。
- **“导入我的题库和教辅”**：直接检查全部原文件，不修改原件，也不先经过本地语义 parser。使用 Agent 的文档/视觉工具读取 PDF、DOCX、TXT 和 Markdown；XLS/XLSX 等其他资料也要登记并说明处理方式。先完成原始资料清单，再为每个入包文件在 v2 `sources` 中写明 role 和 relative path。
- **“生成考点笔记和解析”**：Agent 完成前述全部语义步骤并写出完整 v2 payload。不得以文件名匹配、关键词规则或本地向量相似度替代 Agent 明确声明的关联。根据材料选择 profile：系统集成项目管理工程师（中级）使用 `ruankao-xitongjicheng`；信息系统项目管理师（高级）使用 `ruankao-xitixiangmu`。不得把中级资料放入高级 profile。然后运行 `python3 scripts/quick-pass.py --input <agent-content.json> --profile <matched-profile> --agent-content --output <new-directory> --open`。只有服务成功响应后才能返回打印出的 URL。
- **“打开学习包并刷题”**：使用 `--open` 打印的 URL。仅监听 loopback 的本地学习库会通过 Python 内置 `sqlite3` 把 attempts 和 wrongbook 保存到 `~/.quick-pass-study/learning.sqlite3`；同一学习库和端口可以让重新生成的学习包继承匹配题目的历史记录。服务不调用模型。直接使用 `file://` 只能得到单文件 browser storage，不能承诺跨包继承。若学习包已生成但学习库启动失败，报告已有包路径与错误，然后运行 `python3 scripts/study-library.py open <package-directory>` 重试；不得为了重启服务而重新生成或覆盖学习包。
- **“在手机 Agent 打开学习包”**：不得只发送或打开 `web/index.html`。单独 HTML 不包含 `web/assets`，会导致 Logo、原页图和 PDF 断链，SQLite 进度也会重置。完整包保留在电脑端，运行当前版本的 `python3 scripts/study-library.py open <package-directory>`；若 health check 显示旧服务，换用新端口。手机 Agent 应通过与电脑端服务的连接打开返回的 HTTP 学习库 URL。宣称移动端成功前，确认页面协议不是 `file://`、可见 Profile 正确、品牌 Logo 和至少一张教辅/原页图的 natural dimensions 非零、PDF HEAD 响应包含 `Accept-Ranges: bytes`，且手机与电脑错题数量一致。页面能显示正文不能证明 assets 或 SQLite 已连接。
- **“把对话中的截图或照片错题收录”**：先读取当前学习页顶部可见的 `当前 Profile` 名称和稳定 ID，并把该 ID 原样传给 `--profile`，不得仅凭截图推测考试科目。用 Agent 视觉工具检查原图，识别题目、选项、可靠答案、可见的用户选择和相关知识点/解释。把图片作为 v2 `sources` 中的 `question_bank`，并以 `diagram_image` 引用，使原图进入新学习包。通过 `--agent-content` 生成全新包后运行 `python3 scripts/study-library.py collect <package-directory> --qid <question-id>`。只有用户错误选择清楚可见或已明确说明时才添加 `--picked <label>`；没有 `--picked` 时表示收藏错题，不得伪造一次作答。答案不确定时应请求补充信息或标记待核验，不能猜测。返回打印出的 URL，供用户检查收录题目与知识解释。
- **“收录多问案例截图”**：使用 `cases` 和 `questions: []`。把原始 `.png`、`.jpg`、`.jpeg` 或 `.webp` 声明为 `question_bank` 来源，并使用 `source_pages: []`；案例页会显示原图。来源中缺失的答案标记为 `missing`，不确定标签或图中数值冲突写入 `coverage_review.reason`。案例题不得使用只支持选择题的 `collect --qid`。用同一本地学习库生成并打开新包，然后点击案例级“收藏进错题本”，确认错题本能显示原图和全部小问。

## 保持数据与契约不变

每次使用新的 output directory。不得覆盖输入或已有学习包，也不得通过删除个人数据解决路径冲突。Agent handoff 目录只有通过 `--resume-agent-contract` 才能继续。输出目录父级的 `.qpe-cache/` 含有私有生成内容，不得进入源码快照。`--fixture` 只用于仓库样例；真实 Agent 内容必须使用 `--agent-content`。

保留来源答案、ID、原文和明确的文件/页码信息。question source 与 teaching-material reference 是不同关系。未知答案或缺失教辅证据必须保持为 `unknown`、`not_found` 或 unresolved；不得为了通过检查而制造 evidence item。纯文本公式和 graph text 是有意保留的 fallback；资源不可用时如实报告，不得声称图片已经渲染。

扫描 PDF 必须直接检查原页，重点核对图表、数值标签、表格和答案页。为每题填写真实 physical `source_page`，renderer 会附加该页图片，不依赖 OCR 文本。图表跨页或同页含多题时，还要提供安全的本地 `diagram_image` crop，同时保留完整原页供审计。不得根据低置信度 OCR 文本猜测图中数值或正确答案。图表或答案仍不清楚时，将其标记为待复核。逐一检查所有带图题在生成页面中的可见性和缩放后可读性。

## 验证与交付

进程退出码为 0 不能单独证明完成。检查：

- `manifest.json`
- `reports/quality-report.json`
- `data/questions.json`
- `data/concepts.json`
- `data/sources.json`
- `data/teaching-evidence.json`
- `web/index.html`

核对数量、稳定答案、多对多关系和预期本地资源。单独审阅内容质量结果，并完成知识卡规范要求的逐卡审查；字段非空不代表质量合格。

在浏览器中验证：知识点能显示对应教辅节选和页缩略图；点击后打开正确物理原页；顶部始终有“错题本”入口和正确空状态；完成一次选择题作答，并验证题目与知识点双向跳转。案例题还要确认同一案例的多个小问一起显示，右侧能显示关联考点和方法卡。方法卡右侧应显示关联案例题和关联考点。错题本左侧列出选择题与案例题，中间显示正文，右侧显示关联考点和方法，并支持手动删除。若无法进行浏览器验收，必须明确报告该缺口。

分别报告 structural checks、Agent content review、browser checks 和 human content review；结构状态 `passed` 不等于语义正确。还要区分 fixture generation、fresh real model generation 与 cached rerun。`reports/usage-attempts.json` 只记录当前进程；缓存历史费用未知，token 数也不能证明账单金额。

交付时给出 output directory、learning library URL 和 learning entry。`learning.sqlite3` 与原始截图/照片都属于用户私有数据，不得放入公开源码快照。公开发布和全局安装本 Skill 不在上述生成命令的执行范围内。

## 文档导入边界

题目/知识点字段、内容阶段、笔记规则、发布质量门和学习页面来自现有 Quick Pass 实现。教辅卡片和原页对话框沿用 concept-evidence 与 `readerDialog` 交互，并把服务端 API 改为包内本地资源。旧的高层 `bank_parser.py` 不包含在本公开测试版中；`document_adapter.py` 和 `--import-only` 只暴露来源材料，不是默认 Agent 路径。语义识别与审阅必须由 Agent 完成。应通过本 Skill 的编写规范加强已有内容检查和报告，不得另外引入一套平行的语义 parser 或 relation engine。
