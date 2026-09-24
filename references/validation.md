# r19 案例学习与自评验收（2026-09-22）

> 许可状态更新（2026-09-23）：用户已明确选择 Apache License 2.0。本候选包现包含官方完整 `LICENSE` 和更新后的 `NOTICE.md`。下文关于“许可延期”“未新增 LICENSE”的文字是对应历史阶段的原始验收记录，已由本条更新取代，但保留用于说明当时的验证边界。用户导入资料与第三方内容不因该许可证自动重新授权。

基于用户指定的 quick-pass-candidate-20260922-r18.zip；84 个归档文件与修改前基线的 SHA-256 逐项一致。新增内容在独立 r19 目录，不覆盖 r18 或用户学习数据。

- 支持纯案例和选择题混合 Agent v2 输入；案例/子问来源、答案归属、评分出处、方法卡与知识卡/教辅关联进入确定性检查。
- 案例草稿、自评、展开状态和待复习使用独立 SQLite 表，按学习包和小问保存，不写入选择题尝试及正确率。当前不跨新生成包迁移案例记录。
- Python 全套 169 passed（含回环 HTTP、保存重启、非法字段、来源页越界、错位答案拒绝和案例-only/混合生成）；Node 20 passed；Skill 格式验证通过。PyMuPDF 仅有现有 SWIG 弃用警告。
- 五类合成验收输入位于 examples/cases：计算、多问简答、跨页带图、缺失/归属不明答案、混合学习包。4 案例/6 小问/2 方法卡，混合包另有 1 道选择题。缺失答案及证据缺口故意保留为 review_required，程序不声称语义核验。
- 浏览器已操作案例保存、自评、待复习、展开原文答案及生成解析、刷新恢复；教辅节选弹窗与 PDF 原页链接有效。跨页第 3/4 页图均实际加载为 1323×1872。方法与知识卡关联已检查，纯案例包隐藏选择题入口。375px 页面 scrollWidth=375。
- 浏览器截图接口多次超时，本轮未完成整页截图视觉验收；DOM 与交互结果不替代截图视觉验收。已查看离线原页 PNG，确认演示图中文字与依赖关系可辨。
- 全部验收仅使用合成原件、独立验收学习库，不代表真实案例题库已经识别或人工审校。原有学习库未修改，未调用模型提供方。

---

# 验证记录

日期：2026-09-21。此记录区分工程可运行与内容、视觉和发布资格。

## 2026-09-21：r16.1 错题本入口

将仅在刷题侧栏且有错题时出现的入口，改为顶栏始终可见的“错题本（数量）”和独立列表页。空列表有明确说明；本包错题进入对应题目，历史错题沿用原历史入口。没有修改学习记录。已同步当前真实试用页面和自编预览。

本轮定向验证：renderer/质量呈现19项Python测试通过；新增3项Node测试覆盖空状态、本包题跳转和历史入口。Ego实际点击顶栏进入空错题本，375px下scrollWidth=375且按钮选中状态正确。非空列表点击由Node行为测试覆盖，未向用户学习库写入模拟错题。

## 2026-09-21：r16 知识卡片质量修复

本次以 r15 候选的独立副本修复。Agent 入口必须读取卡片编写规范和正反样例，先归纳知识点、核对证据，再完成逐卡讲解和审校。复用原有概念/Cornell/证据字段，新增可选 `content_review`；旧 v2 可以读取，但缺审校记录时标为待审。

现有质量门新增确定性内容检查：三处整段复制（含尾部标点变体）和整字段占位阻断打包；长段近似重复或缺独立正文保留待审；合理短事实卡、一题一卡、缺教辅支持不因此硬失败。包级清单、报告和HTML分别显示结构状态、内容状态与证据缺口。Agent 自报审校不等于程序核验语义；浏览器检查仍需另记。显式 blocked/failed 包不能注册学习库。

本轮实际工程验证：Python 全套 **131 passed**，Node **13 passed**，Skill 官方格式校验 **Skill is valid**。此前沙箱禁止回环端口的5个测试已在允许绑定本机端口的环境重跑，并包含在131项通过中；仅有PyMuPDF/SWIG弃用警告。没有调用外部模型API。

实际旧输入回归：74张卡全部被判 `CARD_TRIPLE_DUPLICATE`，完整CLI退出码2，未生成学习包；原始输入未改动。报告仍记录30张无教辅证据、56张无直接教辅支持。Sol独立审查发现的尾部标点绕过已增加回归并修复；Luna发现的旧预览状态已通过重新打包修复。

