# New API 基线（Token / logs 集成）

Corpus Tap 的 MySQL enrich 与 [One API 系 `tokens` 表](https://github.com/QuantumNous/new-api) 兼容。

## 锁定 digest（P1）

实施或跑集成测试前，在仓库根执行：

```bash
./upstream/pull.sh newapi
cd upstream/newapi && git rev-parse HEAD
```

将输出写入环境变量（与 `tap_deployment.newapi_image` 对齐）：

```bash
export CORPUS_TAP_NEWAPI_DIGEST=<git rev>
export CORPUS_TAP_NEWAPI_IMAGE=<镜像 tag 可选>
```

## `tokens` 表（只读查询）

| 列 | 用途 |
|----|------|
| `key` | 平台 Token 字符串（与 Bearer 一致，支持 `sk-` 前缀变体） |
| `user_id` | 语料分桶 |
| `id` | `token_id` |
| `status` | `1` = 启用（其它值不解析） |
| `expired_time` | `-1` 永不过期；否则须 `> UNIX_TIMESTAMP()` |

## `logs` 表（异步 enrich）

按 `request_id` 匹配 `http_exchange.newapi_request_id`，回填 `enrich_json`。

列名依部署版本可能略有差异；变更 digest 后请跑：

```bash
make test-integration
```

## 集成测试 Schema

见 [`newapi_mysql_init.sql`](./newapi_mysql_init.sql)，由 `deploy/docker-compose.smoke.yml` 初始化。
