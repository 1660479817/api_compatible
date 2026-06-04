# EC2 用户侧隔离实验点设计

> **文档类型**：实验方法论 · **非** 兼容性认证报告（结论写入 [reports/](../reports/)）  
> **范围**：境外 **EC2 Runner** 上模拟终端开发者：三 Agent、凭据、L2–L5、出站审计 **N1–N3**  
> **凭据**：原厂 Key **或** 中转站平台 Token（含 [中转站原型](./EC2-中转站原型实验点设计.md) 交付、`sites.json` 登记的商业 Token 站）  
> **分工**：[中转站原型稿](./EC2-中转站原型实验点设计.md) = 运营商建站；本文 = Runner 接入 · E4；直连对齐全景 **L1+L2+**，中转为 **经网关 E4**

### 文档元信息

| 项 | 内容 |
|----|------|
| **编写日期** | 2026-06-03 |
| **状态** | 设计稿（基础设施与报告待实施） |
| **工作目录** | [`experiment/user-side/`](../../experiment/user-side/)（下文简称 **user-side**；命令均在此目录执行） |
| **复审触发** | Agent 主 wire 变更、新增中转站源、Runner/SG 拓扑、LiteLLM 转换层变更 |

---

## 目录

1. [实验点定位](#1-实验点定位)
2. [实验要回答的问题](#2-实验要回答的问题)
3. [逻辑架构](#3-逻辑架构)
4. [两种凭据模式](#4-两种凭据模式)
5. [评估维度](#5-评估维度)
6. [EC2 部署建议](#6-ec2-部署建议)
7. [出站审计（防火墙）](#7-出站审计防火墙)
8. [启动器与自动化（t_*）](#8-启动器与自动化t_)
9. [三 Agent 配置要点](#9-三-agent-配置要点)
10. [分阶段实施](#10-分阶段实施)
11. [证据归档与报告](#11-证据归档与报告)
12. [风险与局限](#12-风险与局限)
13. [实施检查清单](#13-实施检查清单)
14. [LiteLLM 转换层（计量与协议）](#14-litellm-转换层计量与协议)

---

## 1. 实验点定位

### 1.1 本实验点是什么

| 是 | 不是 |
|----|------|
| 隔离网络上跑 Coding Agent（`t_claude` / `t_codex` / `t_opencode`） | 中转站运营商机（[中转站原型稿](./EC2-中转站原型实验点设计.md)） |
| **模式 A/B** 对照：LiteLLM 出站目标为原厂 vs 中转 Token 站 | 把 LiteLLM 当上游产品本身（它是 Runner 侧转换/计量层） |
| **标准拓扑**：源 → **LiteLLM**（计量 + 转换）→ 端侧 Agent | 中转站运营商机（建站见原型稿） |
| SG / Flow Log 证明 **用户进程** 出站 | 用本机结论代替 EC2 的 N1–N3（须标注 Runner） |

### 1.2 与中转站原型的协作

```text
[ 中转站原型 EC2 ]  New API · Channel · 平台 Token
        │  交付 base_url、anthropic_base_url、Token、对外 model 名
        ▼
[ 用户侧 EC2 ]      源 → LiteLLM → ./t_*（§2.3 · §8）
```

商业 Token 站无需自建原型，在 user-side 的 `sites.json` 登记为中转源即可。

### 1.3 实施前必须固定

| 固定项 | 否则 |
|--------|------|
| **模式**（A 直连 / B 中转） | 出站白名单与 scope 混乱 |
| **sites.json 站点 id** | 报告不可复现 |
| **Agent 版本**；关闭 OAuth、`doctor`、实验期 CLI 自更新 | N2/N3 失真 |
| **通过 / 失败判定** | 无法写入 reports |

---

## 2. 实验要回答的问题

**评估对象**：`sites.json` 中的 **上游源**（站点 id）。LiteLLM 为固定探针环境（计量 + 转换），结论须绑定站点 id，不可外推。

### 2.1 三层评估法

| 层 | 名称 | 评什么 | 拓扑 | 脚本 |
|----|------|--------|------|------|
| **1** | 平台链接基础评估 | 源是否可达、鉴权是否有效；`/v1/models` **catalog 分支** | **直打源** | `assess-platform.sh` |
| **2** | 基础协议层评估 | protocol 内目标模型 × wire（listed 对比 / 盲测） | **直打源** | `assess-protocol.sh` |
| **3** | 指定 Agent 全协议面评估 | 固定 Agent 在标准链路上能否 E2E | **源 → LiteLLM → Agent** | `run-source-agent-test.sh` |

```text
Layer 1–2  探针 ──────────────────────────► 上游源（sites.json base_url）
Layer 3    Agent ──► LiteLLM ─────────────► 上游源
```

**递进规则**：第 1 层判定 **catalog 分支**（listed / empty / unavailable），决定第 2 层模式；第 2 层 **listed** 时对比 `assess-plan` layer2 与目录后逐模型探测，**empty / unavailable** 时盲测 layer2；2 缺 wire → 3 须标注「依赖 LiteLLM 桥接」；**是否采用该源** 以你关心的 Agent 在第 3 层 **L4 通过** 为准。

**第 1 层 catalog 分支**

| 分支 | 条件 | 第 1 层 | 第 2 层 |
|------|------|---------|---------|
| **listed** | HTTP 200 且 `data` 非空 | 链接 PASS · 目录 PASS | 对比 `assess-plan` layer2 ↔ 目录，再测配置内模型 |
| **empty** | HTTP 200 且 `data` 为空 | 链接 PASS · 目录 WARN | **盲测** `assess-plan` layer2 |
| **unavailable** | 非 200 / 无有效体 | 链接 FAIL | **盲测** `assess-plan` layer2 |

目标模型列表：[`assess-plan.json`](../../experiment/user-side/assess-plan.json) 的 **`layer2.targets`**（Layer 2 探测）；[`sites.json`](../../experiment/user-side/sites.json) 的 **`supported_models`** 为文档摘录（Layer 1 对照，不驱动探测）。配置分工见 [`CONFIG.md`](../../experiment/user-side/CONFIG.md)。

**第 2 层 protocol 分支**（`sites.json` 的 `protocol` 字段）

| 协议 profile | 默认测哪些 Agent | 默认 wire |
|--------------|------------------|-----------|
| **anthropic** | OpenCode + Claude Code | `chat` · `messages` |
| **openai** | OpenCode + Codex | `chat` · `responses` |
| **chat** | OpenCode | `chat` |

显式 `targets` 中的 `wires` 会与 protocol 取交集；未写 `wires` 时对该模型测 protocol 内全部 wire。

**术语（Layer vs L）**

| 术语 | 含义 | 脚本 |
|------|------|------|
| **Layer 1–3** | 本实验 **源评估** 三层（平台 → 源原生协议 → Agent+LiteLLM） | `assess-platform` / `assess-protocol` / `run-source-agent-test` |
| **L1–L5** | [E2E 全景](../research/E2E原生兼容性全景.md) **能力深度**（集成 → wire → 流式 → tool → 高级） | Layer 3 内：`probe-relay` ≈ E2E L2；`t_*` smoke ≈ E2E L3+ |

Layer 3 默认只跑 **protocol profile 内** 的 Agent（`maas.py get assess_agents --site <id>`）；Codex 经 LiteLLM **桥接**，Claude/OpenCode **直通**。

一键（1+2+3 单 Agent）：

```bash
./scripts/assess-source.sh --site <site-id> --agent claude --smoke
```

批量：Layer 1–2 一次 + 多 Agent 第 3 层 → `run-user-side-compat.sh --smoke`。

### 2.2 Agent 主 wire（第 2、3 层对照）

| Agent | 主 wire |
|-------|---------|
| Claude Code | `POST /v1/messages` |
| Codex ≥ 0.133 | `POST /v1/responses` |
| OpenCode | `POST /v1/chat/completions` |

**报告 scope**：中转标注 **站点 id**；第 2 层写 **源原生** 矩阵，第 3 层写 **relay + Agent**，禁止混为「源原生 Responses ✅」。

### 2.3 出站（N1–N3）

是否出现 **未声明** 外连？允许目标见 §7.2。

---

## 3. 逻辑架构

```text
┌─ VPC（建议独立实验账号）────────────────────────────────────┐
│  EC2 Runner（用户侧）                                          │
│    t_* Agent ──► 127.0.0.1:LiteLLM ──► 上游源（sites.json）   │
│  SG：Agent 进程 N2 仅 LiteLLM 端口；LiteLLM N2 连上游 host     │
└──────────────────────────────────────────────────────────────┘
```

**模式 A**（原厂源）与 **模式 B**（中转 Token 站）均经 LiteLLM 出站；差异在 LiteLLM `api_base` 与凭据 env。

---

## 4. 两种凭据模式

### 4.1 模式 A：原厂直连

| 项 | 说明 |
|----|------|
| **凭据** | `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`；Bedrock 仅官方集成测试时用 Instance Profile |
| **BASE_URL** | 默认官方，或不设 `*_BASE_URL` |
| **sites.json** | 可加 `official-openai` 等便于 probe |
| **用途** | Positive control、对照 E2E、排除 Runner/SG 误伤 |

### 4.2 模式 B：中转站

| 项 | 说明 |
|----|------|
| **凭据** | 平台 Access Token（非 Channel 上游 Key） |
| **BASE_URL** | 站点 `base_url` / `anthropic_base_url`（[中转站原型 §10](./EC2-中转站原型实验点设计.md#10-交付用户侧) 或商业站文档） |
| **sites.json** | 例：`newapi-prototype`、任意商业 Token 站 id |
| **model** | 中转站对外映射名 |
| **禁止** | Claude 内置 Bedrock、Codex `amazon-bedrock`（绕过中转 URL） |

### 4.3 模式切换

同一份报告含两种模式时，L2–L5 与 N2 **分表**，不得混列 PASS。

---

## 5. 评估维度

与 [E2E 全景 §1.2](../research/E2E原生兼容性全景.md) 对齐，并增加 N1–N3：

| 层级 | 检查 |
|------|------|
| 第 1 层 | `assess-platform.sh` |
| 第 2 层 | `assess-protocol.sh`（源原生） |
| 第 3 层 | `run-source-agent-test.sh` / `t_*`（L3 流式 · L4 tool · L5 按需） |
| N1 | 空闲出站 |
| N2 | 单次推理出站（§7.2） |
| N3 | L4 期间非模型 API |

---

## 6. EC2 部署建议

| 项 | 建议 |
|----|------|
| **区域** | 与 Bedrock / 中转站原型同区或低延迟；直连原厂可不绑 Bedrock 区 |
| **实例** | `t3.large` 起；≥ 30 GiB 若三 Agent 同机 |
| **IAM** | 模式 A + Bedrock：`bedrock:InvokeModel`；模式 B 通常无需 Bedrock IAM |
| **密钥** | SSM / Secrets Manager；`.env` 不进 Git |
| **启动** | `./t_<agent> --site <id> -y` |

---

## 7. 出站审计（防火墙）

### 7.1 观测手段

Security Group 白名单、`nftables` LOG、VPC Flow Logs（可选）。

### 7.2 预期允许出站（按当前模式）

**共有（N1）**：`amazonaws.com`（SSM/元数据/CloudWatch）、NTP；构建期 npm/镜像源 **仅预装阶段**，N1 窗口不应出现。

| 模式 | N2 允许 |
|------|---------|
| **A** | `api.anthropic.com`、`api.openai.com`、Bedrock endpoint（若测） |
| **B** | 中转站 `base_url` host；**不应** 出现原厂 API（除非 env 残留模式 A） |

**须关闭（避免 N2/N3 失真）**：Codex OAuth、`codex doctor`、CLI 自动更新、未用 MCP / OpenCode 插件市场。

### 7.3 违规记录模板

```text
模式：[A / B <site-id>]  时间窗：[N1][N2][N3]
违规：目标 ∉ §7.2
```

---

## 8. 启动器与自动化（t_*）

实现见 [user-side/AGENTS.md](../../experiment/user-side/AGENTS.md)。

| 组件 | 作用 |
|------|------|
| `sites.json` + `.env` | 上游源与出站 Key（LiteLLM 使用，无密钥入库） |
| `scripts/assess-platform.sh` | 第 1 层：平台链接 |
| `scripts/assess-protocol.sh` | 第 2 层：源原生协议面 |
| `scripts/assess-source.sh` | 第 1+2+3 一键（单 Agent） |
| `scripts/run-source-agent-test.sh` | 第 3 层：LiteLLM → Agent |
| `scripts/litellm-proxy.sh` | LiteLLM 启停 |
| `./t_<agent>` | 第 3 层 L4+ |
| `scripts/run-user-side-compat.sh` | 第 1–2 一次 + 多 Agent 第 3 层 |

本机可跑 `t_*` 调试；**带 N1–N3 的 E4** 须在用户侧 EC2 复跑。

### 8.1 Runner 部署

```bash
git clone <api_compatible> && cd api_compatible/experiment/user-side
cp .env.example .env   # SSM 注入 Key / 平台 Token

# 三层评估
./scripts/assess-platform.sh --site newapi-prototype
./scripts/assess-protocol.sh --site newapi-prototype
./scripts/run-source-agent-test.sh --site newapi-prototype --agent claude --smoke

# 或一键
./scripts/assess-source.sh --site newapi-prototype --agent claude --smoke
```

| 项 | 建议 |
|----|------|
| **路径** | 如 `/opt/api_compatible/experiment/user-side` |
| **代理** | 境外 `MAAS_PROXY_SKIP=1`；大陆调试再用 `MAAS_PROXY` |
| **自动化** | 必须 `-y`；CLI 子命令经 `--` 传入 |
| **产物** | `.runtime/*` 仅 Runner 本地 |

### 8.2 自动化分层

| 层级 | 命令 |
|------|------|
| 1 | `assess-platform.sh --site <id>` |
| 2 | `assess-protocol.sh --site <id>` |
| 3 probe | `run-source-agent-test.sh --probe-only` |
| 3 smoke | `run-source-agent-test.sh --smoke` |
| 3 L4 | `t_* -- …` |

### 8.3 与中转站交付

1. 原型交付 URL + Token（[中转站 §10](./EC2-中转站原型实验点设计.md#10-交付用户侧)）。  
2. 合并 `sites.json` 条目 `newapi-prototype`。  
3. Runner 跑 §8.1 → 结论写入 `docs/reports/`。

---

## 9. 三 Agent 配置要点

`sites.json` 登记 → `.env` 填上游 Key → `./t_* --site <id> -y`（启动器自动 Ensures LiteLLM，Agent Key = `sk-litellm-<site-id>`）。

### 9.1 模式 B（中转 Token 站）

```bash
./scripts/run-source-agent-test.sh --site newapi-prototype --agent claude --smoke
./t_claude --site newapi-prototype --model claude-exp-bedrock -y
```

LiteLLM 出站使用平台 Token（`.env` 中 `api_key_env`）；Codex 禁用 OAuth / Bedrock 直连。

### 9.2 模式 A（原厂源）

在 `sites.json` 登记官方 `base_url`，`.env` 填原厂 Key；同样经 LiteLLM：

```bash
./scripts/run-source-agent-test.sh --site official-openai --agent claude --smoke
```

---

## 10. 分阶段实施

| 阶段 | 内容 | 产出 |
|------|------|------|
| **0** | Runner + SG + CLI + LiteLLM；模式 A L2 + N1–N2 | relay 基线 |
| **1** | 模式 A Claude L4 | reports 样例 |
| **2** | 原型交付 Token；`sites.json`；模式 B L2 + N2 | LiteLLM → 中转 host |
| **3** | 模式 B 三 Agent L4（按 probe 裁 Codex） | `newapi-prototype × Agent` |
| **4** | 增第二、第三中转源（`sites.json`） | 多站点对比 |

上一阶段 L4 或 N2 未通过则不扩。

### 10.2 L4 最小任务

| Agent | 任务 |
|-------|------|
| Claude Code | `--tools Grep` 搜固定字符串 |
| Codex | `codex exec` 单行 |
| OpenCode | 单轮或一次读文件 |

---

## 11. 证据归档与报告

| 章节 | 内容 |
|------|------|
| 评估环境 | 区域、实例、Agent 版本、模式、站点 id |
| 网络 | SG、N1–N3、模式 A/B |
| 协议 | L2–L5（分模式分表） |
| 出站 | 预期 vs 实际 |
| 复现 | §8 命令 +（模式 B）[中转站 §10](./EC2-中转站原型实验点设计.md#10-交付用户侧)；若 §14 旁路须注明 |

**源评估报告命名**（写入 [reports/](../reports/)）：

```text
{源站点域名}-源评估报告-{YYYY-MM-DD}.md
```

示例：`ai.oai.red-源评估报告-2026-06-04.md`。路径由 `experiment/user-side` 下 `python3 lib/maas.py report-path --site <id> --relative` 生成；详见 [reports/README.md §源评估报告命名](../reports/README.md#源评估报告命名)。

Agent 单站兼容性报告（E3）仍沿用 `{Agent}兼容性评估报告.md` 等既有命名，与源评估分开。

---

## 12. 风险与局限

| 风险 | 说明 |
|------|------|
| 模式混用 | env 残留 → N2 假阳性/阴性 |
| 中转不可达 | 先查原型 EC2 / SG，勿误判 Agent |
| 本机 vs EC2 | 本机 `t_*` 不能替代 N1–N3 |
| 站点裁剪 | 某站无 Responses ≠ 原型全功能；须逐站 probe |
| LiteLLM 旁路 | 译码 / `drop_params` 影响协议与 [Prompt Cache 分项](./EC2-中转站原型实验点设计.md#141-prompt-cache-计费与-usage)；成本须分拓扑（§14） |

---

## 13. 实施检查清单

**Runner**

- [ ] VPC + EC2 + SG（模式切换或两套 egress）  
- [ ] 克隆仓库；预装 CLI；`MAAS_PROXY_SKIP=1`（境外）  
- [ ] SSM → `.env`  

**自动化**

- [ ] `run-user-side-compat.sh --site <id> --layers-12`（Layer 1–2）  
- [ ] 可选 `--smoke`  
- [ ] L4 / N3 按 §10.2  

**模式 A**：原厂 Key（+ Bedrock IAM 若需）· probe · N1–N2 · ≥1 L4  

**模式 B**：[中转站原型](./EC2-中转站原型实验点设计.md) 已交付 · `sites.json` + `.env` · LiteLLM start · Layer 3 relay · L4 · N3  

**LiteLLM**：`litellm-proxy.sh start --site <id>` · 日志 `.runtime/litellm.<id>.log`

**文档**：更新 [reports/README.md](../reports/README.md)；结论不进根 README  

---

## 14. LiteLLM 转换层（计量与协议）

Runner 上 **常驻** LiteLLM Proxy：对 Agent 暴露三主 wire，对上游按 `sites.json` 转发或桥接。

### 14.1 职责

| 职责 | 说明 |
|------|------|
| **计量** | 代理日志 → `.runtime/litellm.<site>.log`；完整 spend 对账需 PostgreSQL（见 [中转站 §14.1](./EC2-中转站原型实验点设计.md#141-prompt-cache-计费与-usage)） |
| **转换** | Agent 主 wire 与源可用协议不一致时桥接（典型：Codex `/v1/responses` → 源 Chat） |

### 14.2 拓扑与 N2

```text
t_* Agent ──► 127.0.0.1:LiteLLM ──► 上游 base_url
```

| 进程 | N2 允许 |
|------|---------|
| Agent | 仅本机 LiteLLM 端口 |
| LiteLLM | 上游 host（模式 A/B 见 §7.2） |

报告须标注 **源 → LiteLLM → Agent** 与 **站点 id**。

### 14.3 协议选型

| Agent | LiteLLM 入站 | 出站 | 要点 |
|-------|--------------|------|------|
| Claude | `/v1/messages` | Messages 直通 | `api_base` → `anthropic_base_url` |
| OpenCode | `/v1/chat/completions` | Chat 直通 | `api_base` → `base_url` |
| Codex | `/v1/responses` | **桥接** | `custom_llm_provider: custom`（缺 Responses 的源） |

配置由 `maas.py write-litellm-config` 按站点 `default_models` 生成；Codex 默认启用桥接。

### 14.4 脚本

| 项 | 路径 |
|----|------|
| LiteLLM | `scripts/litellm-proxy.sh` |
| 测试端点 | `scripts/run-source-agent-test.sh` |
| 批量 | `scripts/run-user-side-compat.sh` |
| 运行时 | `.runtime/litellm.<site>.yaml`、`.runtime/litellm.<site>.log` |

Agent Key = `sk-litellm-<site-id>`（LiteLLM `master_key`）；上游 Key 仅 LiteLLM 使用。

Claude / OpenCode 在源已暴露同协议端点时仍可 **直通** LiteLLM（不经额外桥接）；Codex 在仅 Chat 源上须桥接 — 见 [LiteLLM × Codex 报告](../reports/LiteLLM-Codex转换层评估报告.md)。

---

## 参考链接

- [EC2-中转站原型实验点设计](./EC2-中转站原型实验点设计.md)  
- [E2E 原生兼容性全景](../research/E2E原生兼容性全景.md)  
- [LLM API 网关主流技术栈调研](../research/LLM-API网关主流技术栈调研.md)  
- [编程 Agent 模型转换插件调研](../research/编程Agent模型转换插件调研.md)  
- [user-side/AGENTS.md](../../experiment/user-side/AGENTS.md)  
- [E3 站点 × Agent 报告索引](../reports/README.md#e3站点--agent-直连2026-06-01)
