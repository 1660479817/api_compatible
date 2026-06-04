# ai.oai.red 源评估报告

| 项目 | 内容 |
|------|------|
| **报告文件** | `ai.oai.red-源评估报告-2026-06-04.md` |
| **评估对象** | 上游源 `ai.oai.red`（`experiment/user-side/sites.json`） |
| **站点 ID** | `ai.oai.red` |
| **OpenAI Base** | `https://ai.oai.red/v1` |
| **Anthropic Base** | `https://ai.oai.red` |
| **评估方法** | [用户侧三层评估法](../experiment/EC2-用户侧隔离实验点设计.md#21-三层评估法) |
| **评估环境** | LiteLLM relay（`http://127.0.0.1:4000/v1`）；`maas.py assess-source` 自动生成 |
| **评估日期** | 2026-06-04 |
| **测试结果** | `Layer1=PASS; Layer2=PASS; Layer3=PASS; smoke=PASS` |

> **测试范围**：站点 `ai.oai.red`；Layer 2 探测模型 `gpt-5.5`；Layer 3 Agent `opencode`；smoke_mode `relay`。

---

## 1. 执行摘要

| 层 | 判定 | 说明 |
|----|------|------|
| **1 平台链接** | PASS | platform PASS; catalog PASS (listed, 5 ids); docs_only: `gpt-5.4-mini-openai-compact` |
| **2 基础协议** | PASS | profile `openai` |
| **3 指定 Agent** | PASS | `opencode` · relay_mode `passthrough` · result `OK` |
| **4 smoke** | PASS | status=PASS; executed 4/4 PASS; 1 SKIP; smoke_mode=relay |

---

## 2. 第 1 层 — 平台链接

| 检查项 | 结果 |
|--------|------|
| Platform link | PASS |
| Catalog verdict | PASS |
| `GET /v1/models` | HTTP 200 · **1852.0 ms** |
| Catalog 分支 | **listed** |
| Catalog 条数 | 5 |

**Catalog ids**：

- `gpt-5.5`
- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.5-openai-compact`
- `gpt-5.4-openai-compact`

**supported_models（文档）vs catalog**：

- `gpt-5.4`：in both
- `gpt-5.4-mini`：in both
- `gpt-5.4-openai-compact`：in both
- `gpt-5.5`：in both
- `gpt-5.5-openai-compact`：in both
- `gpt-5.4-mini-openai-compact`：docs only

---

## 3. 第 2 层 — 源原生 wire

Protocol profile：**openai**（OpenAI-compatible）

| 模型 | Wire | 端点 | 耗时 | 结果 | 协议面 |
|------|------|------|------|------|--------|
| `gpt-5.5` | chat | `/v1/chat/completions` | 4513.3 ms | OK | shape=ok, usage=ok, stream=ok |
| `gpt-5.5` | responses | `/v1/responses` | 3415.5 ms | OK | shape=ok, usage=ok, stream=ok |

**Wire 汇总**（protocol scope，任一模型 OK 即记 yes）：

- OpenCode: **yes**
- Codex: **yes**

**Layer 2 判定**：PASS

---

## 4. 第 3 层 — LiteLLM relay

拓扑：Agent → `http://127.0.0.1:4000/v1` → `https://ai.oai.red/v1`

| 项 | 值 |
|----|-----|
| Agent | OpenCode (`opencode`) |
| Model | `gpt-5.5` |
| Wire | `/v1/chat/completions` |
| Relay 模式 | passthrough |
| 耗时 | **3628.8 ms** |
| 结果 | **OK** |

**Relay 协议面**： shape=ok, usage=ok, stream=ok

**Layer 3 判定**：PASS

---

## 5. 第 4 层 — Agent smoke

Agent `opencode` · smoke_mode `relay` · expected_model `gpt-5.5` · executed 4/4 PASS · 1 SKIP

| ID | 必选 | 耗时 | 判定 | API model | 自报 model | reason | 输出摘要 |
|----|------|------|------|-----------|------------|--------|----------|
| `model_probe` | 是 | 6877.3 ms | PASS | gpt-5.5 | ChatGPT | generic self-report 'ChatGPT' | {"model":"ChatGPT","release_date":"unknown","knowledge_cutoff":"2024-06"} |
| `explain` | 是 | 3711.8 ms | PASS | gpt-5.5 | — | — | An API gateway is a single entry point that routes client requests to the right backend services. It often handles cross-cutting tasks like authentication, rate limiting, logging, and response transformation. |
| `structured` | 是 | 4296.8 ms | PASS | gpt-5.5 | — | — | {"status":"ok"} |
| `code` | 是 | 3147.2 ms | PASS | gpt-5.5 | — | — | ```python def add(a, b): return a + b ``` |
| `tool` | 否 | 0 ms | SKIP | — | — | skipped (agent_only; smoke_mode=relay) |  |

**Smoke 判定**：PASS

---

## 6. 复现

```bash
cd experiment/user-side
source .env
python3 lib/maas.py assess-source --site ai.oai.red --agent opencode --write-report
# 含 smoke：
python3 lib/maas.py assess-source --site ai.oai.red --agent opencode --smoke --write-report
```

机器可读结果：`.runtime/` 下同日前缀 `*-assess-*.json`。

---

## 参考

- [CONFIG.md](../../experiment/user-side/CONFIG.md)
- [报告命名规范](./README.md#源评估报告命名)
