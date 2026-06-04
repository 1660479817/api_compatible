# Corpus Tap

New API 中转站 **语料采集插件**（透明反向代理）：全量采集主推理 POST，按 **New API 用户** 分区存储，供离线清洗；存储契约同时兼容后续画像/分析（扩展槽，见设计 §16）。

## 设计文档（采集 + 存储，完整稿）

**[`DESIGN.md`](./DESIGN.md)** — 模块定稿：目标、存储长期契约、规则 R1–R7、enrich、流式、数据模型、导出、配置、实施阶段、验收清单。

画像/分析 Worker：**不在** 当前实现范围；扩展槽见 `DESIGN.md` §16 与 [`docs/experiment/中转站语料采集插件设计.md`](../../docs/experiment/中转站语料采集插件设计.md) §8（索引）。

## 快速开始（本地）

```bash
cd experiment/corpus-tap
cp .env.example .env
# 编辑 CORPUS_TAP_UPSTREAM 指向本地或远程 New API

export $(grep -v '^#' .env | xargs)
go run ./cmd/corpus-tap
```

另开终端，经 Tap 访问（开发期需设置 `CORPUS_TAP_DEV_USER_ID`）：

```bash
curl -sS -H "Authorization: Bearer $NEWAPI_PROTOTYPE_TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8443/v1/models
```

采集 POST 推理请求后，在 `CORPUS_TAP_LOCAL_DATA_DIR` 下按 `user_id=<n>/dt=.../<exchange_id>/` 出现 `client_request.json.gz` 等文件。

## 迁移

```bash
psql "$CORPUS_TAP_DATABASE_URL" -f migrations/001_init.sql
psql "$CORPUS_TAP_DATABASE_URL" -f migrations/002_storage_extensions.sql
```

Compose 使用 `corpus-db` 时通常只自动执行 `001_init.sql`；生产需另跑 `002`。

## 环境变量（摘要）

| 变量 | 说明 |
|------|------|
| `CORPUS_TAP_UPSTREAM` | **必填** New API 根 URL |
| `CORPUS_TAP_NEWAPI_MYSQL_DSN` | 生产推荐：Token → `user_id` |
| `CORPUS_TAP_DEV_USER_ID` | **仅开发**：固定 `user_id` |
| `CORPUS_TAP_DATABASE_URL` | PostgreSQL 元数据 |
| `CORPUS_TAP_S3_*` / `CORPUS_TAP_LOCAL_DATA_DIR` | 对象存储（生产 S3，本地目录） |
| `CORPUS_TAP_MODE=proxy-only` | 只转发，不落库 |

完整列表见 [`DESIGN.md` §13](./DESIGN.md#13-配置)。

## Docker Compose

[`deploy/docker-compose.snippet.yml`](./deploy/docker-compose.snippet.yml) — 合并到中转站原型后，对用户暴露 **8443**。

## 实现进度

见 [`DESIGN.md` §15](./DESIGN.md#15-实施阶段与实现差距)（**S0–S5 已实现**）。

```bash
go mod tidy && make build && make test
```

### P1 冒烟 / 集成

| 命令 | 说明 |
|------|------|
| `go test ./...` | 含 `TestSmokeE2E`（mock 上游，无需 Docker） |
| `make test-integration` | MySQL `tokens` 解析（需 `13306` 或 `CORPUS_TAP_TEST_MYSQL_DSN`） |
| `make smoke` | Docker：mock New API + MySQL + PG + 一次真实 POST |

New API digest 锁定说明：[`testdata/NEWAPI_BASELINE.md`](./testdata/NEWAPI_BASELINE.md)

## 内网 API（需 `CORPUS_TAP_ADMIN_KEY`）

```bash
curl -H "X-Corpus-Admin-Key: $CORPUS_TAP_ADMIN_KEY" \
  'http://127.0.0.1:8443/internal/stats?user_id=1'
curl -H "X-Corpus-Admin-Key: $CORPUS_TAP_ADMIN_KEY" \
  'http://127.0.0.1:8443/internal/export?user_id=1' > exports.jsonl
```
