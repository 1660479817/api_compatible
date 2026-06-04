# AGENTS.md — 本仓库协作规则

面向维护者与 AI Agent：在改代码、写文档、提交 Git 前先读本文。

## 项目定位

**API Compatible** 是 **研究项目**，主产出在 `docs/`（research / experiment / reports）。**不是** SDK 或中转站产品。

| 附件 | 路径 | 作用 |
|------|------|------|
| **实验实现** | [`experiment/`](./experiment/) | 与 [`docs/experiment/`](./docs/experiment/) 一一对应；user-side 配置见 [`experiment/user-side/CONFIG.md`](./experiment/user-side/CONFIG.md) |
| **参考源码** | [`upstream/`](./upstream/) | `pull.sh` 拉取 OpenCode / New API / Codex 对照实现（gitignored） |

目标：在接入上游模型源前，用 **源 → LiteLLM → 指定 Agent** 可复现实验判断端到端是否跑通，并把结论写入 `docs/reports/`。测试端点见 [EC2-用户侧隔离实验点 §2.3](./docs/experiment/EC2-用户侧隔离实验点设计.md#23-测试端点源--litellm--agent)。

## 目录职责

| 路径 | 是否提交 Git | 说明 |
|------|--------------|------|
| `docs/` | ✅ | **主产出**：research / experiment / reports |
| `experiment/user-side/` | ✅ | [EC2-用户侧隔离实验点](./docs/experiment/EC2-用户侧隔离实验点设计.md) — 细则见 [AGENTS.md](./experiment/user-side/AGENTS.md) |
| `experiment/gateway-prototype/` | ✅ | [EC2-中转站原型实验点](./docs/experiment/EC2-中转站原型实验点设计.md) — 占位，待补 Compose/脚本 |
| `experiment/corpus-tap/` | ✅ | [中转站语料采集插件设计](./docs/experiment/中转站语料采集插件设计.md) |
| `upstream/pull.sh`, `upstream/README.md` | ✅ | 按需拉取参考源码到 `upstream/*/` |
| `upstream/opencode/`, `upstream/newapi/`, `upstream/codex/` | ❌ | 参考源码 clone |
| 根目录 `.env`、`.claude/`、`.runtime/` | ❌ | **已迁至 `experiment/user-side/`**；根目录残留可删除 |

## 参考源码

需要对照 OpenCode / New API / Codex 实现时：

```bash
./upstream/pull.sh opencode
./upstream/pull.sh newapi
./upstream/pull.sh codex
```

拉取目录在 `upstream/.gitignore`，勿加入版本库。

## 安全与 Git

- **禁止**提交 API Key、`.env`、`.claude/`、`.runtime/`、含密钥的 `opencode.json`
- `experiment/user-side/sites.json` 只引用 `api_key_env` 名称，不写密钥值
- 评估报告中的 Key 应打码或提示轮换

## 文档同步

改目录结构、实验设计或 Git 规则时，同步更新：

- [README.md](./README.md)（用户向总览，不含具体测试结论）
- [docs/README.md](./docs/README.md)（文档索引）
- [experiment/README.md](./experiment/README.md)（实验实现 ↔ 设计稿映射）
- [upstream/README.md](./upstream/README.md)（参考源码拉取说明）
- [docs/research/E2E原生兼容性全景.md](./docs/research/E2E原生兼容性全景.md)（改版时同步 **编写日期**、**评估标的版本** 与矩阵内容）
- [docs/research/编程Agent模型转换插件调研.md](./docs/research/编程Agent模型转换插件调研.md)（网关大版本或 Agent wire 变更时复审）
- [docs/research/LLM-API网关主流技术栈调研.md](./docs/research/LLM-API网关主流技术栈调研.md)（主流网关大版本或新增站点 E3 时复审）
- [docs/experiment/EC2-用户侧隔离实验点设计.md](./docs/experiment/EC2-用户侧隔离实验点设计.md)（Runner 拓扑、凭据模式或用户侧出站策略变更时复审）
- [docs/experiment/EC2-中转站原型实验点设计.md](./docs/experiment/EC2-中转站原型实验点设计.md)（New API 原型、Channel/Token 交付或网关侧出站策略变更时复审）
- [experiment/corpus-tap/DESIGN.md](./experiment/corpus-tap/DESIGN.md)（Corpus Tap **采集+存储** 契约变更时复审；索引见 [中转站语料采集插件设计](./docs/experiment/中转站语料采集插件设计.md)）
- [experiment/corpus-tap/analysis/ARCHITECTURE.md](./experiment/corpus-tap/analysis/ARCHITECTURE.md)（**分析层/多策略** 分界变更时复审）
- [experiment/corpus-tap/analysis/profile/DESIGN.md](./experiment/corpus-tap/analysis/profile/DESIGN.md)（**profile 策略** Stage/导出变更时复审）
- [docs/experiment/中转站语料采集插件设计.md](./docs/experiment/中转站语料采集插件设计.md)（部署拓扑、G2、**Profile Analyzer** 扩展槽变更时复审）
- [experiment/user-side/AGENTS.md](./experiment/user-side/AGENTS.md)（启动器或站点登记变更时）
- [experiment/user-side/CONFIG.md](./experiment/user-side/CONFIG.md)（sites / assess-plan 分工变更时）
- [docs/reports/README.md](./docs/reports/README.md)（报告索引与样例结论）
