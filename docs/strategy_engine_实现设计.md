# strategy_engine 实现设计

> 目标：把《股票投资决策引擎（AI执行版 v2.0）》中的 A-G 闸门规则代码化，输出可复现、可审计、可扩展的评分、闸门结论和最终建议。
>
> 本文档是后续代码实现前的工程规格，不直接替代原规则文档。若规则口径冲突，以原决策引擎为准，并在本模块中记录版本号。

---

## 1. 设计目标

`strategy_engine` 负责做三件事：

1. 读取单只股票 JSON 数据底稿和人工补充参数。
2. 严格按 A-G 闸门顺序执行规则，硬否决命中时短路停止。
3. 输出机器可读 JSON 和人类可读 Markdown 结论，包含评分、证据、缺失数据和触发规则。

第一版重点不是“预测收益”，而是把已有规则变成稳定、可复查的判断流程。

---

## 2. 非目标

第一版不做以下事情：

- 不接入自动交易。
- 不直接替用户生成买卖指令。
- 不用大模型补全缺失财务数据。
- 不把公告标题关键词当作最终事实。
- 不强行自动判断闸门 F 的投资逻辑、催化剂和证伪信号。
- 不把评分当成买入理由；硬否决优先级永远高于评分。

---

## 3. 推荐目录结构

```text
src/
└── ai_trader/
    ├── strategy_engine/
    │   ├── __init__.py
    │   ├── models.py          # 输入、输出、闸门结果数据结构
    │   ├── context.py         # 数据读取、字段访问、缺失值收集
    │   ├── engine.py          # 总调度：A-G 顺序执行与短路
    │   ├── gates/
    │   │   ├── __init__.py
    │   │   ├── gate_a.py
    │   │   ├── gate_b.py
    │   │   ├── gate_c.py
    │   │   ├── gate_d.py
    │   │   ├── gate_e.py
    │   │   ├── gate_f.py
    │   │   └── gate_g.py
    │   ├── scoring.py         # 信心评分、风险扣分、仓位调整
    │   ├── valuation.py       # 年化回报、压力测试、触发价反算
    │   └── report.py          # Markdown/JSON 输出格式化
    └── ...

scripts/
└── run_strategy_engine.py     # CLI 入口

tests/
└── strategy_engine/
    ├── test_gate_a.py
    ├── test_gate_c.py
    ├── test_valuation.py
    └── test_engine_flow.py
```

兼容入口可后续放在项目根目录：

```text
strategy_engine.py
```

---

## 4. 输入设计

### 4.1 机器数据输入

主要输入为现有脚本生成的单票 JSON：

```powershell
data/stock_json/stock_data_601138.json
```

核心字段来自：

- `meta`
- `quote`
- `technical`
- `financial`
- `announcements`
- `engine_flags`
- `data_gaps_for_engine`

### 4.2 人工补充输入

由于 A-G 闸门中有大量“需人工确认”的条件，建议增加一个可选补充文件：

```text
data/strategy_inputs/strategy_input_601138.yaml
```

建议结构：

```yaml
mode: buy                 # buy | hold
period: middle            # short | middle | long
stock_type: growth        # stable | growth | cyclical | turnaround | unknown

account:
  capital_yuan:
  risk_per_trade_pct: 1.0
  current_position_pct:
  cost_price:

valuation:
  current_eps:
  eps_year3_estimate:
  target_pe_conservative:
  target_pe_base:
  pe_5y_median:
  pb_10y_percentile:
  dividend_yield_pct:

manual_checks:
  distress_turnaround: false
  major_holder_reduction_unexplained:
  regulatory_investigation:
  non_standard_audit_opinion:
  fundamental_improvement_for_price_surge:
  short_term_catalyst:
  medium_term_quantified_assumption:
  long_term_compounding_basis:
  receivable_or_inventory_risk:
  goodwill_risk:
  chip_red_signal_has_disproof_logic:

logic:
  thesis:
  catalyst:
  catalyst_deadline:
  disproof_fundamental:
  disproof_price:
  disproof_event:
```

原则：

- JSON 是客观数据输入。
- YAML 是人工判断和估值假设输入。
- 所有人工字段必须进入最终报告，不能和自动字段混在一起。

---

## 5. 输出设计

### 5.1 机器可读 JSON

建议输出：

```text
data/strategy_reports/strategy_result_601138.json
```

核心结构：