当前自编预览明确为“内容待审校”，不是已验证的教材。Ego实际打开页面，确认包级/卡级待审提示，并点击教辅节选打开第1页弹窗，页面图加载成功，原文件链接指向 `#page=1`。375px页面无横向溢出；截图接口超时，截图视觉验收未完成。未经执行的浏览器/人类审查不会由生成器自动标为通过。

真实资料试用：Terra按修订Skill直接读取原件，为原卷空号1、44、45、50生成4题/3卡；主Agent对照原页纠正了网络图F最早开始时间（应为7），补齐变量解释，并将Agent推导移入generated_analysis.explanation，question.explanation只保留题库原解析。新规范要求独立复算中间值及原文/推导分层。区块链卡仅有题库依据，标limited；其余两卡分别关联《32小时通关》物理111/122页。最终包整体limited，0外部模型API调用，真实题库和包不纳入源码快照。

真实试用同时暴露高项默认profile不适用于中项资料，已新增仅用于Agent内容入口的ruankao-xitongjicheng，保留原高项profile及历史数据。浏览器确认中项标题、缺口提示、教辅111/122页弹窗与原文件页码链接、网络图原题页及作答后解析。真实样本仅覆盖上述4个空号，未全量重写74张卡，未声称完成人类审阅。

## 2026-09-21：扫描 PDF 原题页图像

此前 `source_page` 只产生复制后 PDF 的 `#page=N` 链接；题目若未显式填写 `diagram_image`，刷题页不显示扫描页中的网络图等原始图表。现复用教辅页面的本地 PyMuPDF 渲染：每道 PDF 来源题按已验证的物理页生成一份 160 DPI 离线原页图，同一原文件同一页只生成一次。没有独立题图时，刷题页默认展开整页图；有独立题图时保留它并把整页图作为可展开的核验入口。点击原页图可放大，同时保留原 PDF 跳页链接。历史错题快照也会保存该原页图的包内引用。整页可能包含多题，且可能增大学习包；Agent 应优先提供准确的独立图表裁图，并逐题核对图中数值和答案。

本轮工程验证：Python `92 passed`、Node `13 passed`、生成页脚本 `node --check` 和 Python 编译通过。用自编两页 PDF 生成 v2 学习包，原题第 2 物理页渲染为 1323×1871 PNG；Ego Lite 的页面结构和 DOM 均显示该图默认展开并已加载，375px 宽下图像约 295px、无横向溢出。Ego 截图调用连续超时，不能称已完成截图视觉验收；已单独查看 PNG，确认自编夹具第 2 页内容与页码一致。未取得用户这次导入的原始 Q44/Q45 PDF 与生成包，因此没有核实两题图表的裁切、数值、页码和答案；须用实际资料重新生成后逐题核对。

## 2026-09-21：Skill 自动打开学习库

默认 Skill 生成命令现使用 `cli.py --open`：先完成原有质量门和打包，再注册学习包；若同一学习库的本机服务已运行则复用，否则在后台启动；确认 `/api/health` 返回同一学习库标识后输出可打开的 URL。照片错题的 `collect` 也会自动启动或复用服务。端口上是其他服务或不同学习库时会明确失败，不把无效地址交给用户；已生成的学习包保留，可用 `study_server.py open` 单独重试。后台服务只继承必要的基础环境变量，不携带模型 Key。SQLite 是 Python 自带模块，用户不必另行安装数据库。Obsidian Vault 导出未实现，也不属于本轮范围。

本轮实际验证：Python `91 passed`（含真实本机进程自动启动、重复复用、端口冲突、CLI 输出 URL 后 HTTP 可访问），Node `13 passed`；Python 编译和 `git diff --check` 通过。没有用真实用户题库重新跑 Agent 语义识别；本轮也未重做 375px 浏览器视觉验收。

## 2026-09-21：持久错题本与 Agent 对话收录

作答记录从页面内存改为本机 SQLite 学习库。`study_server.py` 只监听 `127.0.0.1`，注册不同学习包后通过固定端口提供离线页面；同一考试 profile 下，以题干、选项和正确答案的规范化内容匹配题目，Agent 重新编号不影响继承。每次作答保存选项和对错；错题累计并按原 WebApp 的连续答对三次规则标记掌握。新包不含旧题时仍列出历史错题，可打开保存的题目、选项、解析与知识点说明。直接 `file://` 打开时仅使用当前文件的浏览器存储，不能保证跨包继承；页面明确显示模式和保存错误。

