# Corpus Tap — 分层架构（采集存储 × 分析策略）

> **模块根目录**：[`experiment/corpus-tap/`](../)  
> **L0 采集 + 存储**：[`../DESIGN.md`](../DESIGN.md)（`corpus-tap`）  
> **L1 分析平面**：本文  
> **L2 金库出口**：[`migrations/schema.sql`](../migrations/schema.sql) 内 `v_gold_*` 视图  
> **策略 profile**：[`profile/DESIGN.md`](./profile/DESIGN.md)

### 文档元信息

| 项 | 内容 |
|----|------|
| **编写日期** | 2026-06-04 |
| **状态** | **本阶段完成**：L0 契约对齐、Profile P0–P1、平台 registry + 金库视图 |
| **复审触发** | 新增分析策略、事实层契约变更、金库出口语义变更 |

---

## 1. 三层数据平面

| 层 | 组件 | 职责 |
|----|------|------|
| **L0 事实** | `corpus-tap` | 原文 + `http_exchange`；热路径无 LLM、无结论 |
| **L1 分析** | `corpus-profile` 等 | 策略流水线；写策略结论表 |
| **L2 资产** | `v_gold_*` 视图 | 金库准入；RAG/SFT/运营只读视图 |

```text
Client → corpus-tap → PG + S3（事实）
              ↓ 只读
         corpus-profile（strategy_id=profile）
              ↓
         v_gold_rag_chunks / v_gold_sft_candidates
```

---

## 2. 目录与二进制

| 路径 | 二进制 |
|------|--------|
| `cmd/corpus-tap/` | `corpus-tap` :8443 |
| `cmd/corpus-profile/` | `corpus-profile` :8444 |
| `internal/analysis/shared/` | 闸门、SSE 文本提取 |
| `internal/analysis/profile/` | Profile 策略 |
| `analysis/` | 架构与各策略 DESIGN |

---

## 3. L0 事实层契约（摘要）

- 流式对象 `assembled_stream.txt.gz` = **原始 SSE**（非纯文本）；语义还原在 `analysis/shared`。
- 分析增量：`skipped_reason` / `store_error` 为空，且 `client_request_uri` 非空。
- `enrich_failed` 且无 `user_id` → **无** `http_exchange` 行。

全文：[`DESIGN.md`](../DESIGN.md) §9、§16。

---

## 4. 分析策略注册（`analysis_strategy`）

| 列 | 说明 |
|----|------|
| `id` | `strategy_id`，如 `profile` |
| `storage_model` | `dedicated_tables`（默认）或未来 `unified_conclusions` |

**定稿（本阶段）**：Profile 使用 **独立表**（`exchange_quality`、`user_profile`、`curated_chunk`…），即 `strategy_id=profile` 的专用命名空间。新策略 **不得** 复用这些表；在 registry 登记后使用 `compliance_*` 或统一结论表。

已登记：

| strategy_id | storage_model | 进程 |
|-------------|---------------|------|
| `profile` | `dedicated_tables` | `corpus-profile` |

---

## 5. 事实游标（`analysis_fact_cursor`）

| 项 | 说明 |
|----|------|
| `id` | 固定 `global`，全策略共享 |
| `last_exchange_created_at` | 本批 Profile 处理的最大事实时间 |

用途：运维观测与后续调度优化；**待分析队列**仍以「无 `exchange_quality` 行」为准（支持重跑）。

---

## 6. Profile 策略（已实现）

| Stage | 输出 |
|-------|------|
| Stage1 | `tier`、`curated_chunk`、`sft_candidate` |
| Stage2 | `cohort`、`profile_json` |

详见 [`profile/DESIGN.md`](./profile/DESIGN.md)。

---

## 7. L2 金库出口（视图）

| 视图 | 准入条件 |
|------|----------|
| `v_gold_rag_chunks` | `cohort=gold` ∧ `tier=A` ∧ `rag_indexable` ∧ `llm_status=ok` |
| `v_gold_sft_candidates` | 上列 + `sft_eligible` ∧ `trainable_as_sft` |

`corpus-profile` 导出 API 读上述视图；下游 ETL **应优先读视图**，而非裸表。

---

## 8. 建库与构建

```bash
make db-reset          # 空库或复位：migrations/schema.sql
make build build-profile
```

| DDL | 内容 |
|-----|------|
| [`schema.sql`](../migrations/schema.sql) | Tap 事实层 + Profile 表 + registry、fact cursor、`v_gold_*` |

---

## 9. 本阶段验收（已完成项）

- [x] Tap 与 Profile 进程/Token 隔离  
- [x] L0 流式语义在 DESIGN 与 ARCHITECTURE 中对齐  
- [x] 规则闸门 + Stage1/2 LLM（Profile）  
- [x] 金库导出视图 + API 读视图  
- [x] `analysis_strategy` + `analysis_fact_cursor`  
- [ ] 生产环境真实用户金库 → RAG 试点（需运营数据）  
- [ ] 第二分析策略（合规/主题，按需）  

---

## 10. 下一阶段（可选）

1. 选一高活用户：Tap 采数 → `corpus-profile` → 导出 `v_gold_rag_chunks` → 向量库试点。  
2. 新策略：在 registry 登记 + 独立表 + `analysis/<id>/DESIGN.md`。  
3. Prompt 升级：`DELETE FROM exchange_quality WHERE prompt_version <> $new` 后重跑（见 profile DESIGN §11）。

---

## 参考

- [`profile/DESIGN.md`](./profile/DESIGN.md)  
- [`../README.md`](../README.md)
