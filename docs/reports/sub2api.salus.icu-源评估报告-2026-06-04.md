# sub2api.salus.icu 源评估报告

| 项目 | 内容 |
|------|------|
| **报告文件** | `sub2api.salus.icu-源评估报告-2026-06-04.md` |
| **评估对象** | 上游源 `sub2api.salus.icu`（`experiment/user-side/sites.json`） |
| **站点 ID** | `sub2api.salus.icu` |
| **OpenAI Base** | `https://sub2api.salus.icu/v1` |
| **Anthropic Base** | `https://sub2api.salus.icu` |
| **评估方法** | [用户侧三层评估法](../experiment/EC2-用户侧隔离实验点设计.md#21-三层评估法) |
| **评估环境** | LiteLLM relay（`http://127.0.0.1:4000/v1`）；`maas.py assess-source` 自动生成 |
| **评估日期** | 2026-06-04 |
| **测试结果** | `Layer1=PASS; Layer2=PASS; Layer3=PASS; smoke=NOT_RUN` |

> **测试范围**：站点 `sub2api.salus.icu`；Layer 2 探测模型 `gpt-5.5`；Layer 3 Agent `opencode`。

---

## 1. 执行摘要

| 层 | 判定 | 说明 |
|----|------|------|
| **1 平台链接** | PASS | platform PASS; catalog PASS (listed, 2 ids) |
| **2 基础协议** | PASS | profile `openai` |
| **3 指定 Agent** | PASS | `opencode` · relay_mode `passthrough` · result `OK` |
| **4 smoke** | NOT_RUN | NOT_RUN |

---

## 2. 第 1 层 — 平台链接

| 检查项 | 结果 |
|--------|------|
| Platform link | PASS |
| Catalog verdict | PASS |
| `GET /v1/models` | HTTP 200 · **2132.9 ms** |
| Catalog 分支 | **listed** |
| Catalog 条数 | 2 |

**Catalog ids**：

- `gpt-5.5`
- `gpt-image-2`

**supported_models（文档）vs catalog**：

- `gpt-5.5`：in both
- `gpt-image-2`：in both

---

## 3. 第 2 层 — 源原生 wire

Protocol profile：**openai**（OpenAI-compatible）

| 模型 | Wire | 端点 | 耗时 | 结果 | 协议面 |
|------|------|------|------|------|--------|
| `gpt-5.5` | chat | `/v1/chat/completions` | 15643.3 ms | OK | shape=ok, usage=missing, stream=ok |
| `gpt-5.5` | responses | `/v1/responses` | 9271.9 ms | HTTP 502 | shape=missing, usage=missing, stream=skip |

**Wire 汇总**（protocol scope，任一模型 OK 即记 yes）：

- OpenCode: **yes**
- Codex: **no**

**Layer 2 判定**：PASS

---

## 4. 第 3 层 — LiteLLM relay

拓扑：Agent → `http://127.0.0.1:4000/v1` → `https://sub2api.salus.icu/v1`

| 项 | 值 |
|----|-----|
| Agent | OpenCode (`opencode`) |
| Model | `gpt-5.5` |
| Wire | `/v1/chat/completions` |
| Relay 模式 | passthrough |
| 耗时 | **15382.3 ms** |
| 结果 | **OK** |

**Relay 协议面**： shape=ok, usage=zero, stream=ok

**Layer 3 判定**：PASS

---

## 5. 复现

```bash
cd experiment/user-side
source .env
python3 lib/maas.py assess-source --site sub2api.salus.icu --agent opencode --write-report
# 含 smoke：
python3 lib/maas.py assess-source --site sub2api.salus.icu --agent opencode --smoke --write-report
```

机器可读结果：`.runtime/` 下同日前缀 `*-assess-*.json`。

---

## 参考

- [CONFIG.md](../../experiment/user-side/CONFIG.md)
- [报告命名规范](./README.md#源评估报告命名)
