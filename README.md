# Quick-Pass-Exam README：功能与使用说明

WorkBuddy / Agent Skill：把题库与教辅原文件整理为**离线、可追溯、能记录学习进度**的本地学习网页。当前公开测试版本为 **v1.0.0-beta.2**。本 Skill 自有代码、文档和合成示例采用 [Apache License 2.0](LICENSE)；用户导入资料与第三方依赖不因此被重新授权，详见 [NOTICE.md](NOTICE.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [provenance.json](provenance.json)。

---

## 一、一句话概括

给 Agent 提供 PDF、DOCX、TXT 或 Markdown 题库及可选教辅。Agent 阅读原件并建立「题目 ↔ 知识点 ↔ 教辅证据」的关联；本地代码校验和生成学习网页，包含**考点笔记、方法卡、错题本、选择题、案例题**。电脑端的本地学习库用 SQLite 保存学习记录。

它不是一个「AI 自动出题」工具，而是一个**证据可追溯的学习包生产管线**。

---

## 二、核心设计：Agent-first 分工（这是它最大的特点）

| 角色 | 负责什么 |
| --- | --- |
| **Agent（你/模型）** | 全部语义工作：识别题干、选项、答案及其来源；归纳知识点；建立题目↔知识点多对多关联；在教辅里定位相关段落与物理页；建立知识点↔证据关联；撰写知识卡正文与自测 |
| **本地代码** | 只做确定性校验：相对路径安全、SHA-256、PDF 物理页范围、稳定 ID、双向引用、枚举状态、区域归一化、资源安全复制、被引用 PDF 页渲染、质量门 |

**代码不会做的事**（刻意的边界）：不判断题目边界、不猜答案、不提炼知识点、不检索教辅、不用关键词/向量/文件名相似度臆造关联。

唯一支持的 Agent 交接契约是 `quick-pass-agent-content-v2`；旧 schema 与旧字段别名一律拒绝。`--agent-content` 打包阶段**不调用任何外部模型**。

---

## 三、功能清单

### 3.1 五大学习模块（顶部导航）

| 模块 | 内容 | 备注 |
| --- | --- | --- |
| **考点笔记** | 按考点组织的知识卡：定义、原理、关键规则、公式/框架、康奈尔问答、闪卡、记忆口诀、易错点、概念对比表、知识图谱、学习路径；可跳到关联选择题/案例小问/教辅证据 | 纯案例包显示空状态 |
| **方法卡** | 计算方法 / 答题方法：适用条件、公式或作答框架、步骤、代入过程、单位口径、易错点；与案例小问、考点笔记互跳 | 无方法卡时入口隐藏 |
| **错题本** | 同时收录选择题与整道案例题；左选、中看正文（可折叠原题原件）、右看关联考点与方法；支持自动加入、手动收藏、手动删除 | 顶栏常驻，数量实时显示 |
| **选择题** | 原题干、选项、可靠答案、题库解析、选项分析、记忆提示；单选/多选作答、判题、重做、收藏；原题 PDF 原页与图表可展开核验 | 侧栏可搜索题目；纯案例包显示空状态 |
| **案例题** | 一个完整案例集中展示背景、图表、全部小问；逐问填写并本地保存、展开原文答案与生成解析、自评「掌握/部分掌握/未掌握」、加入待复习、整题收藏 | 自评与选择题正确率**分别统计**，不自动判分 |

### 3.2 一张知识卡里有什么

- **核心概念**：`definition` 定义 / `principle` 原理 / `syntax` 公式或语法 / `rules` 关键规则
- **概念对比表**：强制统一为「对比维度｜当前概念｜对比概念」表格，逐维度一行；`commonality` 写共性，不重复粘贴
- **康奈尔笔记**：cue/note 逐行配对（左右并排，600px 以下纵向），底部 summary；**闪卡模式**可翻卡自测
- **教学辅助**：记忆口诀、易错点（错误做法 → 正确做法 → 严重度）、最佳实践、为什么考
- **可视化**：离线 SVG 知识图谱（节点+有向边，窄屏横向滚动）；四象限类图（如干系人权力/利益）；公式保留可读纯文本
- **关联**：关联选择题、案例小问、`learning_relations` 学习路径（章节相邻**不**自动构成前置关系）
- **教辅证据卡**：文件名 + PDF 物理页 + Agent 选定节选 + 原页缩略图；提供归一化区域时才在页图上标出区域。点击可打开原版页面弹窗，并可跳到包内 PDF 的 `#page=N`。

不同卡片需要讲清的内容，详见 [卡片编写规范](references/card-authoring.md) 与 [质量正反例](references/card-quality-examples.md)：

| 卡片类型 | 必须讲清的内容 |
| --- | --- |
| 概念与分类 | 定义、分类依据、关键区别、适用边界 |
| 计算方法 | 参数含义、公式适用条件、计算步骤、结果解释、易错点 |
| 管理过程 | 过程目的、关键输入输出、工具作用、相邻过程区别 |
| 单一事实 | 准确结论、必要背景、资料版本或时间范围 |

### 3.3 原件与证据可追溯（差异化能力）

- 题目/案例保留**原编号、来源文件、PDF 物理页、图表**；图片可放大，PDF 可跳页
- 扫描 PDF 可以按 Agent 核验过的物理页，将整页以 160 DPI 渲染为离线图片；选择题页面提供折叠的原页入口，点击后可放大。页图显示不代表题目文字、图表数值或答案已识别正确。
- **来源严格分层**，互不冒充：
  - 题库原有解析（question-bank explanation）
  - 教辅证据（teaching evidence，直接支持某条主张）
  - 相关段落（related passage，主题相关但不能直接证明）
  - Agent 生成的说明/示例（Agent-derived）
- 缺答案、缺评分细则、缺图、证据冲突 → 明确标 `missing` / `unresolved` / `limited`，**不猜分值、不猜页码、不补写答案**

### 3.4 本地学习记录（SQLite，不联网）

- 数据位置：`~/.quick-pass-study/learning.sqlite3`（Python 自带 sqlite3，无需额外安装）
- 保存内容：选择题作答与对错、错题本、案例草稿、展开状态、自评、待复习、收藏
- **跨包继承**：同一 profile 下，按「题干+选项+正确答案」的规范化内容匹配题目，Agent 重新编号也不丢记录；新包不含旧题时，历史错题仍会列出（可点开看题干/选项/解析/知识点）
- 掌握规则：错题累计保留，**连续答对 3 次**标记为已掌握并退出待复习列表
- 案例记录：按「学习包 + 小问」保存，当前**不跨重新生成的包迁移**
- 服务只监听 `127.0.0.1`；打开网页、刷题、记录进度**都不调用模型**

### 3.5 多端访问

- 电脑端学习库只监听 `127.0.0.1`。手机需要由有权限连接电脑本地服务的 Agent 或正式连接能力打开完整学习包；直接在手机浏览器输入电脑返回的 `127.0.0.1` 地址无法访问电脑。
- 服务对图片/PDF 提供 `HEAD` 与单段字节范围响应（`Accept-Ranges: bytes`），方便手机 PDF 阅读器按需加载
- ⚠️ 手机端**不要只传 `web/index.html`**：该文件引用同目录 `assets`，单独打开会 Logo/教辅页图/PDF 断链，并且退回不连 SQLite 的单文件记录

### 3.6 质量门与状态含义

`manifest.json` 里三个独立状态：

| 字段 | 可能取值 | 含义 |
| --- | --- | --- |
| `structural_status` | `passed` / 其他 | 结构、路径、哈希、页码、双向引用等确定性检查 |
| `content_status` | `fixture` / `review_required` / `limited` / `agent_reviewed` / `blocked` | 内容与审校状态 |
| `quality_status` | 跟随内容状态 | `blocked` / `failed` 的包**不能注册**学习库 |

确定性内容检查：
- **硬阻断**：同一段题目解析被整段复制到 3 处（含尾部标点变体）、整字段占位文字
- **保留待审**：长段近似重复、缺独立正文
- **不硬失败**：合理的短事实卡、一题一卡、缺少教辅支持
- 可选 `content_review`：逐卡记录 `reviewer / status(reviewed|needs_revision|limited) / rationale`；缺记录的新卡标为待审
- 包级**覆盖率报告**：口诀、图、原理、对比、实践建议、应试重点是否覆盖；整包无口诀或无图会要求复核（而不是编内容）

> 关键提醒：**结构检查通过 ≠ 语义正确**。`agent_reviewed` 只代表 Agent 声明已逐卡审校并通过确定性检查，程序没有独立核验语义。打包器默认记录 `browser_status: "not_checked"`，因为它没有替你浏览页面。

---

## 四、目录结构

```
quick-pass-exam/
├─ SKILL.md                  # Skill 入口（WorkBuddy 读取）
├─ README.md                 # 完整说明（最详细）
├─ NOTICE.md / LICENSE       # Apache-2.0 与权利边界
├─ provenance.json           # 上游来源与文件哈希
├─ cli.py                    # 底层命令行
├─ generator.py              # 契约校验 + 质量门 + 打包
├─ renderer.py               # 静态页面渲染
├─ study_server.py           # 本地学习库（SQLite + HTTP + Range）
├─ agent_preprocess.py       # Agent 内容预处理
├─ case_contract.py          # 案例题契约
├─ document_adapter.py       # 诊断用文档展开
├─ importer.py               # --import-only 导入
├─ scripts/
│   ├─ quick-pass.py         # 标准生成入口
│   └─ study-library.py      # 注册/启动/收录错题入口
├─ templates/                # 页面与交互模板（index.html + 7 个 JS 模块）
├─ vendor/                   # 从主工程适配的既有能力
├─ profiles/                 # ruankao-xitixiangmu（高项）/ ruankao-xitongjicheng（中项）
├─ references/               # 卡片编写规范、正反例、案例规范、验证说明
├─ examples/                 # 固定样本 + 已生成预览 + 合成案例
└─ tests/                    # Python 与 Node 测试
```

---

## 五、使用说明

### 5.0 环境准备

需要 **Python 3.10+**。

```bash
cd /path/to/quick-pass-exam
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt          # 基础：requests
.venv/bin/python -m pip install -r requirements-import.txt   # PDF 导入与原页渲染
```

`requirements-import.txt` 已包含基础依赖、pypdfium2 和 Pillow；SQLite 由 Python 自带。处理 PDF 或生成原页图时安装导入依赖。开发者运行完整测试时安装 `requirements-dev.txt`。第三方许可证见 `THIRD_PARTY_NOTICES.md`。

### 5.1 场景速查

| 我想…… | 用户操作说明 | 用哪个入口 | 是否调用模型 |
| --- | --- | --- | --- |
| 先看完整页面效果 | 在 Agent 对话框中输入「用样例生成一个学习包，我想先看看效果」（无需拖入文件） | `--fixture --open` | 否 |
| 用自己的题库+教辅生成知识卡 | 在 Agent 对话框中拖入题库、教辅资料，输入「用以上资料生成知识卡」 | Agent 读原件 → 写 v2 JSON → `--agent-content --open` | 打包阶段否 |
| 生成纯案例 / 选择题+案例混合包 | 在 Agent 对话框中拖入案例题库（有选择题就一起拖进去），输入「用以上资料生成案例题学习包」，或「生成案例题＋选择题混合学习包」 | v2 JSON 里用 `cases` / `methods` | 否 |
| 已有结构化选择题 JSON，想用模型生成知识内容 | 在 Agent 对话框中拖入已结构化的题目 JSON，输入「用这份题库生成知识卡，走模型生成内容」，并按提示配置模型 Key | `--llm-config` 兼容路径 | 是，可能产生费用 |
| 只打开已生成的包 | 在 Agent 对话框中输入「打开 <学习包路径>」，或「打开上次生成的学习包」 | `study-library.py open <包目录>` | 否 |
| 收录对话里的截图/照片选择题 | 把题目截图或照片直接拖进 Agent 对话框，输入「把这道错题收进错题本」；如果自己做错了，补一句「我选的是 B」 | 生成 v2 图片题包 → `study-library.py collect --qid` | 否 |
| 收录多问案例截图 | 把案例截图拖进 Agent 对话框，输入「把这个案例收进学习包」；生成后在页面上点案例标题旁「收藏进错题本」 | 生成含 `cases` 的 v2 包 → 页面点「收藏进错题本」 | 否 |
| Agent 暂时看不了某个 PDF/DOCX | 在 Agent 对话框中输入「这个文件你没法直接读，先把它展开给我看看」，回填内容后再让它继续生成 | `--import-only` → 回填 → `--resume-agent-contract` | 否（仅诊断展开） |

「用哪个入口」是这些对话指令背后实际执行的命令；正常使用时无需自己敲，只有脱离 Agent 手动运行或排障时才需要直接调用。模型 Key 只通过配置指定的环境变量提供，不要发在对话里。

### 5.2 场景 A：跑通演示包（最快验证安装是否成功）

```bash
.venv/bin/python scripts/quick-pass.py \
  --input examples/learning-package-input.json \
  --profile ruankao-xitixiangmu \
  --fixture \
  --output /tmp/quick-pass-demo \
  --open
```

- 输出目录**必须是不存在的新目录**，程序拒绝覆盖
- 最后一行打印可打开的 `http://127.0.0.1:8766/packages/<id>/web/index.html`
- `--fixture` 只打包仓库内固定样本，**不调用模型**，也不代表真实生成质量。示例输出目录已存在时，请选一个新的目录名。

### 5.3 场景 B：用自己的题库 + 教辅（推荐主路径）

**第一步**，把 `agent-content.json` 和所有原始题库/教辅放在同一目录（或子目录）。Agent 先直接读原件，再写结构化结果。最小接口示例（假设同目录有 `题库.pdf`、`教材.pdf`）：

```json
{
  "schema_version": "quick-pass-agent-content-v2",
  "sources": [
    {"id": "bank-1", "role": "question_bank", "path": "题库.pdf"},
    {"id": "book-1", "role": "teaching_material", "path": "教材.pdf"}
  ],
  "questions": [
    {
      "id": "q-1",
      "question_zh": "成本绩效指数如何计算？",
      "options": [
        {"label": "A", "text": "EV/AC", "is_correct": true},
        {"label": "B", "text": "AC/EV", "is_correct": false}
      ],
      "answer": "A",
      "source_id": "bank-1",
      "source_page": 1,
      "concept_ids": ["concept-1"]
    }
  ],
  "concepts": [
    {
      "id": "concept-1",
      "title": "成本绩效指数",
      "source_questions": ["q-1"],
      "one_liner": "CPI 用于衡量成本效率。",
      "cornell_note": {
        "pairs": [{"cue": "CPI 的公式是什么？", "note": "EV/AC。"}],
        "summary": "CPI 是挣值与实际成本之比。",
        "pairing_status": "paired"
      },
      "teaching_evidence_ids": ["evidence-1"]
    }
  ],
  "teaching_evidence": [
    {
      "id": "evidence-1",
      "source_id": "book-1",
      "concept_ids": ["concept-1"],
      "status": "input_provided",
      "relation": "supports",
      "locator": {"page": 1, "excerpt": "成本绩效指数等于挣值除以实际成本。"}
    }
  ]
}
```

**第二步**，生成：

```bash
.venv/bin/python cli.py \
  --input /path/to/agent-content.json \
  --profile ruankao-xitixiangmu \
  --agent-content \
  --output /path/to/new-learning-package \
  --open
```

约束要点：

- `sources[].path` **必须相对 JSON 所在目录**；PDF 页码**从 1 开始**
- `source_file` / `page_no` / `material_id` 等旧字段会被**拒绝**
- 题目来源（question_bank）与教辅证据（teaching_material）是**两种不同关系**
- 代码会拒绝：坏形状、重复 ID、答案类型错误、未知或单向关联、越界物理页、不安全资源；质量门失败不发布

**第三步**，逐卡审校并记录 `concept.content_review`：

```json
{"reviewer": "agent", "status": "reviewed", "rationale": "本卡已对照《教材》第 111 页核验公式与单位口径"}
```
`rationale` 不能留空或写占位文字；`reviewed` 不能覆盖正文缺失或硬阻断。

写卡前阅读 [卡片编写规范](references/card-authoring.md) 与 [质量正反例](references/card-quality-examples.md)。先把题目要求归纳成可复用知识点，再收集证据，最后写卡。一道独立题可以对应一个知识点，但不能按题号机械建卡；把同一段解析复制到 takeaway、Cornell answer 和 summary 三处会触发阻断。

### 5.4 场景 C：案例题 / 混合包（r19 新增）

```bash
.venv/bin/python scripts/quick-pass.py \
  --input examples/cases/agent-content-mixed.json \
  --profile ruankao-xitongjicheng \
  --agent-content \
  --output ./case-demo-new --open
```

- 纯案例：`questions: []`，输入换成 `examples/cases/agent-content-cases.json`
- 案例字段：`id / original_number / source_id / source_pages / scenario / diagram_images / sub_questions[]`
- 小问答案三态：`verified`（已核对原文与归属）/ `missing`（缺失）/ `unresolved`（归属不明，必须写 `reason`）
- `generated_analysis`（Agent 解析）与 `reference_answer.text`（原文答案）**必须分开存**
- `calculation_steps` 每步要带 `input_basis`（来源 ID + 页码 + 节选）；只有原件明确给出才写 `score` / `scoring_points`
- 截图案例：原始 PNG/JPG/WebP 声明为 `question_bank` 来源、`source_pages: []`，案例页直接显示原图；**案例不能用 `collect --qid`**

### 5.5 场景 D：把对话里的截图/照片错题收录进来

1. 让 Agent 用自己的视觉能力读原图，识别题干、选项、可靠答案、可见的个人选择
2. 生成 v2 包：原图同时作为 `sources` 的 `question_bank` 和题目的 `diagram_image`
3. 先读学习页顶部的「当前 Profile」稳定 ID，**原样**传给 `--profile`
4. 收录：

```bash
python3 scripts/study-library.py collect /path/to/photo-question-package --qid photo-q-1
# 只有确实看到或用户确认了错误选择，才加 --picked B
```

没有 `--picked` 时只记录「用户标记为错题」，**不伪造一次作答**。

### 5.6 场景 E：打开已有包 / 换端口

```bash
.venv/bin/python scripts/study-library.py open /tmp/quick-pass-demo
# 端口被占用时：
.venv/bin/python scripts/study-library.py --port 8899 open /tmp/quick-pass-demo
```

- 包已生成但服务启动失败时，**只重跑这条命令**，不要重新生成、不要覆盖学习包
- 同一学习库目录存储学习记录；换端口后应使用新地址访问同一学习库。不要把不同的 `--library` 目录误认为同一份记录。
- `http://127.0.0.1:<port>/` 是学习库首页，列出所有已注册的学习包

### 5.7 场景 F：手机端打开

1. 电脑端执行 `study-library.py open <包目录>`，拿到 HTTP 地址。
2. 手机 Agent 须具备访问电脑本地回环服务的正式连接能力，再通过该连接打开完整学习包；`127.0.0.1` 不能供另一台设备直接访问。
3. 宣称移动端成功前应实际确认：协议不是 `file://`、页面 Profile 正确、Logo 与至少一张教辅/原页图的 natural dimensions 非零、PDF 的 `HEAD` 响应含 `Accept-Ranges: bytes`、手机与电脑错题数量一致

### 5.8 诊断与兼容入口（非默认路径）

```bash
# 把单个 PDF/DOCX/TXT/MD 展开成中间材料（PDF→pages.json + 逐页图 + agent-question-contract.json；
# DOCX→document-content.json + embedded-images/；TXT/MD→全文与分块）
python3 scripts/quick-pass.py --input /path/to/bank.pdf --output /tmp/bank-handoff --import-only

# Agent 回填后校验源哈希与物理页，产出 questions.json
python3 scripts/quick-pass.py --input /path/to/bank.pdf --output /tmp/bank-handoff \
  --import-only --resume-agent-contract
```

```bash
# 兼容路径：对已结构化的选择题 JSON 调用外部模型生成知识内容（会产生费用）
export QPE_LLM_API_KEY='你的 Key'
.venv/bin/python cli.py --input /path/to/my-questions.json \
  --profile ruankao-xitixiangmu --llm-config config.deepseek.example.json \
  --output /path/to/new-learning-package
```
Key 只放环境变量，**不要**写进 JSON、输出文件或聊天记录。

---

## 六、输出产物

| 路径 | 用途 |
| --- | --- |
| `web/index.html` | 本地学习网页入口（含内联数据与本地资源） |
| `data/questions.json` | 题目、答案、解析、题目↔考点关联 |
| `data/concepts.json` | 考点笔记、康奈尔笔记、考点↔题目关联 |
| `data/cases.json` | 案例背景、图表、全部小问、参考答案状态、生成解析与评分来源 |
| `data/methods.json` | 计算方法卡 / 答题方法卡及其与案例小问、考点的关联 |
| `data/sources.json` | Agent 内容入口声明的题库与教辅原文件清单 |
| `data/teaching-evidence.json` | Agent 内容入口声明的知识点↔教辅节选/物理页/区域关系 |
| `reports/quality-report.json` | 输入、关联、来源、内容问题的确定性检查 + Agent 审校状态 |
| `reports/usage-attempts.json` | 当前进程的模型调用事件与供应商 usage（不含 Key 与提示词） |
| `manifest.json` | profile、输入/配置摘要、文件哈希、时间、数量与质量状态；详细学习辅助覆盖率见质量报告 |

**交付前至少检查**：`manifest.json` 的 `structural_status` / `content_status` / `quality_status`、质量报告、题目与考点数量、关联入口是否可见、本地资源是否完整。

---

## 七、验证与故障处理

生成后检查 `manifest.json`、`reports/quality-report.json` 和页面中的题目、知识卡、关联入口与原页资源。演示包预期为 2 道选择题、2 张知识卡、0 道案例题和 0 张方法卡；它仅用于验证打包与呈现。实际内容还需 Agent 审校和浏览器检查。

若 `--open` 报端口占用，先确认该端口是否有其他服务。当前健康检查使用 Python `urllib` 访问 `127.0.0.1`；在设置 HTTP 代理的环境中，可让本机回环地址绕过代理后重试：

```bash
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
```

仍无法启动时，可以通过 `--port` 选用空闲端口；学习包已经成功生成时只需重试 `scripts/study-library.py open <包目录>`。运行项目测试可使用 `python -m pytest tests -q` 和 `node --test tests/*.cjs`，但测试结果不能替代真实材料审校与浏览器验收。

---

## 八、边界与不支持

- **只支持两个 profile**：`ruankao-xitixiangmu`（信息系统项目管理师·高级）、`ruankao-xitongjicheng`（系统集成项目管理工程师·中级）。**不能把中级资料放进高级 profile**
- **不支持**：旧 `.doc`、论文题、完整 WebApp 部署
- **案例题**只能通过 v2 `--agent-content` 流程生成
- 文档识别**没有独立语义解析器、没有隐藏 OCR 供应商分支**——原件交给 Agent；`--import-only` 只是诊断兼容工具
- 公式为纯文本（不加载 MathJax/KaTeX）、图表为节点/关系或说明文字（离线、零外部依赖）
- `--agent-content` 通过质量门**不等于内容语义正确**；fixture 生成 ≠ 真实模型生成 ≠ 缓存重跑，三者要分开报告
- **私有数据不要外发**：`~/.quick-pass-study/learning.sqlite3`、输出目录父级的 `.qpe-cache/`（可能含生成内容）、原始截图/照片、`--import-only` 交接目录

---

## 九、常见问题

**Q：为什么生成的知识卡被拒绝 / 标为待审？**
最常见是「同一段解析被复制到三处」（`CARD_TRIPLE_DUPLICATE`，硬阻断）或整字段占位。修法不是加字数或加更多 pair，而是**重新归纳知识点、独立写正文与自测**。

**Q：`--open` 报「端口已被占用」怎么办？**
换端口：`--port 8899`。若确实是旧版学习服务，新版本会明确提示「旧版学习服务不支持 XX；请换一个 --port」，不会给你一个无效地址。

**Q：直接双击 `web/index.html` 能用吗？**
能看，但只使用该文件的浏览器存储，**不能保证跨包继承错题**，并且 `file://` 下多文件存储行为由浏览器决定。正式入口永远是 `study-library.py open` 打印的 HTTP 地址。

**Q：重新生成学习包会丢错题吗？**
同一学习库目录、同一 profile 且内容匹配的选择题会继承作答与错题；**案例记录当前不跨包迁移**。

**Q：能开源发布吗？**
`LICENSE` / `NOTICE.md` 已按 Apache-2.0 就位，但用户导入的题库、真题、教材、生成的私有内容**不在授权范围**内。快照脚本 `tools/build_snapshot.py` 只打包 `SNAPSHOT_FILES.txt` 明确列出的源码文件，不含题库、缓存、Key 与私有配置。
