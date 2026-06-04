# Corpus Tap

插在 **客户端与 New API 之间** 的透明代理：照常转发推理请求，同时把对话 **原文** 按平台用户落盘，供后续清洗与微调。

用户侧只需把 API 入口从 New API `:3000` 改为 Tap `:8443`（路径与 Token 不变）。

---

## 做什么 / 不做什么

| 做 | 不做 |
|----|------|
| 采集 `POST /v1/chat/completions`、`/v1/messages`、`/v1/responses` 全文 | 抽问答对、打分、去重、领域分类 |
| 按 New API **`user_id`** 分桶存 gzip 原文 + PG 索引 | 替代 New API 计费 `logs` |
| 流式 SSE 重组后落盘；失败仍转发 | 热路径里调用 LLM |
| 最小脱敏（如 `Authorization`、常见密钥字段） | 画像 / 分析（见扩展槽，未实现） |

---

## 架构

```text
Agent  ──►  corpus-tap :8443  ──►  new-api :3000  ──►  上游
              │
              ├── PostgreSQL（索引）
              └── S3 或本地目录（正文）
```

计费与渠道统计仍在 New API；语料在 **独立库 + 桶**。

---

## 快速开始（本地开发）

**前提**：本机可访问 New API（或 `make smoke`）；PostgreSQL 用于元数据（分析依赖同库）。

### 1. 配置

```bash
cd experiment/corpus-tap
cp .env.example .env
# 分析（可选）：cp analysis/profile/.env.example .env.profile 并合并 LLM 变量
```

`.env` 至少：

```bash
CORPUS_TAP_UPSTREAM=http://127.0.0.1:3000
CORPUS_TAP_DATABASE_URL=postgres://corpus:corpus@127.0.0.1:5433/corpus?sslmode=disable
CORPUS_TAP_DEV_USER_ID=1
CORPUS_TAP_LOCAL_DATA_DIR=./data
```

### 2. 首次建库

```bash
make db-reset           # 空库或复位：migrations/schema.sql，见 migrations/README.md
```

### 3. 启动 Tap

```bash
make build
export $(grep -v '^#' .env | xargs)
./bin/corpus-tap
```

### 4. 启动分析（可选，需 LiteLLM）

```bash
make build-profile
export CORPUS_PROFILE_LLM_BASE=http://127.0.0.1:4000
export CORPUS_PROFILE_LLM_API_KEY=sk-operator-analysis
export CORPUS_PROFILE_DATABASE_URL="$CORPUS_TAP_DATABASE_URL"
./bin/corpus-profile
```

无 Tap / Docker 时，可用种子数据跑通 Profile 批处理（需本机 Postgres + LiteLLM）：

```bash
make db-reset dev-local
```

另开终端发一条推理（示例）：

```bash
curl -sS -X POST http://127.0.0.1:8443/v1/messages \
  -H "Authorization: Bearer <你的平台 Token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-test","max_tokens":32,"messages":[{"role":"user","content":"hi"}]}'
```

**如何确认采到了**：在 `./data/<deployment_id>/user_id=1/dt=…/<exchange_id>/` 下应有 `client_request.json.gz`（及非流式时的 `upstream_response.json.gz` 或流式的 `assembled_stream.txt.gz`）。

---

## 生产部署要点

| 项 | 建议 |
|----|------|
| Token → 用户 | `CORPUS_TAP_NEWAPI_MYSQL_DSN` 只读查 `tokens` 表（**不要** 用 `DEV_USER_ID`） |
| 元数据 | `CORPUS_TAP_DATABASE_URL`（PostgreSQL） |
| 正文 | `CORPUS_TAP_S3_*`；或仅开发用 `CORPUS_TAP_LOCAL_DATA_DIR` |
| 部署 ID 稳定 | `CORPUS_TAP_DEPLOYMENT_ID=<固定 UUID>`，避免重启换前缀 |
| 长流式 | `CORPUS_TAP_SSE_SPOOL_DIR` + `CORPUS_TAP_SSE_SPOOL_MEM_BYTES` |
| 旁路 | 紧急时 `CORPUS_TAP_MODE=proxy-only`（只转发，不采） |

数据库初始化或复位：

```bash
export CORPUS_TAP_DATABASE_URL=postgres://corpus:corpus@127.0.0.1:5432/corpus?sslmode=disable
make db-reset
```

本地 Homebrew Postgres 若应用用户不能 `DROP DATABASE`，可设超级用户连接（见 [`migrations/README.md`](./migrations/README.md)）：

