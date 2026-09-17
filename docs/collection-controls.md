# Collection controls / 采集控制

Open **Admin → Collection controls** at `/admin/platform/controls/`.

在后台左侧选择 **采集控制**，即可分别设置行情开关与频率；页面下半部提供每个新闻来源的设置入口。

| Control | Scope | Allowed interval |
| --- | --- | --- |
| Polymarket / Kalshi | Each exchange independently; existing target selection is preserved | 15–3,600 seconds, default 60 |
| News source | Each registered feed; disabled sources also stop official document fetches | 300–86,400 seconds, default 900 |

行情：建议先使用 60 秒；新闻订阅：默认 15 分钟。修改需要填写原因，并记入操作审计。取消行情来源勾选后保存即可暂停，再次勾选保存即可恢复。历史与采集名单保留。新闻来源点击「设置来源」修改开关及间隔。

## Configuration and acknowledgement

- PostgreSQL stores runtime settings alongside the singleton collection plan. The first save activates runtime controls independently of managed market selection. Before activation, the form shows proposed defaults; the collector still uses its startup interval.
- An authorized, active staff account needs `markets.change_collectionplan` to edit market controls; news editing requires `research.change_evidencesource`. Organization ownership does not confer these permissions. Existing operator groups are not automatically granted the new market-control permission.
- Saves require a reason, use a row lock and reject stale form revisions. A plan revision and before/after audit event are committed together. A successful save means **requested**, not yet **applied**.
- The analytics worker publishes settings to Redis every iteration (normally ten seconds). Rust checks while idle every five seconds and between market requests. An in-flight exchange request or retry can delay application. The console shows the last fresh acknowledgement and revision; refresh to check it.
- Schema v2 adds required per-exchange `enabled` and `interval_seconds` controls. v1 plans and journals remain readable. Old collectors reject v2 rather than claim it has applied. Upgrade the collector before activating these controls.
- Pausing stops new market fetches after the collector applies it. An already-running request may finish, and already-collected durable batches may still be written and processed. Pausing does not delete historical data or disable analysis of existing batches.
- The last valid configuration is saved in the collector journal, including pauses. Missing or invalid Redis values retain it across restarts. Existing revision-conflict and rollback protections still apply.

页面的「采集器已生效」表示已确认配置版本，不等于交易所请求成功。请同时查看「数据采集」中的最新观测、错误和分析服务状态。服务离线时会显示等待确认，不会把“已保存”当成“已开启”。

## Frequency and freshness

Each market source has its own minimum interval between cycle starts. A switch/frequency change takes effect on the next configuration check and schedules the enabled source immediately. Slow responses, retries and serial processing can make the actual interval longer. The fixed 180-second data freshness policy remains unchanged: choosing a longer interval can make research indicators unavailable between observations. Pausing also breaks continuous analytical windows; resuming does not backfill missed data.

News intervals schedule feed polls through a shared queue; failures use exponential backoff. Official document revisits retain their independent daily schedule. Source edits invalidate in-flight feed and document leases, so responses under the previous source configuration cannot publish. `NEWS_FEEDS_ENABLED=false` remains a deployment-level gate and is shown in the console; source switches cannot override it.

## Service lifecycle

`market-data`, `worker`, and `news-worker` must remain running. Paused sources leave the service idle and available for admin resume. Compose uses `restart: unless-stopped` for these services. It recovers process exits while Docker is running; it does not override a manual stop or start Docker when the host is asleep/offline.

For initial deployment or recovery:

```sh
docker compose up -d --build market-data worker news-worker
```

For the development overlay, use the same Compose files as the existing deployment. Keep the collector volume: it contains configuration and pending observations. No Docker socket is exposed to Django. This control surface does not start Agent jobs or issue LLM requests.