```json
{
  "schema_version": "strategy_engine_result/v1",
  "rule_version": "decision_engine_v2.0",
  "generated_at": "2026-07-03T18:00:00+08:00",
  "code": "601138",
  "name": "工业富联",
  "mode": "buy",
  "period": "middle",
  "final_decision": "watch",
  "confidence": "low",
  "score": {
    "total": 42,
    "quality": 12,
    "valuation": 8,
    "technical": 6,
    "risk_penalty": -10,
    "data_completeness": 26
  },
  "hard_reject": false,
  "stop_at_gate": null,
  "gates": [],
  "position": {},
  "missing_required_fields": [],
  "manual_review_required": [],
  "risk_notes": []
}
```

### 5.2 人类可读 Markdown

建议输出：

```text
data/strategy_reports/strategy_report_601138.md
```

Markdown 内容遵循原决策引擎第 10 节模板，并额外附加：

- 规则版本。
- 数据生成时间。
- 自动判断字段列表。
- 人工输入字段列表。
- 触发的规则编号。
- 缺失字段清单。

---

## 6. 闸门执行模型

每个闸门返回统一结构：

```python
GateResult(
    gate="A",
    title="前置硬否决",
    status="pass",             # pass | watch | reject | data_missing | manual_required
    hard_reject=False,
    score_delta=0,
    confidence_delta=0,
    position_multiplier=1.0,
    triggered_rules=[],
    evidence=[],
    missing_fields=[],
    manual_review=[]
)
```

总调度规则：

1. 按 A -> B -> C -> D -> E -> F -> G 顺序执行。
2. `hard_reject=True` 时立即停止。
3. `data_missing` 不等于硬否决，但最终建议不得高于 `watch`。
4. `manual_required` 不等于硬否决，但必须写入报告。
5. 评分只用于信心和排序，不覆盖硬规则。

---

## 7. 决策枚举

买入评估：

```text
buy       买入
watch     观望
reject    不买入
```

持仓评估：

```text
hold       持有
reduce     减仓一半
clear      清仓
```

建议在代码中使用英文枚举，报告层再翻译为中文，避免内部逻辑混用字符串。

---

## 8. 缺失数据处理

缺失数据分三类：

| 类型 | 处理 |
|------|------|
| 必需数据缺失 | 最终建议最高 `watch`，报告列入 `missing_required_fields` |
| 可选数据缺失 | 保守处理，报告列入 `manual_review_required` |
| 人工判断缺失 | 该闸门返回 `manual_required`，最终建议最高 `watch` |

第一版建议把以下字段视为买入评估必需：

- 股票代码、名称、当前股价。
- 用户周期或默认周期。
- 近 3 年营收、归母净利润、扣非净利润。
- 毛利率、净利率、ROE、资产负债率。
- 近 3 年经营现金流/净利润。
- 非周期股：当前 PE、目标 PE、未来第 3 年 EPS 假设。
- 周期股：当前 PB、近 10 年 PB 分位。
- 闸门 F 的三段式逻辑，至少包含基本面、价格、事件三类证伪。

---

## 9. A-G 闸门实现拆分

### 9.1 闸门 A：前置硬否决

可自动化：

- A-2：`engine_flags.a2_deducted_profit_negative_2y`
- A-4：`engine_flags.chase_high_1m_over_80_pct`

需人工确认：

- A-1：减持是否大幅、是否无合理解释。
- A-3：监管立案、非标审计意见。
- A-4：股价暴涨是否有基本面改善。

实现建议：

- 普通股命中 A-2 直接 `reject`。
- 若 `manual_checks.distress_turnaround=true`，A-2 不硬否决，但必须进入困境反转分支。
- A-4 涨幅可自动判定，基本面改善必须来自人工补充或明确财务改善规则。

### 9.2 闸门 B：周期与意图匹配

可自动化：

- 读取 `meta.requested_period` 或人工 `period`。
- 检查短线技术面、中线财务改善、长线盈利质量的辅助指标。

需人工确认：

- 短线 1 个月内催化剂。
- 中线 1-2 年量化假设和跟踪指标。
- 长线商业模式、竞争格局和复利基础。

实现建议：

- 缺周期时默认 `middle`，但最终建议最高 `watch`。
- 周期匹配失败返回 `reject`。
- 周期信息不足返回 `manual_required`。

### 9.3 闸门 C：基本面硬否决

可自动化：

