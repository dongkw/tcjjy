# AI 交易员项目

这是一个面向 A 股买入/持仓评估的本地决策辅助项目。当前阶段重点是：抓取单只股票的客观数据，生成结构化 JSON，再按文档中的决策引擎进行人工或 AI 辅助判断。

> 注意：本项目用于研究和辅助决策，不构成投资建议。后续接入自动交易前，需要补齐风控、回测、审计和人工确认流程。

## 目录结构

```text
.
├── README.md
├── requirements.txt
├── stock_decision_data.py              # 兼容入口：单票数据抓取
├── fetch_stock_codes.py                # 兼容入口：股票代码列表抓取
├── src/
│   └── ai_trader/
│       ├── __init__.py
│       └── stock_decision_data.py      # 核心：行情/财务/技术面/公告数据抓取
├── scripts/
│   └── fetch_stock_codes.py            # 工具脚本：生成 A 股代码池
├── data/
│   ├── 沪深A股代码（不含创业板）.csv
│   └── stock_json/
│       ├── stock_data_000969.json
│       ├── stock_data_600398.json
│       ├── stock_data_601138.json
│       └── stock_data_601857.json
└── docs/
    ├── agent.md
    ├── 股票投资决策引擎（AI执行版 v2.0）.md
    ├── 股票投资分析自查手册（逻辑修订版 v2.0）.md
    ├── 股票决策数据底稿_JSON通用模板.md
    ├── 股票决策数据底稿_字段说明与规则映射.md
    └── 自选股买入筛选报告_2026-07-02.md
```

## 快速开始

安装依赖：

```powershell
pip install -r requirements.txt
```

抓取单只股票数据：

```powershell
python .\stock_decision_data.py 601138 --period middle
```

默认输出：

```text
data/stock_json/stock_data_601138.json
```

刷新股票代码池：

```powershell
python .\fetch_stock_codes.py
```

默认输出：

```text
data/沪深A股代码（不含创业板）.csv
```

## 当前能力

- 抓取实时行情、估值、K 线技术指标、财务摘要、公告标题、股东户数、融资余额、北向持股和限售解禁。
- 生成单只股票的结构化 JSON 数据底稿。
- 生成机械判断标记，例如均线趋势、短期涨幅、扣非利润连续为负、经营现金流质量等。
- 配合 `docs/股票投资决策引擎（AI执行版 v2.0）.md` 执行买入或持仓评估。

## 后续演进建议

后续如果要实现“AI 交易员”，建议按下面顺序扩展：

1. `data_fetching`：稳定化数据源，增加缓存、失败重试、数据质量检查。
2. `strategy_engine`：把文档里的 A-G 闸门规则代码化，输出可复现的评分和结论。
3. `portfolio`：维护持仓、成本、仓位、止损线、交易日志。
4. `backtesting`：用历史数据验证策略胜率、回撤和仓位规则。
5. `risk_control`：加入单票上限、行业集中度、最大回撤、黑名单和硬否决规则。
6. `agent`：让 AI 只负责解释、归纳和复核，关键交易动作必须经过规则和人工确认。

## 主要文档

- [Agent 执行说明](docs/agent.md)
- [股票投资决策引擎](docs/股票投资决策引擎（AI执行版%20v2.0）.md)
- [数据字段与规则映射](docs/股票决策数据底稿_字段说明与规则映射.md)
