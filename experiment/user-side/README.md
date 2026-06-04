# user-side — 用户侧源评估实验

本目录是 **[EC2-用户侧隔离实验点设计](../../docs/experiment/EC2-用户侧隔离实验点设计.md)** 的可运行实现：在固定拓扑 **源 → LiteLLM → Agent** 下，对 `sites.json` 登记的上游源做 **三层源评估**，并把结构化结果写入 `docs/reports/`。

可在本机、CI 或 EC2 Runner 上运行；脚本不绑定 AWS，设计稿中的 SG / N1–N3 出站审计属于云上增强项。

**配置分工**（字段级说明见 [`CONFIG.md`](./CONFIG.md)）：

| 文件 | 职责 |
|------|------|
| [`sites.json`](./sites.json) | **描述站点**：URL、`protocol`、文档模型列表、`api_key_env` |
| [`assess-plan.json`](./assess-plan.json) | **描述测什么**：模型族 `families`、Layer 2 wire、Layer 3 模型与 smoke |
| [`.env`](./.env.example) | API Key（Git 忽略；变量名对齐 `api_key_env`） |

协作与 Git 规则：[AGENTS.md](./AGENTS.md)

---

## 评估要回答什么

对单个 **站点 id**（不可外推到其他源）：

1. 源是否可达、鉴权是否有效、catalog 返回什么？
2. 在源上，assess-plan 配置的 model × wire 能否原生跑通？
3. 经 LiteLLM relay 后，指定 Agent 能否 E2E？可选 smoke 场景结果如何？

报告 **只记录测试事实**（PASS/FAIL/SKIP、耗时、协议面、API model 等）；是否采用该源由人或在报告之上解读。

---

## 拓扑

```text
Layer 1–2   探针 ──────────────────────────────► 上游源（sites.json base_url）
Layer 3     Agent / smoke ──► LiteLLM :4000 ──► 上游源
```

LiteLLM 配置由 `maas.py write-litellm-config` 按站点生成，落在 `.runtime/litellm.<site>.yaml`；进程由 `scripts/litellm-proxy.sh` 管理。

| Agent | 主 wire | LiteLLM 出站 |
|-------|---------|--------------|
| OpenCode | `POST /v1/chat/completions` | Chat 直通 |
| Claude Code | `POST /v1/messages` | Messages 直通 |
| Codex | `POST /v1/responses` | 缺 Responses 的源上 **桥接** 为 Chat |

**模型族 → 主 Agent**（见 [`CONFIG.md`](./CONFIG.md)）：`gpt` → Codex，`anthropic` → Claude Code；**OpenCode** 为各族通用 chat 探针。

```bash
python3 lib/maas.py get families --site test_gpt_claude
# anthropic,gpt

python3 lib/maas.py get assess_agents --site ai.oai.red --family gpt
# opencode,codex
```

---

## 前置条件

| 依赖 | 用途 |
|------|------|
| **Python 3** | `lib/maas.py` 主入口 |
| **LiteLLM** | Layer 3 relay（`pip install litellm` 或项目既有环境） |
| **`.env`** | 平台 Token；`cp .env.example .env` 后填写 |
| **Agent CLI**（可选） | `--smoke` 且 `smoke_mode=agent` 时需要；默认 `smoke_mode=relay` 可只测 HTTP |
| **代理**（可选） | 国内访问境外源时设 `MAAS_PROXY`；境外 Runner 可 `MAAS_PROXY_SKIP=1` |

---

## 快速开始

```bash
cd experiment/user-side
cp .env.example .env          # 填写 sites.json 中 api_key_env 对应密钥
source .env

# GPT 族一键：L1–2 + OpenCode 探针 + Codex（单族站可省略 --family）
./scripts/assess-family.sh --site ai.oai.red --family gpt --smoke --write-report
```

等价于：

```bash
python3 lib/maas.py assess-source --site ai.oai.red --family gpt --agent codex --smoke --write-report
```

**产出**：

