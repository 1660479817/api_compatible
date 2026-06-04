# API Compatible — 研究：Coding Agent × 上游模型源兼容性

本仓库是 **研究项目**，不是 SDK、不是中转站产品。核心产出是 **文档**（调研、实验设计、评估报告）；`experiment/` 与 `upstream/` 是 **可复现附件**，服务于研究结论而非独立交付。

## 研究问题

在接入 **上游模型源** 之前，能否判断 **指定 Coding Agent** 在 **源 → LiteLLM → Agent** 链路上 **协议对齐、端到端可跑**？LiteLLM 承担 **计量** 与 **接口转换**；Agent 只连 Runner 本机 Proxy。

| 维度 | 关注点 |
|------|--------|
| **协议面** | Agent 硬性依赖的 HTTP 端点（如 `/v1/responses`、`/v1/messages`）与中转站是否裁剪、转换 |
| **网关栈** | New API / One API / LiteLLM 等 LLM API 网关实现差异与探测方法 |
| **网关转换** | 协议桥接方案地图（非「能 curl 通」即兼容） |
| **实验可复现** | 用户侧隔离 Runner、中转站原型 EC2、出站审计与语料采集 |
| **实证** | 源 × Agent 的 L2–L5 结论与复现步骤 |

> Key 有效、`/v1/models` 可达 **≠** Agent 可用 — 这是研究的主线判断，详见 [E2E 原生兼容性全景](./docs/research/E2E原生兼容性全景.md)。

---

## 产出结构（主阅读路径）

完整索引：[docs/README.md](./docs/README.md)

| 层级 | 目录 | 角色 |
|------|------|------|
| **调研** | [docs/research/](./docs/research/) | 理论基线：协议矩阵、LLM API 网关技术栈、转换插件地图 |
| **实验设计** | [docs/experiment/](./docs/experiment/) | 云上实验点：用户侧 Runner、中转站原型、语料采集插件契约 |
| **评估报告** | [docs/reports/](./docs/reports/) | 站点 × Agent **实测结论**（研究证据，不写在 README 里） |

建议阅读顺序：

1. [E2E 原生兼容性全景](./docs/research/E2E原生兼容性全景.md)  
2. [LLM API 网关主流技术栈调研](./docs/research/LLM-API网关主流技术栈调研.md)（若评估 Token 站或自托管网关）  
3. [EC2-中转站原型实验点设计](./docs/experiment/EC2-中转站原型实验点设计.md) → [EC2-用户侧隔离实验点设计](./docs/experiment/EC2-用户侧隔离实验点设计.md)  
4. 结论对照 [docs/reports/](./docs/reports/)

---

## 代码附件

代码 **不** 定义项目边界；用于 **执行** 文档中的实验设计与探针。

| 类型 | 路径 | 作用 |
|------|------|------|
| **实验实现** | [experiment/](./experiment/) | 与 `docs/experiment/` 对应 — 见 [experiment/README.md](./experiment/README.md) |
| **参考源码** | [upstream/](./upstream/) | `pull.sh` → `upstream/opencode/`、`newapi/`、`codex/`（本地拉取，不提交 Git） |

---

## 研究方法（概要）

```mermaid
flowchart TD
  R["research：协议矩阵 / 技术栈 / 转换地图"]
  E["experiment 设计稿"]
  V["experiment/ 代码：user-side · gateway · corpus-tap"]
  P["reports：站点 × Agent 结论"]

  R --> E --> V --> P
```

| 阶段 | 文档 | 代码（可选） |
|------|------|----------------|
| 建立基线 | `docs/research/` | — |
| 设计实验 | `docs/experiment/` | 云上拓扑、凭据、出站策略 |
| 执行探测 | 用户侧实验点 § 操作说明 | `experiment/user-side/` |
| 语料 / 网关 | 中转站原型 + 语料插件设计 | `experiment/gateway-prototype/`、`experiment/corpus-tap/` |
| 归档结论 | `docs/reports/` | — |

**环境分工**：E4 兼容性自动化在 **用户侧 EC2 Runner** 上 `cd experiment/user-side` 后跑 `t_*`；**中转站原型 EC2** 用于建站、发 Token 与可选语料采集，**不** 作为 `t_*` 的常规运行环境。详见 [EC2-用户侧隔离实验点设计](./docs/experiment/EC2-用户侧隔离实验点设计.md)。

---

## 仓库布局

```
api_compatible/
├── docs/                    # ★ 主产出（research / experiment / reports）
├── experiment/              # 实验实现（与 docs/experiment/ 对应）
│   ├── user-side/           # 用户侧 Runner
│   ├── gateway-prototype/   # 中转站原型（占位）
│   └── corpus-tap/          # 语料采集插件
└── upstream/                # 参考源码 pull.sh + 本地 clone
```

协作与 Git 规则：[AGENTS.md](./AGENTS.md)；用户侧细则：[experiment/user-side/AGENTS.md](./experiment/user-side/AGENTS.md)。

---

## 复现验证（从属章节）

需要 **复现** 某份报告或实验点中的步骤时，进入对应 `experiment/` 子目录；日常阅读以 `docs/` 为主。

```bash
cd experiment/user-side
cp .env.example .env
./scripts/assess-platform.sh --site <site-id>
./scripts/assess-protocol.sh --site <site-id>
./scripts/assess-source.sh --site <site-id> --agent claude --smoke
```

- 启动器细节、代理（v2rayN）、新增站点：见 [experiment/user-side/AGENTS.md](./experiment/user-side/AGENTS.md)。  
- Corpus Tap：[experiment/corpus-tap/README.md](./experiment/corpus-tap/README.md)。

---

## 协议速查（指向调研）

| Agent | 硬性 API | 深度阅读 |
|-------|----------|----------|
| Codex 0.133+ | `/v1/responses` | [Codex 兼容性评估报告](./docs/reports/Codex兼容性评估报告.md) |
| Claude Code | `/v1/messages` | [Claude Code 兼容性评估报告](./docs/reports/ClaudeCode兼容性评估报告.md) |
| OpenCode | `/v1/chat/completions` | reports 索引 |

矩阵与版本基线：[E2E 原生兼容性全景](./docs/research/E2E原生兼容性全景.md)。

---

## 扩展研究

| 方向 | 先写 / 改文档 | 再按需改代码 |
|------|----------------|--------------|
| 新上游类型或站点 | `docs/research/` 或 `docs/reports/` | `experiment/user-side/sites.json`、`t_*` |
| 新 Agent | `docs/research/` 矩阵 + 新报告卷 | 新 `experiment/user-side/t_<agent>` |
| 新实验点 | `docs/experiment/` 新设计稿 | `experiment/<slug>/` 新子目录 |
| 语料采集规则 | [中转站语料采集插件设计](./docs/experiment/中转站语料采集插件设计.md) | `experiment/corpus-tap/` |

---

## 许可证

- 文档与方法论以本仓库维护为准。  
- `upstream/opencode/`、`upstream/newapi/`、`upstream/codex/` 为可选参考源码，遵循各自许可证；`upstream/pull.sh` 拉取，不纳入 Git。

---

**一句话**：研究 **Agent 与上游是否真兼容** — 证据在 `docs/`，`experiment/` 与 `upstream/` 只是复现附件。
