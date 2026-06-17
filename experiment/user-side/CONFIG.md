# user-side 配置分工

评估链路：**Layer 1–2 直打源** · **Layer 3 源 → LiteLLM → Agent**。按 **Key + 模型族** 组织测试（用户心智：GPT 模型 → Codex，Claude 模型 → Claude Code，OpenCode 作通用探针）。

## 文件一览

| 文件 | 描述什么 | 不写什么 | 主要消费者 |
|------|----------|----------|------------|
| **`sites.json`** | 站点身份、URL、`protocol`（传输面）、`supported_models`、`api_key_env` | 测哪些 model、族 → Agent 映射 | Layer 1；LiteLLM 出站 URL |
| **`assess-plan.json`** | 模型族 `families`、Layer 2 wire、Layer 3 模型与 OpenCode provider | 站点 URL、密钥 | `assess-protocol`；`write-litellm-config`；`t_*` |
| **`provider-profiles.json`** | 第三方平台 profile：一个平台多入口、多 Key、多协议、目标模型 | Agent / LiteLLM E2E | `assess-provider` |
| **`.env`** | API Key 值 | 站点结构 | 全部（Git 忽略） |

## 模型族 → Agent（评估主轴）

| 族 `family` | 用户场景主 Agent | Layer 2 默认 wire | Layer 3 默认 Agent |
|-------------|------------------|-------------------|---------------------|
| **`gpt`** | **Codex** | `chat` + `responses` | OpenCode + Codex |
| **`anthropic`** | **Claude Code** | `chat` + `messages` | OpenCode + Claude |
| **`other`** | （仅探针） | `chat` | OpenCode |

- **OpenCode**：每个族的 **通用 chat 探针**（连通、流式、真伪 smoke），不替代该族主 Agent 的 L4 结论。
- **`sites.json` → `protocol`**：仅限制 wire 与 `sites` 传输面的交集（如 `openai` 站不盲测 `messages`）；**不**决定「测哪些族」。

多族站点（如 `test_gpt_claude`）须 **`--family gpt`** 或 **`--family anthropic`** 跑 Layer 2–3；仅一种族时可省略。

## 三种「模型列表」（勿混）

| 来源 | 含义 | 用于 |
|------|------|------|
| **`sites.json` → `supported_models`** | 文档宣称 model id | Layer 1 对照 catalog |
| **`GET /v1/models`** | 运行时 catalog | Layer 1 分支 |
| **`families.<name>.models`** | 本实验要测的 model id | Layer 2–3 |

## `assess-plan.json` 字段

| 路径 | 说明 |
|------|------|
| `model_families` | 全局族定义（`primary_agent`、`layer2_wires`、`layer3_agents`） |
| `sites.<id>.families.<name>` | `{ "models": [...], "layer3": { "models": {...}, "agents": [...] } }` |
| `sites.<id>.layer3.opencode` | 站点级 OpenCode provider（各族共享） |
| `smoke_scenarios[]` | Layer 3 smoke；`model_probe` 对照 `layer3.models` |

`profiles` 为 **`families` 的废弃别名**；CLI **`--profile`** 等同 **`--family`**。

**族推断**（未写 `--family` 时）：单族站自动选中；多族站 `codex`→`gpt`、`claude`→`anthropic`、`opencode`→`gpt`（若存在）。`t_*` 与 `assess-source` 共用该逻辑。

## 配置 → 脚本映射

```text
sites.json
  └─ assess-platform.sh          Layer 1

sites.json + assess-plan.json + --family
  └─ assess-protocol.sh          Layer 2
  └─ litellm-proxy.sh / t_*      Layer 3
  └─ assess-source.sh            Layer 1–3 一键

run-user-side-compat.sh          L1 一次 + 按族或 --agents 批量 L3
assess-family.sh               **推荐**：一族 L1–2 + 族内全部 Agent L3（默认 --smoke）
assess-provider.sh             第三方平台轻量体检：profile API 直测，不跑 Agent / LiteLLM
```

## 第三方平台 profile 评估

`provider-profiles.json` 面向接入前小体检；它与 `sites.json` / `assess-plan.json` 独立。适合一个平台同时提供 OpenAI-compatible 与 Anthropic-compatible 入口，且不同模型族需要不同令牌的情况。

```bash
cp provider-profiles.example.json provider-profiles.json
# 在 .env 中填写 provider-profiles.json 里的 api_key_env
./scripts/assess-provider.sh --platform example --write-report
./scripts/assess-provider.sh --platform example --provider-profile openai_gpt --cache-check
```

评估内容：

- `GET /v1/models` 与 catalog 对比。
- 目标模型 × wire 最小调用：`chat` / `responses` / `messages`。
- 对可用 wire 做 stream 基础检查。
- 轻量 smoke：普通生成、JSON、代码、模型自报。
- 轻量可靠性：默认 5 次连续请求；可选 `--concurrency N`。
- provider-reported usage 合理性检查：保留原始 usage，归一化 input/output/cache/reasoning，并用本地粗估与控制变量发现明显异常。
- 可选 cache 行为观察：OpenAI/GPT 自动前缀缓存、Anthropic/Claude `cache_control: {"type":"ephemeral"}`。

注意：usage 与 cache 都是平台自报加行为观察，不能证明真实账单；异常只表示需要账单侧或后台日志复核。

## 报告

`docs/reports/{report_domain}-源评估报告-{YYYY-MM-DD}.md` — 范围须含 **`family`** 与 **主 Agent**（自动生成）。

```bash
cd experiment/user-side && source .env
./scripts/assess-source.sh --site ai.oai.red --family gpt --agent codex --write-report
./scripts/assess-family.sh --site ai.oai.red --family gpt --smoke
./scripts/assess-family.sh --site test_gpt_claude --family gpt --smoke --write-report
```

设计稿：[EC2-用户侧隔离实验点设计 §2.1](../../docs/experiment/EC2-用户侧隔离实验点设计.md#21-三层评估法)
