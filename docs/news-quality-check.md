# Initial news collection and discovery check

Checked on **2026-09-17 at 08:07 UTC** against a local installation, after bounded
feed polling. These are observed counts, not uptime, relevance-precision or
forecast-accuracy measurements. No model requests or human evidence approvals
were created by this check.

Event: `fed-october-2026`, definition version 2, policy `fed-macro-v1`.
The read-only `news_quality` command sampled up to 100 saved items per source.

| Source | Accepted in latest feed | Rejected | Duplicate feed entries | Saved items sampled | Discovery candidates |
| --- | ---: | ---: | ---: | ---: | ---: |
| Federal Reserve monetary policy | 15 | 0 | 0 | 17 | 6 |
| Federal Reserve speeches | 15 | 0 | 0 | 15 | 12 |
| Federal Reserve testimony | 15 | 0 | 0 | 15 | 1 |
| BEA releases | 47 | 1 | 0 | 47 | 5 |
| BBC Business | 44 | 0 | 4 | 44 | 1 |
| CNBC Economy | 30 | 0 | 0 | 30 | 7 |
| **Total** | **166** | **1** | **4** | **168** | **32** |

- All accepted entries in these polls had a publication timestamp. This does not
  establish that the publisher's date is correct or that every article is fresh.
- The two additional saved Fed monetary-policy items came from earlier collection;
  accepted feed counts are not counts of newly inserted database records.
- BEA had one entry without a valid absolute HTTP(S) article link; it was rejected.
  BBC had four repeated article identities within its feed; they were deduplicated.
- Both BLS adapters remained paused after earlier HTTP 403 connectivity checks;
  this run did not poll them. No access restrictions were bypassed.
- All 32 candidates remained **pending review** within a dossier containing ten
  linked contracts. Twenty-six had priority 20 and six had priority 10. Priorities
  express review order only. Broad economic language can produce weak matches;
  an operator still needs to check the event date, original text and contract rules.
- Official/media provenance stays separate. The added BEA, BBC, CNBC and testimony
  feed entries do not imply full article or attachment capture. See
  [source coverage](news-sources.md) and [body capture limits](official-evidence.md).

To take a new snapshot with the databases available:

```sh
docker compose exec backend python apps/backend/manage.py news_quality --event fed-october-2026
```

This command reads stored collection state; it does not poll publishers. Services
were temporarily started for verification and stopped afterward. Continuous
collection and longer observation are needed before evaluating operational reliability.

## 中文说明

本次是本地实际采集与候选匹配检查。六个启用来源的最近订阅响应共接受 166 条，
拒绝 1 条无效链接，去重 4 条；包含此前保存条目后，抽样共 168 条。系统按内容规则
筛出 32 条候选，归入包含 10 份合约的美联储事件档案，全部仍待人工审核。

这些数字用于检查采集与匹配流程，不能代表长期稳定性、关联准确率或预测能力。
媒体摘要不会自动变成官方证据；“直接相关”和“支持某个合约结果”分别审核。
本次未调用付费模型，检查完成后恢复服务停止状态。
