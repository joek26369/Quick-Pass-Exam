# 固定样本

这些文件是仓库验收用的极小自编样本，覆盖软考高项风格的选择题、选项分析、记忆提示、题目与考点关联、教辅节选与物理页关联，以及公式、表格和图片夹具。

两道演示题的题干、选项和答案已由用户于 2026-09-20 审阅确认；这不是官方真题，也不等于概念笔记或教辅关联经过人工审校。`teaching-sample.pdf` 是本仓库自编的两页显示夹具，仅用于核对节选卡、物理页缩略图和点击查看原版页面，不是教材依据。

- `questions.json`：题目输入。
- `concepts.json`：概念产物。
- `learning-package-input.json`：`--fixture` 模式可直接使用的合并输入。
- `agent-content.json`：符合 `quick-pass-agent-content-v2` 的 Agent 内容交接示例，可用 `--agent-content` 运行严格质量门。
- `assets/evm-flow.svg`：本地手写 SVG 夹具。
- `assets/teaching-sample.pdf`：自编两页教辅显示夹具。

`learning-package-input.json` 只用于 `--fixture` 演示。真实 Agent 交接应使用
`"schema_version": "quick-pass-agent-content-v2"`，并通过
`cli.py --agent-content` 运行严格质量门。该命令不调用外部 LLM/OCR，也不替代
题目或概念内容的人工审阅。视觉资源不可用时应保留文字降级并在报告中说明。

当前预览已用 r16 重新打包。因这些概念未附逐卡审校记录，页面和清单明确标为“内容待审校”；接口示例能打包不等于内容已通过审校。