Agent 可把聊天中的截图/照片作为 `question_bank` 原件，识别题目和知识点后生成 v2 学习包，再用 `study_server.py collect` 收录到同一错题库。识别到个人错误选择时记录实际作答；未识别到时只标记错题，不伪造作答事件。自编图片夹具已走通 v2 打包、原图复制、注册与收录；这证明工程链路，不证明任意真实照片的识别质量。

本轮实际验证：Python `88 passed`、Node `13 passed`；Ego Lite 在本地 HTTP 学习入口将自编 CPI 题答错，页面显示持久错题，再刷新和打开第二个新包，作答与错题状态均恢复。另用自编图片题完成 `collect --picked B`，SQLite 中同时保有两条错题。跨浏览器/设备同步、真实用户照片语义审校和新布局的 375px 视觉验收尚未完成。SQLite 路径属于私人用户数据，不进入快照。

## 2026-09-21：题库、知识点与教辅证据完整链路

默认入口现为“原文件直交 Agent + 最小确定性预处理”。`quick-pass-agent-content-v2` 要求 Agent 显式给出 `sources`、题目、知识点、题目↔知识点关系、`teaching_evidence` 和知识点↔教辅证据关系。本地代码不切题、不猜答案、不生成知识点、不检索教辅，也不用关键词、向量或文件名推断关系；它只校验相对路径、原文件、SHA-256、PDF真实物理页、稳定 ID、双向多对多关系、枚举状态和归一化 region。

展示层从原 WebApp 的知识点教辅卡片和 `readerDialog` 交互抽取：知识点内显示教辅文件、物理页、Agent 选定节选和原页缩略图；点击后用静态 dialog 显示原版页面与节选，并提供包内 PDF 的 `#page=N` 链接。单机适配删除了账号、数据库、RAG/API、拖拽和裁剪依赖。`examples/assets/teaching-sample.pdf` 是自编两页显示夹具，不是教材证据。

本轮主控最终回归：Python `84 passed`，Node `13 passed`，Python 编译和 `git diff --check` 通过。Agent 入口只接受 v2；新增回归明确拒绝 v1 schema、顶层 `materials`、source 的 `source_file`、evidence 的 `material_id`，并要求题目↔知识点双向关系由 Agent 完整给出。使用 `examples/agent-content.json` 生成 v2 包，得到 2 道题、2 个知识点、2 个 source、2 条教辅证据、1 份复制后 PDF 和两个按引用页生成的原页 PNG；打包命令没有模型调用。Ego Lite 实际打开 `file://` 页面，确认知识点内节选卡可见；点击第1页卡片后 dialog 显示对应节选和 992×1404 原页图，随后新页实际打开包内 PDF `#page=1`。在 375×812 下确认第2页教辅卡和 dialog 可见、页面无横向溢出。该浏览器验收只覆盖本轮教辅卡、原页弹窗和本地PDF链接，不替代真实用户教辅内容的语义审阅。

## 2026-09-21：Agent-first 工作流边界

当前默认协作边界是：原文件直接交给 Agent；Agent 负责题目结构化、答案冲突标记、知识点/解析生成、教辅相关段落与页面选择，以及两组多对多关系。代码只负责确定性来源、契约、资源和渲染工作。Agent 内容只接受 `quick-pass-agent-content-v2` 和 canonical `sources`/`teaching_evidence` 字段；旧 Agent schema 和旧字段别名会直接拒绝。`--fixture` 仅用于仓库固定样例。

`--import-only` 仍可把 PDF 展开为逐页图片/原生文本、把 TXT/MD 展开为全文分块、把 DOCX 展开为正文/表格/嵌图引用，但它是诊断兼容入口，不是默认语义链路。文档路径不包含旧解析器或外部 OCR/结构化后备；历史真实模型/OCR结果不能扩展为当前 Agent 路径已经通过语义验收。

视觉能力缺失时，当前渲染器的验收目标是可读降级：公式保留纯文本，表格保留结构化文本/HTML，图表保留节点关系或说明，缺失资源明确报告。扫描页没有真实 OCR 结果时应停止或报告缺失；空文字层、fixture 或 mock 不算 OCR 通过。教辅卡及原页查看的桌面/375px验收已按上一节完成；答题、刷新重开和断网等更大范围仍按历史记录分别判断。