- C-1：扣非净利润连续 2 年低于净利润 50%。
- C-2：年归母净利润低于 5000 万。
- C-3：`engine_flags.c3_ocf_low_3y`
- 最近一年现金流异常的信心降级。

需扩展数据：

- C-4：应收账款/营收、存货/营收。
- C-5：商誉/净资产。
- C-6：监管处罚、造假、非标意见。

实现建议：

- C-1、C-2 对困境反转股不直接硬否决，转入 D 的反转估值。
- C-3 普通股硬否决。
- C-4/C-5 数据缺失时不默认通过，记录为人工复核项。

### 9.4 闸门 D：类型与估值

稳定价值股/成长股：

- 计算 3 年预期年化回报率。
- 计算零增长压力测试。
- 根据普通股票 8%、高波动/小盘/强周期/困境反转 12% 门槛判断。
- 不达标时反算触发价格或所需 EPS 增速。

周期股：

- 检查 PB 近 10 年分位是否 `<=30%`。
- 检查利润/ROE 是否历史高位。
- 商品价格、库存、产能等先作为人工输入。

困境反转股：

- 使用正常化 EPS。
- 必须有反转驱动力、时间表和证伪信号。

实现建议：

- D 是第一版最容易产生争议的模块，所有估值假设必须原样输出。
- 缺目标 PE、未来 EPS 或 PB 分位时，不得输出 `buy`。
- “成长股重估例外”单独做成 `valuation_profile=base_case_exception`，并自动降低仓位。

### 9.5 闸门 E：筹码风险过滤

可自动化或半自动：

- 公告标题中的减持、回购、监管关键词。

需扩展数据：

- 股东户数变化。
- 融资余额变化。
- 北向资金变化。
- 解禁日程。

实现建议：

- 红色信号且无清晰证伪逻辑，返回硬否决。
- 橙色信号不硬否决，但下调仓位。
- 两个及以上橙色信号，最高只能 `watch` 或观察仓。

### 9.6 闸门 F：三段式逻辑

第一版建议不自动生成逻辑，只做结构化校验：

- `logic.thesis` 非空。
- `logic.catalyst` 非空。
- `logic.catalyst_deadline` 非空。
- `logic.disproof_fundamental` 非空。
- `logic.disproof_price` 非空。
- `logic.disproof_event` 非空。

实现建议：

- 证伪信号三类缺任一类，最终建议最高 `watch`。
- 完全写不出证伪信号，返回硬否决。
- AI 后续可参与解释，但不能替代硬校验。

### 9.7 闸门 G：技术面与仓位

可自动化：

- 短线：`above_ma20 && ma20_slope_up`
- 中线：`above_ma60 && ma60_slope_up`
- 大跌日禁追：`engine_flags.big_down_day_over_5_pct`
- 追高降级：`chase_high_1m_50_to_80_pct`、`change_60d_pct > 80`
- 止损幅度：`max(结构止损距离, 1.5 * ATR / 当前价)`

需人工或后续增强：

- 平台突破、回踩、修复买点。
- 周线 MACD。
- 月线 20 月均线。
- 结构止损位。

实现建议：

- 技术面不通过时，基本面再强也最高 `watch`。
- 大跌日试错仓不得超过计划仓位的 `1/3`。
- 仓位计算和仓位调整因子必须逐项输出。

---

## 10. 评分建议

评分只用于信心评级、批量排序和报告可读性，不用于覆盖硬规则。

建议总分 100：

| 模块 | 分值 | 说明 |
|------|------|------|
| 数据完整度 | 20 | 必需字段齐全、人工输入齐全 |
| 基本面质量 | 20 | 利润、现金流、ROE、盈利稳定性 |
| 估值吸引力 | 20 | 年化回报、安全边际、压力测试 |
| 周期匹配 | 10 | 周期、催化剂、验证指标匹配 |
| 筹码风险 | 10 | 红橙黄信号扣分，回购小幅加分 |
| 逻辑可验证性 | 10 | 三段式逻辑和证伪信号质量 |
| 技术买点 | 10 | 均线、趋势、买点、止损距离 |

硬否决命中时：

- 仍可输出已计算分数。
- `final_decision` 必须为 `reject`。
- `score.total` 不得用于翻案。

信心评级建议：

| 条件 | 信心 |
|------|------|
| 无硬否决，必需数据齐全，分数 >= 75 | 高 |
| 无硬否决，分数 55-74 | 中 |
| 数据缺失明显、人工项较多、分数 < 55 | 低 |
| 硬否决命中 | 低 |

