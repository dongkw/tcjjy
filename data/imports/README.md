# 手工导入数据目录

当前文件来自券商持仓截图，先作为后续导入真实影子账户的输入。

## 文件

- `real_account_summary.csv`：账户总资产、现金、仓位等摘要。
- `real_positions.csv`：真实持仓明细。
- `real_watchlist.txt`：由当前持仓生成的股票池，后续可追加自选股。
- `watchlist_all.txt`：用户自选股全量去重列表。
- `watchlist_daily_default.txt`：默认盘前扫描列表，先取全量前 30 只。
- `watchlist_summary.md`：自选股整理说明。

## 注意

- `symbol` 是根据股票名称推测的代码，导入前需要确认。
- `buy_logic` 和 `invalidation_point` 目前为空，后续需要补充，否则卖出评估只能偏预评估。
- `account_id` 暂定为 `real_shadow`，表示真实账户的本地影子账本，不连接券商、不自动实盘交易。

## 导入命令

```powershell
python .\import_real_account.py --trade-date 2026-07-06
python .\database.py reconcile --strict
python .\database.py summary --limit 10
```

导入后可以在 Web 工作台查看：

```text
http://127.0.0.1:8000/accounts
http://127.0.0.1:8000/positions
```
