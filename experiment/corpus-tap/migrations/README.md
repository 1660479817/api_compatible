# 数据库

未上线环境 **只需一个文件**：

| 文件 | 用途 |
|------|------|
| [`schema.sql`](./schema.sql) | 全量建表（Tap 事实层 + Profile 分析 + 金库视图） |

## 复位（推荐）

```bash
export CORPUS_TAP_DATABASE_URL=postgres://corpus:corpus@127.0.0.1:5433/corpus?sslmode=disable
make db-reset
```

或：`./scripts/reset-db.sh`（优先 `DROP DATABASE` 重建；无权限时回退 `DROP SCHEMA`）。

本地 Homebrew Postgres 若 `corpus` 无 `CREATEDB`，可设超级用户 URL：

```bash
export CORPUS_TAP_DATABASE_ADMIN_URL="postgres://$(whoami)@127.0.0.1:5432/postgres"
```

## 仅初始化（空库、不 DROP）

```bash
psql "$CORPUS_TAP_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/schema.sql
```

`make db-init` 同上。