---

## 11. 仓位计算建议

基础公式：

```text
风险仓位上限 = 单笔可承受账户亏损% / 止损幅度%
最终单票仓位 = min(风险仓位上限, 30%)
```

调整因子：

| 条件 | 因子 |
|------|------|
| 高波动/小盘/强周期/困境反转 | `0.5` 或降低风险预算到 `0.5%` |
| D 仅基准档达标 | `0.5` |
| 任一筹码橙色信号 | `0.67` |
| 两个及以上筹码橙色信号 | 最高观察仓 |
| 自由现金流持续为负且资本开支扩大 | `0.67` |
| 近 60 日涨幅 > 80% | `0.67` |
| 左侧试错或大跌日试错 | 首仓不超过计划仓位 `1/3` |

输出时拆分：

- 理论风险仓位。
- 单票上限。
- 调整因子。
- 最终仓位上限。
- 首仓建议。
- 加仓条件。

---

## 12. CLI 设计

建议命令：

```powershell
python .\scripts\run_strategy_engine.py .\data\stock_json\stock_data_601138.json `
  --input .\data\strategy_inputs\strategy_input_601138.yaml `
  --out-dir .\data\strategy_reports
```

可选参数：

```text
--mode buy|hold
--period short|middle|long
--format json|md|both
--strict              # 缺人工项时报错，不生成结论
--rule-version v2.0
```

第一版默认：

- `--format both`
- 缺人工项仍生成报告，但最终建议最高 `watch`
- 不连接网络

---

## 13. 测试策略

优先做单元测试，不依赖实时数据源。

必测场景：

1. A-2 扣非净利润最近两年为负，普通股直接不买入。
2. A-2 命中但 `distress_turnaround=true`，允许进入后续流程。
3. C-3 经营现金流/净利润连续 3 年低于 0.5，硬否决。
4. 非周期股缺未来第 3 年 EPS，最终不能买入。
5. 年化回报率 >= 门槛，D 通过。
6. 年化回报率处于观望区间，反算触发价。
7. 闸门 F 缺证伪信号，最终不能买入。
8. 大跌日禁追，只能观察仓或试错仓。
9. 硬否决短路后，不继续执行后续闸门。
10. 输出 JSON schema 稳定。

测试数据建议使用手工构造的小 JSON，不直接依赖 `data/stock_json` 的实时样本。

---

## 14. 分阶段落地计划

### 第 1 阶段：引擎骨架

- 定义 `StrategyInput`、`GateResult`、`StrategyResult`。
- 实现 A-G 闸门调度与硬否决短路。
- 实现 JSON/Markdown 输出。
- 不追求规则全覆盖，先保证流程稳定。

### 第 2 阶段：确定性规则

- 实现 A-2、C-1、C-2、C-3。
- 实现非周期股估值公式和零增长压力测试。
- 实现技术面基础判断和仓位公式。
- 加单元测试。

### 第 3 阶段：人工输入闭环

- 增加 YAML 补充输入。
- 实现闸门 B、E、F 的人工字段校验。
- 报告中区分自动证据和人工假设。

### 第 4 阶段：数据源扩展

- 近 5 年 PE 中位数。
- 近 10 年 PB 分位。
- 应收账款、存货、商誉、净资产。
- 股东户数、融资余额、北向资金、解禁。
- 公告原文链接和公告日期过滤。

### 第 5 阶段：批量评分

- 支持股票池批量执行。
- 输出 CSV 排序结果。
- 按硬否决、数据缺口、评分、估值触发价筛选。

---

## 15. 优化建议

1. 规则版本化：每次修改 A-G 规则都要记录 `rule_version`，报告里保留版本。
2. 输出可追溯：每个结论必须带字段路径，例如 `financial.annual_last_3[0].ocf_to_net_profit`。
3. 自动和人工分层：自动数据、人工假设、AI解释三层必须分开。
4. 缺失数据不静默：任何影响买入结论的缺口都要压低最终建议。
5. 先做确定性规则：A-2、C-3、估值公式、技术均线、仓位公式优先，主观项后置。
6. 报告可复现：同一份 JSON + 同一份 YAML + 同一规则版本，必须输出同一结论。
7. 大模型只做解释层：AI 可以总结理由、发现矛盾、提醒缺口，但不能改写硬规则输出。

