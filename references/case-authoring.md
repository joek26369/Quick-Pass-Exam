# 案例题：原件到离线学习与自评

当输入包含案例、背景材料加多个小问、计算过程或主观简答时，阅读本说明。案例识别和答案归属由 Agent 完成，程序只检查结构、文件与引用。保持选择题原有路径；一份 v2 内容可以同时包含 `questions`、`cases`、`concepts`、`teaching_evidence`、`methods`，纯案例时 `questions: []` 合法。

## 先核原件，再写内容

1. 逐页记录案例原编号、完整背景、表格/图、续页及全部小问；保留小问原编号，另给全包唯一稳定 ID。背景摘要不能替代原材料。PDF 用物理页码，非 PDF 不编造页码。
2. 单独定位参考答案，逐问确认对应关系。不要按答案中的“一、二、三”机械拆分为子问，不要把整案答案或第一问答案复制给缺答案的小问。
3. `reference_answer.status=verified` 仅表示 Agent 已核对原文和归属，不表示程序或官方认证。缺失填 `missing`、空文本并省略未知来源；存在无法确定归属的候选填 `unresolved` 并写 `reason`，界面必须提示不是该问确定答案。
4. 原文答案保存在 `reference_answer.text`；Agent 解释放 `generated_analysis`。计算步骤逐项列明输入数据出处；核对条件、单位、中间值和图上的全部依赖边，不能只看最终答案吻合。
5. 只有原件明确给出，才写 `score` 和 `scoring_points`，并引用原文。不要从常识估计分值，也不要把自己的答案要点冒充官方评分细则。
6. 将子问关联到可复用知识点；知识卡沿用 [card-authoring.md](card-authoring.md)。方法卡应教会如何解决同类题，包含适用条件、步骤、依据和易错点；演示代入与通用方法分开。不依靠方法名称相同就合并有冲突的内容。

## v2 增量字段

可运行完整样例：`examples/cases/agent-content-cases.json`（纯案例）、`agent-content-mixed.json`（混合）。样例 PDF 为合成验收材料，不是真题或教材。

### cases[]

- `id`, `original_number`, `source_id`（question_bank）, `source_pages`（PDF 全部有关物理页；非 PDF 为 []）
- `scenario`：完整背景；`diagram_images`：对象列表，每项 `page` 指向案例原页；可按渲染器支持的 `path` 指定本地原图，保持原页可追溯。
- `sub_questions`：以下字段均按小问填写。
  - `id`, `original_number`, `type`, `question`, `source_pages`
  - `reference_answer`: `{status, text, sub_question_id, source_id?, source_pages?, reason?}`；`sub_question_id` 必须等于本小问 ID。verified 必须有明确来源和原文；unresolved 必须解释原因。
  - `generated_analysis` 字符串、`calculation_steps: [{text,input_basis:[{source_id,page?,excerpt}]}]`、`pitfalls: [字符串]`
  - `concept_ids`, `evidence_ids`, `method_ids`：已有对象的 ID 数组；缺支持可为空但需报告缺口。概念的 `source_questions` 可引用案例小问 ID，并与小问 `concept_ids` 双向一致。
  - 可选 `score: {max_points,source_id,source_pages,excerpt}`；`scoring_points: [{text,source_id,source_pages,excerpt}]`
- `coverage_review`: `{status,background_status,diagrams_status,expected_sub_question_ids,expected_diagram_pages,reason}`。前三个状态为 complete/incomplete/unverified；预期清单由 Agent 对照原件填写，不能从已生成的小问倒推后当作完整性证据。

### methods[]

`id`, `title`, `type`（calculation/answering）, `applicability`, `formula`, `substitution`, `units`, `pitfalls`（字符串数组）, `steps`（字符串数组）, `case_basis`（与 input_basis 相同结构）, `answer_structure`, `sub_question_ids`, `concept_ids`, `evidence_ids`。

不适用的字符串留空、数组留空。方法与子问双向关联；知识点和教辅关系必须真实，不能为提高覆盖率编造。方法依据及计算输入的 excerpt 必须来自所指原文，程序校验页码并不证明摘录与结论的语义关系。

## 生成与验收

```sh
python3 scripts/quick-pass.py --input <agent-content.json> --profile ruankao-xitongjicheng --agent-content --output <全新目录> --open
```

查看 `data/cases.json`、`data/methods.json`、`web/case-assets.json` 和质量报告的 `cases`。结构错误拒绝生成；缺失答案、覆盖缺口、分析/方法依据不足等进入待核验报告。程序不能发现 Agent 没记录的原件遗漏，必须保留逐页人工/Agent复核。

浏览器验收至少包括：计算案例、多问简答案例、跨页带图案例、缺失/错位答案案例、选择题与案例混合包。逐项检查：案例入口；输入→保存→刷新恢复；展开答案与生成解析的区分；三个自评状态；加入/移出待复习及复习入口；方法↔小问、方法↔知识卡；教辅节选和答案/数据/评分原页；小屏布局。错位答案不能呈现为确定答案，没有来源的评分字段必须被拒绝。

案例自评不写入选择题作答正确率，不自动算分。当前案例草稿和自评按学习包及小问保存；不会跨新生成包自动继承。`file://` 为浏览器本地存储；本地学习库使用 SQLite。保存失败必须可见，不用清空用户数据解决问题。旧服务不支持案例接口时，在新端口用新版服务打开已经生成的包；不要重新生成或强停旧服务。
