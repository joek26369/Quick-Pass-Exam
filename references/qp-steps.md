# 可选计算分步数据（qp-steps-v1）

仅为本次新编写的 calculation 方法卡提供 `methods[].qp_steps` 对象；由宿主 Agent 使用自己的模型编写，Skill 不增加任何模型调用。缺字段兼容旧输入，不补块；重打包已有 payload 不生成缺失块。已有 output 拒绝覆盖，不做跨包历史判新旧或增量 merge。

## 输入、输出与生成要求

输入依据是当前方法的完整 `title` 与非空纯文本/Markdown `formula`（不含「公式定义」标题）。公式应为一个节正文，不嵌入一级/二级标题；空公式或会拆节的公式只保留文字、不发布块。保留原题、适用条件、假设与单位，不能把合成演示说成原题答案。

输出字段是可选的 `qp_steps`，其完整 JSON 合同见 `schema/qp-steps-v1.schema.json`。`method` 必须与当前 `title` 完全一致；`provenance.generator` 填 `skill`，`source_questions` 填真实关联题目 ID，`generated_at` 填 ISO-8601 时间。`provenance.basis_hash` 必须使用同包 `qp_steps.basis_hash(title, formula)` 计算：两段分别按明确 ECMAScript 空白集合归一为单空格后去首尾空格，以一个 LF 分隔，再 UTF-8 SHA-256；不去 Markdown、不改标点、不做 Unicode 规范化。不要猜 hash。

对象最小形状示意（省略号为说明，不是可提交数据）：

```text
methods[i].qp_steps = {
  "schema": "qp-steps-v1", "method": methods[i].title,
  "kind": "method" 或 "trace", "view": "formula" 或 "table",
  "inputs": [{"id": "X", "label": "输入", "example": 2}],
  "steps": [{"id": "Y", "title": "计算", "explain": "说明", "expr": "X*2"}],
  "provenance": {"generator": "skill", "source_questions": [...],
                 "generated_at": "ISO-8601", "basis_hash": "64位hash"}
}
```

数据不是程序；只允许 Schema 的表达式、单层 choices、显示用 verdicts，无循环/动态执行。`method` 可改输入重算，`trace` 仅回放给定数字，换数字不能套用旧 trace。最多 40 个输入、80 步、64 KiB；每个 choices 组合的示例必须可计算且有限。

## 校验与持久化

`case_contract.validate_cases_methods` 在真实生成路径中校验可选字段；结构/表达式非法、method 不等于 title、非 calculation 卡、basis_hash 与当前文字不一致时，删除字段，保留文字，质量报告记录 `METHOD_QP_STEPS_DROPPED`。不修补过期 hash 让它假通过。旧 payload 无块不会自动补，旧块依据未变可保留、依据已变则删除。

通过的对象保存到 `data/methods.json`；静态 HTML 携带同一数据，不新增独立 Skill 播放器。导入 Web 时映射到 frontmatter `type: calc_method`、`method: title`、`## 公式定义` 原样公式和 `## 分步演示数据` 的 qp-steps 围栏；Web 信任边界再次校验，失败只省略块。浏览器播放器由 Web 的 qp-steps 播放链提供，不以 JSON 校验代替播放器验收。

源码、Schema、共享用例按 `qp-steps-source.json` 的逐文件 SHA-256 固定内容版本；更新时一起同步并重跑共享用例及解包测试。公开清单不包含内部仓库地址或提交元数据。纯标准库校验器不依赖 WebApp 路径/Schema 资源定位；WorkBuddy 与 Generic ZIP 都带源码和 Schema。共享测试用例保留在开发/源码快照，不进入运行发行 ZIP。

真实 BYOK、双路真题固定输出对照和同播放器验收须另附实际证据；合成用例通过仅代表结构/计算冒烟。
