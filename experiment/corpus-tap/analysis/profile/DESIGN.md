# 分析策略：Profile（高质量语料 + 用户画像）

> **strategy_id**：`profile`（`analysis_strategy` 已登记）  
> **进程**：`corpus-profile` `:8444`  
> **架构**：[`../ARCHITECTURE.md`](../ARCHITECTURE.md) · **事实层**：[`../../DESIGN.md`](../../DESIGN.md)  
> **代码**：[`../../internal/analysis/profile/`](../../internal/analysis/profile/)

### 状态：**P0–P1 完成**（平台 registry + 金库视图已接入）

---

## 1. 目的

识别 **高质量交互**（`tier`）与 **高质量人群**（`cohort`），产出 **L2 金库** 资产（RAG chunk、SFT 候选）。N 维领域在 `profile_json.domains[]` 开放涌现。

---

## 2. 流水线

```text
http_exchange + blob
  → shared.RuleGate
  → canonical.Parser (+ shared.ExtractAssistantText for SSE)
  → Stage1 LLM → exchange_quality, curated_chunk, sft_candidate
  →（≥10 tier=A 或定时）Stage2 LLM → user_profile
```

| Stage | Prompt | 模型 |
|-------|--------|------|
| 1 | `worker/prompts/v1/stage1_quality_curation.md` | `CORPUS_PROFILE_LLM_MODEL_L1` |
| 2 | `worker/prompts/v1/stage2_user_profiling.md` | `CORPUS_PROFILE_LLM_MODEL_L2` |

---

## 3. 结论表（本策略专用）

| 表 | 说明 |
|----|------|
| `exchange_quality` | 每 exchange 结论（profile 命名空间） |
| `user_profile` | cohort + `profile_json` |
| `curated_chunk` / `sft_candidate` | L2 原料；导出经视图过滤 gold |

**禁止** 他策略写入上表；新策略用新表或未来 `unified_conclusions`。

---

## 4. L2 出口

| 方式 | 说明 |
|------|------|
| 视图 | `v_gold_rag_chunks`、`v_gold_sft_candidates`（[`schema.sql`](../migrations/schema.sql)） |
| HTTP | `GET /profile/export/rag|sft?user_id=`（读视图；需 `CORPUS_PROFILE_ADMIN_KEY`） |

---

## 5. 配置

[`.env.example`](./.env.example) — `CORPUS_PROFILE_*` 优先，DB/blob 可回退 `CORPUS_TAP_*`。

---

## 6. 运行

```bash
# 需 LiteLLM + schema（make db-reset）
make db-reset
export $(grep -v '^#' analysis/profile/.env.example | xargs)  # 与 Tap 库一致
./bin/corpus-profile
curl -X POST -H "X-Corpus-Admin-Key: $CORPUS_PROFILE_ADMIN_KEY" http://127.0.0.1:8444/internal/run
```

---

## 7. Prompt 升级 / 重跑（backfill）

1. 更新 `worker/prompts/<version>/` 与 `CORPUS_PROFILE_PROMPT_VERSION`。  
2. 删除待重算结论：`DELETE FROM exchange_quality WHERE prompt_version IS DISTINCT FROM 'v2';`（级联前先删 `curated_chunk` / `sft_candidate` 对应行，或按 `exchange_id` 清理）。  
3. `POST /internal/run` 触发；未删行的 exchange **不会** 自动重跑（无 `exchange_quality` 才入队）。

---

## 8. 验收

- [x] 闸门拒绝不调 LLM  
- [x] 导出仅 gold + tier=A（视图）  
- [x] SSE 经 `ExtractAssistantText`  
- [ ] 至少 1 个真实 gold 用户端到端 RAG 试点（运营侧）

---

## 参考

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
