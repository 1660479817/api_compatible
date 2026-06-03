# AGENTS.md — 本仓库协作规则

面向维护者与 AI Agent：在改代码、写文档、提交 Git 前先读本文。

## 项目定位

**API Compatible** 不是 SDK，而是一套：

1. **站点注册**（`sites.json` + `.env`）
2. **Agent 启动器**（`t_claude` / `t_codex` / `t_opencode` → `lib/maas.sh` + `lib/maas.py`）
3. **兼容性评估报告**（`docs/reports/`，按站点 × Agent 分卷）

目标：在接入上游模型源（官方 API 或 Token 中转站）前，判断 Coding Agent 能否端到端跑通。

## 目录职责

| 路径 | 是否提交 Git | 说明 |
|------|--------------|------|
| `t_*` | ✅ | 薄入口，逻辑在 `lib/maas.sh` |
| `lib/maas.sh`, `lib/maas.py` | ✅ | 共享启动、站点解析、临时配置生成 |
| `sites.json` | ✅ | 上游站点注册表（无密钥） |
| `.env.example` | ✅ | 密钥环境变量模板 |
| `opencode.json.example` | ✅ | OpenCode 手工配置示例（无密钥） |
| `scripts/pull-upstream.sh` | ✅ | 按需拉取参考源码 |
| `docs/E2E原生兼容性全景.md` | ✅ | 上游 × 四 Agent 原生 E2E 兼容矩阵（含 Gemini CLI；不含中转站） |
| `docs/reports/` | ✅ | 评估结论与复现步骤（见目录内 README 索引） |
| `.env` | ❌ | 本地 API Key |
| `.claude/` | ❌ | Claude Code 本地配置（含密钥） |
| `.runtime/` | ❌ | 启动器生成的临时 Agent 配置 |
| `opencode.json` | ❌ | 本地 OpenCode 配置（若含密钥） |
| `opencode/`, `newapi/` | ❌ | 上游参考源码，用 `pull-upstream.sh` 拉取 |

## 启动器约定

- **`./t_claude`**：Anthropic Messages；缺 CLI 时自动安装；写入 `.claude/settings.json`
- **`./t_codex`**：OpenAI Responses；缺 CLI 时自动安装；写入 `.runtime/codex.<site>.toml`
- **`./t_opencode`**：Chat Completions；缺 CLI 时自动安装；写入 `.runtime/opencode.<site>.json`

三者共用参数：`--site`、`--model`、`-y`、`--list-sites`、`--list-models`；其余参数透传给底层 CLI。

**不要**让启动器依赖仓库内的 `opencode/` 或 `newapi/` 源码目录。

## 新增上游站点

1. 在 `sites.json` → `sites` 增加条目（`base_url`、`anthropic_base_url`、`api_key_env`、`default_models`、可选 `opencode` 块）
2. 在 `.env.example` 增加对应 `*_API_KEY` 占位
3. 用户本地 `.env` 填真实 Key
4. 用 `./t_*` 跑通后，在 `docs/reports/` 新增或更新评估报告

## 新增 Agent 启动器

1. 新增 `t_<name>`（source `lib/maas.sh`，调用 `maas_run_<name>`）
2. 在 `maas.sh` 实现：参数解析、CLI 检测/安装、环境变量与临时配置、`exec` 启动
3. 在 `maas.py` 按需增加 `get` / `write-*-config` 子命令
4. 在 `docs/reports/` 新增 `*兼容性评估报告.md`

## 安全与 Git

- **禁止**提交 API Key、`.env`、`.claude/`、`.runtime/`、含密钥的 `opencode.json`
- `sites.json` 只引用 `api_key_env` 名称，不写密钥值
- 评估报告中的 Key 应打码或提示轮换

## 参考源码

需要对照 OpenCode / New API 实现时：

```bash
./scripts/pull-upstream.sh opencode
./scripts/pull-upstream.sh newapi
```

拉取目录已在 `.gitignore`，勿加入版本库。

## 文档同步

改目录结构、启动器行为或 Git 规则时，同步更新：

- `README.md`（用户向总览，不含具体测试结论）
- `docs/E2E原生兼容性全景.md`（改版时同步 **编写日期**、**评估标的版本** 与矩阵内容）
- `AGENTS.md`（本文件，协作规则）
- `docs/reports/README.md`（报告索引与样例结论）
