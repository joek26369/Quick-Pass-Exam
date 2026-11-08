# 计算方法覆盖与漏项修复

编写或修复含题目的 Agent 内容时读取本规范。新 `--agent-content` 输入必须提供全题分类清单；旧包仍可阅读，缺少清单的独立验收返回 limited，不得宣称计算方法完整。fixture/旧 LLM 路径不作此承诺。

## 从题目建立清单

逐题阅读所有选择题和案例小问（包括背景、图表、原答案），再声明 calculation、non_calculation 或 unresolved；不要仅靠关键词、章节标签分类，不要截取前 N 题。数据在图中也需要判断。非计算题必须填写理由；不要求每一道题都有计算方法卡。重复来源记录保留稳定 ID，覆盖数量分别报告记录数与去重题型数。

一问可需要多个算法。按适用条件、输入、输出与求解步骤决定拆分：关键路径、三点估算、完工概率、赶工费用、资源优化不能只因属于进度管理就用一个大标题代替各自方法。相同算法的条件分支可放在一张卡，但必须讲明选择依据。不规定固定卡片数量。

检查实际题库是否包含：EVM 指标、ETC/EAC 预测假设、预算与储备、关键路径/浮动时间、提前滞后关系、三点估算、概率、赶工、资源峰值优化、EMV、合同结算、质量成本、质量指标、沟通渠道、投资回收期。此清单仅是遗漏提示；不得给没有对应题目的类型凑卡。三角与贝塔等模型不得无依据默认。

## JSON 契约

顶层新增：

```json
{
  "method_coverage": {
    "schema_version": "quick-pass-method-coverage-v1",
    "items": [
      {
        "question_id": "case1-q1",
        "classification": "calculation",
        "reason": "要求按两个方案的概率与净收益计算 EMV 并作决策",
        "input_excerpt": "计算两种方案的预期货币价值",
        "requirements": [
          {"type_id": "emv", "method_id": "method-emv", "reason": "卡中概率加权步骤对应本问的两种收益情景，先统一成本口径"}
        ]
      },
      {
        "question_id": "q2",
        "classification": "non_calculation",
        "reason": "要求识别合同类型，不要求付款计算",
        "requirements": []
      }
    ]
  }
}
```

- `question_id` 覆盖全部选择题和案例小问，恰好一次，不能用案例父 ID。
- calculation 的 `input_excerpt` 必须是当前题干或案例背景的原文子串，用来防止审查脱离当前输入。图表先忠实转录到题干/背景并保留图和出处。摘录命中不证明语义正确。
- 每个 requirement 使用一个自定义稳定 `type_id`，对应方法的 `calculation_type`；`reason` 说明该方法如何满足本问条件。同问同类型不重复登记。
- unresolved 写明缺失条件与原因；检查阻止正式交付，须先核原件。缺少参考答案与题型无法判断是不同问题，不得为满足覆盖而猜答案。
- 每张 calculation 方法卡增加 `calculation_type`（单个类型字符串）、`assumptions`（明确假设）、`input_requirements`（非空字符串数组）。同时保留已有公式、非空步骤、单位、适用条件、来源 `case_basis`。公式/演示必须能回查可靠原题或教辅；教辅支持填真实 `evidence_ids`，没有教辅时不得硬挂无关证据。
- methods 新增可选 `question_ids`，用于选择题双向导航；案例沿用 `sub_question_ids` 和小问 `method_ids` 双向一致。概念关联或前置知识链接不能替代 requirements 中的实际算法覆盖。
- 可选 `methods[].qp_steps` 按 [qp-steps.md](qp-steps.md) 的输入/输出/生成规则编写并验证；分步数据不是方法覆盖或语义正确的证明。无块输入保持无块，旧块 basis_hash 不一致删除，不增加付费请求。
- 同一类型能否合并仍须 Agent 审查正文；程序不自动理解公式。不能用一个泛化类型名称把本应拆开的算法重新并回大卡。

## 检查与补报

生成前失败报告为 `<output>.method-coverage.json`，包含逐题缺口和 repair_instructions。全部通过后冻结 `data/method-coverage.json`，保存 `reports/method-coverage.json`。生成后再次执行分类/关联检查，并核对 HTML 内方法的公式、步骤、假设及关联是否与已审内容一致。独立验收：

```sh
python3 scripts/verify-package.py <学习包目录>
```

旧内容缺少清单时，需要补全审查后再用新版本生成；不允许删检查、改 passed 或把所有题标 non_calculation 来兼容。程序的 passed 只代表完整声明与结构一致，语义审查仍由 Agent 承担，浏览器验收另行记录。

发现缺口后：保留原题/案例/考点/证据 ID 与学习记录，逐项补读原件、补方法、拆不合理合并、修关联，再在新目录生成。不能只改线上 HTML；agent-content 必须同步。按用户明确的原始范围扫描，不扩展范围。在替换原包前比较所有旧 ID、题数、答案状态，逐计算类型验收公式/假设/单位、题↔方法跳转和原页；复核学习库草稿、错题和作答记录。保持用户 URL 时遵循既有包替换流程，不清空数据库。

向用户补报：每种计算类型及题数、覆盖的方法、拆分前后对应、具体补读来源、结构检查结果、语义抽查和浏览器证据、仍未解决事项。不得把结构通过称为全部内容正确，不得把 missing/unresolved 答案改成 verified 来过关。