| 产物 | 路径 |
|------|------|
| Markdown 报告 | `docs/reports/{report_domain}-源评估报告-{YYYY-MM-DD}.md` |
| 结构化 JSON | `.runtime/{site}-assess-{YYYYMMDD}.json` |
| LiteLLM 日志 | `.runtime/litellm.{site}.log` |

查询报告路径：

```bash
python3 lib/maas.py report-path --site ai.oai.red --relative
```

---

## 三层评估法

设计稿：[§2.1 三层评估法](../../docs/experiment/EC2-用户侧隔离实验点设计.md#21-三层评估法)

| 层 | 名称 | 拓扑 | 脚本 | 判定依据 |
|----|------|------|------|----------|
| **1** | 平台链接 | 直打源 | `assess-platform.sh` | `GET /v1/models`；catalog 分支 `listed` / `empty` / `unavailable`；与 `supported_models` 对照 |
| **2** | 基础协议 | 直打源 | `assess-protocol.sh` | `families.<name>.models` × wire；记录 `shape` / `usage` / `stream` |
| **3** | 指定 Agent | 源 → LiteLLM → Agent | `run-source-agent-test.sh` | relay wire probe；可选 smoke（`assess-plan` → `smoke_scenarios`） |
| **3+** | smoke（可选） | 同上或 `t_*` | `--smoke` | `smoke_mode`: `relay`（默认，HTTP 经 LiteLLM）或 `agent`（完整 Agent CLI） |

**递进关系**：Layer 1 的 catalog 分支决定 Layer 2 是 **listed 对比** 还是 **盲测**；Layer 2 某 wire 缺失时，Layer 3 须在报告中标注依赖 LiteLLM 桥接（Codex 常见）。

**逐层手动跑**：

```bash
./scripts/assess-platform.sh --site ai.oai.red
./scripts/assess-protocol.sh --site ai.oai.red --family gpt
./scripts/run-source-agent-test.sh --site ai.oai.red --family gpt --agent codex --probe-only
./scripts/run-source-agent-test.sh --site ai.oai.red --family gpt --agent codex --smoke
```

**批量**（Layer 1 一次；Layer 2–3 按族或 `--agents`）：

```bash
./scripts/run-user-side-compat.sh --site b.ai --layers-12
./scripts/run-user-side-compat.sh --site b.ai --family anthropic --smoke
./scripts/run-user-side-compat.sh --site b.ai --family other --smoke --agents opencode
```

---

## 目录结构

```text
experiment/user-side/
├── sites.json              # 上游站点登记
├── assess-plan.json        # 各层探测与 smoke 计划
├── .env.example            # 密钥模板
├── CONFIG.md               # 配置字段与脚本映射（细则）
├── AGENTS.md               # 协作 / Git 规则
├── lib/
│   ├── maas.py             # 站点注册、各层评估、报告生成
│   └── maas.sh             # shell 辅助（t_* 启动器引用）
├── scripts/
│   ├── assess-platform.sh      # Layer 1
│   ├── assess-protocol.sh      # Layer 2
│   ├── assess-family.sh        # 一族 L1–2 + 族内多 Agent L3
│   ├── assess-source.sh        # 单 Agent Layer 1–3 + --write-report
│   ├── run-source-agent-test.sh # Layer 3
│   ├── run-user-side-compat.sh  # 批量
│   └── litellm-proxy.sh        # LiteLLM 启停
├── t_claude / t_codex / t_opencode   # Agent 启动器（`--family` 可省略，按 Agent 推断）
└── .runtime/               # 生成物与 JSON 证据（Git 忽略）
```

---

## 脚本一览

| 脚本 | 作用 |
|------|------|
| `assess-family.sh` | **按族批量**：L1–2 + 族内各 Agent L3；默认 `--smoke` |
| `assess-source.sh` | 单 Agent 全层；`--smoke`；`--write-report` |
| `assess-platform.sh` | 仅 Layer 1 |
| `assess-protocol.sh` | 仅 Layer 2 |
| `run-source-agent-test.sh` | 仅 Layer 3（`--probe-only` / `--smoke`） |
| `run-user-side-compat.sh` | 批量；`--layers-12` 只跑 1–2 |
| `litellm-proxy.sh` | `start \| stop \| status --site <id>` |

---

## `maas.py` 常用命令

在 `experiment/user-side` 下执行：

| 命令 | 说明 |
|------|------|
| `list-sites` | 列出 `sites.json` 站点 id |
| `get families --site <id>` | 该站模型族列表 |
| `get default_family --site <id> --agent <name>` | 推断模型族（`gpt` / `anthropic` / …） |
| `get assess_agents --site <id> [--family NAME]` | 该族或全站 Layer 3 Agent 列表 |
| `get default_model --site <id> --agent <name>` | Layer 3 默认 model |
| `list-models --site <id>` | 直打源 `GET /v1/models` |
| `assess-platform --site <id>` | Layer 1（`--json` 输出 JSON） |
| `assess-protocol --site <id>` | Layer 2 |
| `probe-relay --site <id> --agent <name>` | Layer 3 relay 探针 |
| `run-smoke --site <id> --agent <name>` | Layer 3 smoke |
| `assess-source --site <id> --agent <name> [--smoke] [--write-report]` | 完整评估 |
| `report-path --site <id> --relative` | 报告 Markdown 路径 |
| `write-litellm-config --site <id> --out .runtime/litellm.<id>.yaml` | 生成 LiteLLM 配置 |

---

## 已登记站点

| 站点 id | protocol | 说明 |
|---------|----------|------|
| `b.ai` | `anthropic` | 族 `anthropic`（Claude Code）+ `other`（Kimi，仅 OpenCode） |
| `ai.oai.red` | `openai` | 族 `gpt`：`gpt-5.5` → Codex + OpenCode 探针 |
| `sub2api.salus.icu` | `openai` | 族 `gpt`：`gpt-5.5` |
| `test_gpt_claude` | `openai` | 族 `gpt` + `anthropic`（[Paratera](https://ai.paratera.com/)） |

### Paratera（`test_gpt_claude`）双族

**Layer 1 一次**；Layer 2–3 用 **`--family`**（`--profile` 为同义别名）：

| family | 主 Agent | Layer 3 | 说明 |
|--------|----------|---------|------|
| `gpt` | Codex | OpenCode + Codex | `chat` + `responses` |
| `anthropic` | Claude Code（若仅有 chat 面则 N/A） | OpenCode | Claude 模型经 chat；不跑 Claude Code 除非有 Messages |

```bash
cd experiment/user-side && source .env

./scripts/assess-platform.sh --site test_gpt_claude

./scripts/assess-protocol.sh --site test_gpt_claude --family gpt
./scripts/assess-source.sh --site test_gpt_claude --family gpt --agent codex --write-report

./scripts/assess-protocol.sh --site test_gpt_claude --family anthropic
./scripts/assess-source.sh --site test_gpt_claude --family anthropic --agent opencode --write-report

./scripts/assess-family.sh --site test_gpt_claude --family gpt --smoke
./scripts/assess-family.sh --site test_gpt_claude --family anthropic --smoke
```

详情见 [CONFIG.md](./CONFIG.md)。

新增站点：编辑 `sites.json` + `assess-plan.json` → `.env` 补密钥 → 跑 `assess-source` → 更新 [`docs/reports/README.md`](../../docs/reports/README.md) 索引。

---

## 报告约定

- 命名：`{report_domain}-源评估报告-{YYYY-MM-DD}.md`（见 [`docs/reports/README.md`](../../docs/reports/README.md)）
- 由 `--write-report` **自动生成**；同站同日覆盖，换日保留历史
- 正文为测试记录，**勿手抄终端日志**；解读写在报告外（人工或 AI）

---

## 相关文档

- [EC2-用户侧隔离实验点设计](../../docs/experiment/EC2-用户侧隔离实验点设计.md) — 方法论、Runner、出站审计
- [EC2-中转站原型实验点设计](../../docs/experiment/EC2-中转站原型实验点设计.md) — 运营商建站与 Token 交付
- [E2E 原生兼容性全景](../../docs/research/E2E原生兼容性全景.md) — Layer vs L1–L5 术语对照
- [docs/reports/](../../docs/reports/) — 实测结论归档
