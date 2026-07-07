# 自选股整理

来源：用户从券商自选股截图整理出的股票代码。

## 数量

- 原始数量：142
- 去重后：140
- 重复代码：`600048`、`600406`

## 文件

- `watchlist_all.txt`：去重后的全量自选股，140 只。
- `watchlist_daily_default.txt`：默认盘前扫描列表，取前 30 只。
- `real_watchlist.txt`：当前真实持仓列表，4 只。

## 使用建议

当前本金有限，全量 140 只不建议每天盘前全跑。

第一版建议：

```text
盘前默认扫描 watchlist_daily_default.txt
研究或周末复盘再扫描 watchlist_all.txt
当前持仓继续用 real_watchlist.txt
```

后续需要把全量自选股拆成：

```text
A 类：近期真可能买，最多 10 只
B 类：观察池，最多 20-30 只
C 类：长期看看，不进入每日盘前扫描
```