较早一轮完成并验证过诊断交接路径：文档可生成本地交接材料，Agent 回填题目后通过源文件哈希、PDF实际页数和答案契约生成 `questions.json`。该旧 Agent 内容契约现已删除，不再作为兼容入口。旧 `bank_parser.py`、专属测试、OCR配置及 `pdf-inspector` 依赖仍保持删除。

删除旧解析器后的主控最终回归：Python `65 passed`，Node `13 passed`，Python/JavaScript 语法检查和 `git diff --check` 通过。实际 CLI 分别完成 TXT、DOCX、文本 PDF、扫描 PDF 的 prepare → Agent 契约回填 → resume；随后用两题两概念 `examples/agent-content.json` 生成 `mode=agent`、模型为空、调用次数为 0 的学习包。候选快照为 67 个文件，并确认不含旧解析器、专属测试、OCR配置或 `pdf-inspector`。交接输出拒绝符号链接目标并采用排他或原子写入；DOCX 保留制表符、换行和内容控件，无法无损展开的公式、对象或嵌套表会进入 warnings。以上验证使用程序填写的最小契约验证链路，不等同 Agent 已实际完成四种格式的内容识别；也不包含新的真实模型、内容人工审校或浏览器视觉验收。

## 已实际执行

- 从显式抽取目录复制到新的临时目录，用 Python 3.13.3 新建独立 venv，安装 `requests` 与测试用 `pytest`；代码副本不含旧数据库、上传、历史缓存或私人配置。
- 旧基线曾记录 31 passed；后续章节记录各轮实际范围。不要用该历史数量代表当前源码。
- fixture 模式实际生成两题两概念的完整包；不是模型验证。
- 真实模型在空 HOME、显式环境注入 Key、新缓存下完成两题两概念生成。请求模型 `deepseek-v4-flash`，端点 `api.deepseek.com`；当前客户端未记录供应商响应中的实际模型名，不能断言底层模型版本。
- 最终真实生成：6 个独立调用 attempt，全部成功；12 条事件包括各调用的 sent/succeeded。供应商报告输入 9,862 tokens，其中缓存输入 7,424；输出 21,694 tokens。金额未核验。这些数字不包含首次调试运行，不能视为整个实施过程的总成本。
- 首次调试真实运行遇到 4096/8192 输出截断，重试成功；据此将 DeepSeek 示例上限改为 16384。初次运行未采集完整 usage，不补造成本。
- 原题四个选项与答案保留；生成辅助分析独立存储。模型生成来源建议隔离为未核验内容，未提供外部来源时不伪造页码或教材证据。
- 生成后 JavaScript 已运行 `node --check`。Skill frontmatter 通过 skill-creator `quick_validate.py`。
- 用户于 2026-09-20 明确确认两道演示题的题干、选项和答案已审阅可用于演示。概念笔记和模型输出不在该人工确认范围。

## 2026-09-20 继续验收

- 修复 Cornell 归一化：数组长度相等不再自动建立语义配对；显式配对仍保留，空pairs重复归一化不再丢失原数组。新增回归测试。
- 当时的真实预览概念笔记完成过独立AI复核及限定修订。2026-09-21 的 v2 教辅链路验收已用自编教辅夹具重新生成预览，因此旧 `model-concepts-original.json` 不再属于当前预览；人工确认仍不能由AI审阅替代。
- 自编两页PDF经PDF解析及渲染检查，第2页具有 `PAGE TWO`、`CPI = EV / AC`。自动契约测试确认源文件复制哈希不变和 `#page=2`，拒绝零/负/小数/布尔页码。尚不等同浏览器实际打开正确物理页。
- 用户明确要求许可确认“后续再说，先跳过”，因此本轮不新增LICENSE、不将许可确认当作工程验收前置；公开发布仍未执行。

## 浏览器验收状态

已打开原导出器同样本和独立学习页，读取实际页面树，并确认目录/公式文字/关联入口存在、375px页面宽度无横向溢出。首次生成页面曾有 JS 换行转义错误，已修复并重新检查脚本。

