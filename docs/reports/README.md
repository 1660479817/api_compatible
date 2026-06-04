# 兼容性评估报告

本目录存放**具体站点 × Agent** 的测试结论与复现步骤（研究实证层）。  
研究总览与复现入口见根目录 [README.md](../../README.md)；文档导航见 [docs/README.md](../README.md)。  
E2E 全景见 [research/E2E原生兼容性全景.md](../research/E2E原生兼容性全景.md)。  
LLM API 网关技术栈见 [research/LLM-API网关主流技术栈调研.md](../research/LLM-API网关主流技术栈调研.md)。  
云上实验点：[experiment/EC2-用户侧隔离实验点设计.md](../experiment/EC2-用户侧隔离实验点设计.md)（Runner）、[experiment/EC2-中转站原型实验点设计.md](../experiment/EC2-中转站原型实验点设计.md)（原型）；实测结论仍写本目录。

> **索引原则**：每条报告绑定 `experiment/user-side/sites.json` 中的 **站点 ID**。站点之间 **不可** 互推结论。

## 源评估报告命名

三层源评估（Layer 1–3）报告 **固定文件名**：

```text
{源站点域名}-{报告名称}-{YYYY-MM-DD}.md
```

| 段 | 说明 | 示例 |
|----|------|------|
| **源站点域名** | `sites.json` 站点 id（含 `.` 时直接用）；否则 `base_url` 主机名；可设 `report_domain` 覆盖 | `ai.oai.red` |
| **报告名称** | 固定 slug | `源评估报告` |
| **日期** | 评估执行日（ISO 8601 日期） | `2026-06-04` |

**示例**：`ai.oai.red-源评估报告-2026-06-04.md`

查询路径（在 `experiment/user-side` 下）：

```bash
python3 lib/maas.py report-path --site ai.oai.red --relative
# → docs/reports/ai.oai.red-源评估报告-2026-06-04.md

./scripts/assess-source.sh --site ai.oai.red --agent opencode --write-report
# 自动生成同日报告 + .runtime/*-assess-*.json
```

同一站点 **同日复测** 覆盖同名文件；**换日** 生成新文件，保留历史。

## E3：站点 × Agent 直连（2026-06-01）

**站点 ID**：`b.ai`（当前仓库 **首批** 完整三 Agent 同环境对比；换站请新增报告，勿外推本表）。

| 报告 | 结论 | 阻塞原因 |
|------|------|----------|
| [OpenCode](./OpenCode兼容性评估报告.md) | 🟢 兼容 | Chat Completions 对齐 |
| [Claude Code](./ClaudeCode兼容性评估报告.md) | 🟢 基本兼容 | Messages 对齐；部分模型需账户权限 |
| [Codex](./Codex兼容性评估报告.md) | 🔴 不兼容 | 缺 `/v1/responses` |

## E4：转换层（2026-06-03）

| 报告 | 测试结果 | 说明 |
|------|------|------|
| [LiteLLM × Codex 转换层](./LiteLLM-Codex转换层评估报告.md) | 🟡 部分 | curl L2–L3 ✅；Codex `exec` ❌ |

## 源评估（三层法）

| 报告 | 测试结果 | 说明 |
|------|------|------|
| [ai.oai.red 2026-06-04](./ai.oai.red-源评估报告-2026-06-04.md) | L1–3 PASS · smoke PASS | OpenCode · gpt-5.5 · 4/4 executed · 1 SKIP |

## 新增报告

1. 跑评估并 **自动生成** Markdown（推荐）：

```bash
cd experiment/user-side
source .env
./scripts/assess-source.sh --site <id> --agent <name> --write-report
```

2. 结构化 JSON：`.runtime/<site>-assess-<YYYYMMDD>.json`  
3. 更新本节索引表（结论一行即可；正文由 `--write-report` 生成，无需手改）

报告 **不含** 跨站点对比表；各站点结论不可互推。