```bash
export CORPUS_TAP_DATABASE_ADMIN_URL="postgres://$(whoami)@127.0.0.1:5432/postgres"
```

合并到中转站 Compose：[`deploy/docker-compose.snippet.yml`](./deploy/docker-compose.snippet.yml)（对外 **8443**）。

---

## 配置

完整说明见 [`DESIGN.md` §13](./DESIGN.md#13-配置)。常用变量：

**必填**

| 变量 | 说明 |
|------|------|
| `CORPUS_TAP_UPSTREAM` | New API 根 URL，如 `http://new-api:3000` |

**生产推荐**

| 变量 | 说明 |
|------|------|
| `CORPUS_TAP_NEWAPI_MYSQL_DSN` | 只读 MySQL，解析 Token → `user_id` |
| `CORPUS_TAP_DATABASE_URL` | PostgreSQL |
| `CORPUS_TAP_S3_BUCKET` / `CORPUS_TAP_S3_REGION` | 对象存储 |
| `CORPUS_TAP_DEPLOYMENT_ID` | 固定部署 UUID |
| `CORPUS_TAP_ADMIN_KEY` | 内网统计 / 导出 API |

**仅开发**

| 变量 | 说明 |
|------|------|
| `CORPUS_TAP_DEV_USER_ID` | 无 MySQL 时把所有请求记到同一用户 |
| `CORPUS_TAP_LOCAL_DATA_DIR` | 本地语料目录（默认 `./data`） |

**可选**

| 变量 | 说明 |
|------|------|
| `CORPUS_TAP_MODE=proxy-only` | 只转发 |
| `CORPUS_TAP_SSE_SPOOL_DIR` | 大 SSE 落盘缓冲 |
| `CORPUS_TAP_NEWAPI_DIGEST` | 锁定的 New API git commit（运维标记） |

模板： [`.env.example`](./.env.example)

---

## 内网运维 API

需设置 `CORPUS_TAP_ADMIN_KEY`，请求头：`X-Corpus-Admin-Key: <key>` 或 `Authorization: Bearer <key>`。

```bash
# 用户统计
curl -sS -H "X-Corpus-Admin-Key: $CORPUS_TAP_ADMIN_KEY" \
  "http://127.0.0.1:8443/internal/stats?user_id=100"

# 导出 JSONL 清单（供清洗管道）
curl -sS -H "X-Corpus-Admin-Key: $CORPUS_TAP_ADMIN_KEY" \
  "http://127.0.0.1:8443/internal/export?user_id=100" > exports.jsonl
```

健康检查：`GET /healthz`、`GET /readyz`（不鉴权）。

---

## 测试

| 命令 | 场景 |
|------|------|
| `make test` | 单元测试 + **mock 上游 E2E**（无需 Docker / New API） |
| `make test-integration` | MySQL `tokens` 表解析（需 `127.0.0.1:13306` 或 `CORPUS_TAP_TEST_MYSQL_DSN`） |
| `make smoke` | Docker 全栈：mock New API + MySQL + PG + 一次真实 POST |
| `make dev-seed` | 写入一条 `http_exchange` + `./data` 样例 blob |
| `make dev-local` | `dev-seed` + 启动 `corpus-profile` 跑一轮 `/internal/run` |

New API 版本与表结构约定：[`testdata/NEWAPI_BASELINE.md`](./testdata/NEWAPI_BASELINE.md)

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [**DESIGN.md**](./DESIGN.md) | **采集 + 存储**（`corpus-tap`，规则、表结构、导出契约） |
| [**analysis/ARCHITECTURE.md**](./analysis/ARCHITECTURE.md) | **分析层**（多策略架构；与 Tap 分界） |
| [**analysis/profile/DESIGN.md**](./analysis/profile/DESIGN.md) | 策略 **profile**（`corpus-profile`，Stage1/2） |
| [中转站语料采集插件设计](../../docs/experiment/中转站语料采集插件设计.md) | 实验点索引、Compose、G2 出站、画像扩展槽 |
| [AGENTS.md](../../AGENTS.md) | 仓库协作与复审触发 |

实现状态：**L0 采集存储 S0–S5** · **L1 Profile 策略 P0–P1** · **L2 金库视图**（[`analysis/ARCHITECTURE.md`](./analysis/ARCHITECTURE.md)）。建库：`make db-reset`；分析：`make build-profile`。