完整桌面/375px可视截图、实际点击答题/双向跳转、刷新重开及断网交互尚未通过。继续本轮时Ego同一空间仍截图超时；用户同意换浏览器后，Codex内置浏览器安全策略拒绝访问本地file://学习包，并明确禁止通过代理路径、其它浏览器或命令绕过。已停止该浏览器动作，没有改用HTTP/数据URL等绕过。PDF实际打开第2页仍未验收。需用户手动完成，或浏览器管理侧提供正式允许的验收方式；不能把静态契约检查当作交互通过。

## 呈现与边界

- 公式使用可读纯文本，不包含在线 MathJax/KaTeX；结构图提供明确文本降级。
- 本地图片（包含经检查的被动 SVG）复制进包；不能安全复制的资源显示不可用提示。
- 题干支持最小 pipe-table 渲染，其余 Markdown 仍有纯文本降级。
- 该阶段答题状态只在页面内存中；现已由上方 2026-09-21 持久错题本实现替代。
- 真实笔记仍需人工内容评估，不能把结构质量门当作语义真实性证明。
- 没有执行公开发布；许可证仍待权利人确认。

## 复核命令

```bash
python3 -m venv /tmp/qpe-check-env
/tmp/qpe-check-env/bin/python -m pip install -r requirements.txt pytest
/tmp/qpe-check-env/bin/python -m pytest tests -q
/tmp/qpe-check-env/bin/python cli.py --input examples/learning-package-input.json \
  --profile ruankao-xitixiangmu --fixture --output /tmp/qpe-new-demo
```

当前 `examples/preview/` 由 `examples/agent-content.json` 的 v2 自编题目、概念和两页教辅显示夹具生成，用于离线呈现验收；它不代表新一轮真实模型调用或真实教材语义验收。历史真实模型调用记录只保留在本文件前述记录中。

## 康奈尔笔记格式修复

用户指出预览只显示小结。现已在考点、题库解析和模型辅助解析中复用完整康奈尔组件：提示/自测、笔记/要点、底部总结；桌面两栏，600px以下纵向排列。显示已有全部cues/notes或明确pairs；独立数组不自动逐条配对。只有summary的旧数据保留小结并明确其余内容缺失，不生成虚构笔记。加粗与行内代码仅通过安全文本节点渲染。

实际验证：31项Python测试通过；`node --test tests/test_cornell_dom.cjs` 4项合成DOM单元测试通过，覆盖内容保留、明确配对、注入文本与旧数据；输出脚本 `node --check` 通过。DOM单元测试不是浏览器/视觉验收。尝试读取用户已打开的本地页仍被浏览器URL策略拒绝；桌面及375px截图未通过工具验收。预览重新渲染且manifest摘要已更新，题目和概念JSON未修改。

### 康奈尔逐行问答（2026-09-20）
两条预览概念按语义整理为各 6 组显式问答，左右同一行并加分隔线，移动端保留两列。生成提示词改用 pairs。Python 31 项、Node 5 项通过；未重跑真实模型，实际截图仍待验收。内容整理仍待人工审阅。

### 离线知识图谱（2026-09-20）
预览从文字降级改为离线图形：CPI 为 SVG 节点和有向边，干系人为带轴方向的权力/利益四象限。窄容器中的大图可横向滚动；原始节点/关系在折叠说明中保留。仅绘制输入中明确可解析的边，不推断缺失关系，不引入网络资源。Python 31 项、Node 8 项及生成脚本语法检查通过，覆盖 7 个 CPI 节点、6 条边和四象限策略位置。浏览器策略仍阻断本地页面访问，桌面/移动实际视觉待验收。

### 对比内容呈现（2026-09-20）
类型对比按现有类型名称前缀分组为「类型 / 判别或示例 / 关键规则」对照表，移动端改为带字段标签的卡片。易混对比用双概念标题和分段区别卡片，默认展开，可切换自测隐藏区别并逐卡揭示。未改动内容数据、未生成新口诀。Python 31 项、Node 10 项、页面脚本语法检查通过；包含分类分组与信息保留、自测显隐验证。实际桌面与移动浏览器视觉仍待验收。

### 最新继续验收（2026-09-20，r7）

- 真实模型生成路径新增严格 Cornell pairs 质量门；缺失、空字符串、null、数字、对象均不能冒充完整问答。fixture/legacy保留兼容。
- 最新源码：34 Python、10 Node检查通过；生成页面JS语法、Skill校验通过。
- 新提示词真实DeepSeek运行：独立代码副本、空HOME、新缓存，复用已隔离依赖venv。2题/2概念、每概念6组pairs；6成功调用、0失败，最新结构质量门通过。此前沙箱连接失败不计入这次成功统计。未记录账单金额，不以此证明语义正确。新产物未覆盖已整理预览。
- 图谱增加学习示意说明和未匹配关系提示。类型分类兼容中英文冒号。r6归档独立解压的31 Python/10 Node、fixture CLI和48文件清单已通过，不能混称为r7的归档结果。
- 仍待：实际桌面/375px浏览器阅读与答题、解析、双向跳转、错题/计数；刷新/关闭重开、断网交互；来源PDF实际第2页；当前修订笔记人工审阅。浏览器策略仍拒绝file页面，未用其他浏览器/代理绕过。许可按用户要求延期。

## 2026-09-21：已撤销的旧解析器候选验证

以下记录只说明本轮较早阶段曾验证过的供应商解析链。随后确认 Agent Skill 不应让高层解析器预先决定题目语义，因此 `vendor/bank_parser.py`、OCR 配置和相关依赖已从当前候选删除；下列命令结果不是当前运行方式，也不能用于宣称当前包仍提供这些能力。

`vendor/bank_parser.py` 从主项目复制并适配，不在运行时导入原项目。Word沿用原题库标题布局；PDF沿用pdf-inspector文本层判定、按页OCR、题块结构化、原图与页码定位。TXT/MD是复用原切题/结构化算法的新适配，不冒充主项目原先已支持。

在独立代码副本、空HOME和显式安装依赖的临时venv中实际验证：

| 输入 | 实际执行 | 结果 |
| --- | --- | --- |
| UTF-8 TXT | 真实结构化→真实知识生成→导出 | 2题/2概念，答案A/B，无伪造物理页 |
| DOCX | 原解析器纯抽取→真实知识生成→导出 | 2题/2概念，答案A/B，无伪造物理页 |
| 文本PDF | 原生文本提取→真实结构化→知识生成→导出 | 2题/2概念，页1/2，零OCR页 |
| 扫描PDF | 单次文档CLI完成两页真实OCR→结构化→知识生成→导出 | 2题/2概念，页1/2，2次OCR请求 |

前三种按import-only和生成两个CLI步骤验证；扫描PDF验证单入口自动串联。Markdown复用TXT同一入口且含固定夹具，本轮未额外调用真实模型验证MD后缀。四份包均通过当前结构质量门及manifest文件哈希校验。样本自编，未声明人工审校或官方材料；完整生成不证明语义真实。OCR未提供的usage/账单标为unknown，结构化和知识生成调用分别记录，调试失败不合并为成功次数。

实际发现并修复：扫描首页被旧封面启发式误跳过、DOCX中文同行题干丢失、缺题/空题及源答案冲突、TLS可信证书链、归档漏品牌图标。TLS始终验证证书。导入缓存与源副本只写隔离工作目录。无明确源答案时停止请求人工补充，不把模型解题冒充源答案。

出口补回原题和generated_analysis中的核心考点、计算步骤、知识拓展、方法论；答案冲突先警示、提交后披露；题干内图片通过安全本地复制；输入来源和旧references明确标为未额外核验。完整教辅检索/证据关联未实现。

该阶段当时记录为54项Python、13项Node检查通过；当前候选以文件顶部最新验证记录为准。真实浏览器桌面/375px、刷新/离线/PDF页实际点击仍未完成本轮工具验收；许可按用户要求继续延期。


## r18 learning support completeness (2026-09-22)

Adds per-card applicability decisions and package coverage for mnemonics, diagrams, principles, comparisons, practical study advice and examination focus. Legacy v2 stays readable but missing review information is not considered completed content. Actual content must match an included decision. A batch with no mnemonics or diagrams requests review rather than inventing content. Reports and the learning page display coverage; counts are not semantic proof.

Explicit learning_relations navigate between existing concepts; chapter order is not converted into prerequisites. Diagrams accept a caption explaining arrow semantics. Comparison tables omit the rules column if no row supplies it.

Verification: Sol ran 141 Python tests with loopback service tests in a permitted environment; the lead reran 19 renderer/quality tests after final UI changes and 19 Node tests passed. Known SWIG deprecation warnings remain. Private 75-question/62-card content and source PDFs are excluded from this archive. The real package remains limited because some teaching support is missing; original-source correctness is not certified by these tests. Lead browser checks confirmed network diagram, comparison table, mnemonic, source-page modal, explicit concept navigation, existing wrongbook and 375px document width.
