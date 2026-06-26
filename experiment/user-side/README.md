# user-side - 第三方模型平台评估

本目录只保留新的 provider profile 测试流程，用于接入第三方模型平台前做轻量体检。它直接请求平台 API，不做客户端端到端跑通测试。

```text
assess-provider -> provider profile(base_url + api_key_env + protocol + models)
```

## 快速开始

```bash
cd experiment/user-side
cp provider-profiles.example.json provider-profiles.json
cp .env.example .env

# 编辑 provider-profiles.json：配置平台、profile、base_url、api_key_env、protocol、models
# 编辑 .env：填写 api_key_env 对应的密钥

./scripts/assess-provider.sh --platform example --write-report
./scripts/assess-provider.sh --platform example --provider-profile openai_gpt --cache-check
```

也可以直接调用 Python：

```bash
python3 lib/maas.py list-profiles --config provider-profiles.json
python3 lib/maas.py assess-provider --config provider-profiles.json --platform example --repeat 5 --write-report
```

## 命令行参数

入口脚本 `scripts/assess-provider.sh` 会先加载 `.env`，再把参数原样转给 `python3 lib/maas.py assess-provider`。下面两个子命令的参数含义相同；`assess-provider.sh` 只支持 `assess-provider` 子命令的参数。

### `list-profiles` — 列出已配置的 profile

只读配置，不发 API 请求。用于确认 platform / profile ID、协议、wire、模型是否正确。

```bash
python3 lib/maas.py list-profiles [--config PATH] [--platform ID] [--provider-profile ID]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--config PATH` | 否 | 配置文件路径，默认 `provider-profiles.json` |
| `--platform ID` | 否 | 只列出指定平台；省略则列出全部平台 |
| `--provider-profile ID` | 否 | 只列出指定 profile；通常与 `--platform` 一起用 |

示例：

```bash
python3 lib/maas.py list-profiles
python3 lib/maas.py list-profiles --platform krill
python3 lib/maas.py list-profiles --platform krill --provider-profile openai_gpt
```

### `assess-provider` — 运行平台评估

对匹配的 profile 执行完整评估流程（见下文「测试流程」）。Shell 与 Python 调用等价：

```bash
./scripts/assess-provider.sh [options]
python3 lib/maas.py assess-provider [options]
```

**参数速查：**

| 参数 | 含义 |
|------|------|
| `--config PATH` | 配置文件，默认 `provider-profiles.json` |
| `--platform ID` | 只测某个平台（如 `krill`） |
| `--provider-profile ID` | 只测该平台下某个 profile（如 `openai_gpt`） |
| `--repeat N` | 稳定性测试重复次数，默认 5 |
| `--concurrency N` | 额外并发数，默认 0（不并发） |
| `--timeout SEC` | 单次请求超时，默认 120 秒 |
| `--cache-check` | 开启缓存观察（额外 2 次相同前缀请求） |
| `--write-report` | 生成 Markdown 报告 |
| `--date YYYY-MM-DD` | 输出文件名中的日期 |
| `--json` | 终端打印完整 JSON |
| `-h` / `--help` | 帮助（仅 Shell 脚本） |

以上参数均可省略；省略 `--platform` / `--provider-profile` 时评估全部平台与 profile。优先级：命令行 > profile 内配置 > 配置文件顶层默认值。

#### 筛选参数：`--platform` 与 `--provider-profile`

配置结构是 `platforms.<platform_id>.profiles.<profile_id>`。两个参数组合决定评估范围：

| 命令 | 评估范围 |
|------|----------|
| 无筛选 | 配置文件中所有平台、所有 profile |
| `--platform krill` | krill 平台下的 openai_gpt + anthropic_claude |
| `--platform krill --provider-profile openai_gpt` | 仅 krill 的 openai_gpt 一个 profile |

profile 决定实际请求的 `base_url`、`api_key_env`、`protocol`、`wires`、`models`；同一平台下不同 profile 可对应不同入口、不同 Key、不同协议。

#### 负载参数：`--repeat`、`--concurrency`、`--timeout`

这三个参数只影响**第 5 阶段（稳定性与时延）**，也可在 `provider-profiles.json` 顶层或单个 profile 内设置；命令行会覆盖配置值，profile 内字段再覆盖顶层。

- `--repeat 5`：对主 wire 连续发 5 次相同请求，统计成功率与 p50/p95 时延
- `--concurrency 3`：在顺序请求之外，再并发 3 路请求（0 表示不做并发）
- `--timeout 120`：任意单次请求超过 120 秒则记为失败

#### 输出参数：`--write-report`、`--date`、`--json`

- 不加 `--write-report`：只写 `.runtime/{platform}-provider-assess-{YYYYMMDD}.json`，终端打印摘要
- 加 `--write-report`：额外写 `docs/reports/{platform}-平台评估报告-{YYYY-MM-DD}.md`
- `--date 2026-06-17`：固定输出文件名中的日期，便于复现或补跑历史报告
- `--json`：适合管道处理或调试，会把完整结果打印到 stdout

#### 缓存参数：`--cache-check`

开启后，对每个被评估的 profile **额外**做两次「相同长前缀、不同后缀」的请求，观察平台是否在 `usage` 里返回缓存 token。类型由 profile 的 `cache_test` 决定：

| `cache_test` | 适用协议 | 做法 | 观察字段 |
|--------------|----------|------|----------|
| `openai_auto_prefix` | OpenAI / GPT 类 | 长前缀完全一致，靠平台自动缓存 | `cached_tokens`、`cache_read_tokens` |
| `anthropic_ephemeral` | Anthropic / Claude 类 | 前缀加 `cache_control: {"type":"ephemeral"}` | 第 1 次 `cache_write`，第 2 次 `cache_read` |

缓存结果状态包括 `observed`、`not_observed`、`creation_only`、`unsupported_or_hidden` 等。**不影响 A/B/C/D 评级**，未观察到也不代表平台不支持。

#### 退出码

- 评估完成且所有被测平台等级不是 D：`0`
- 任一被测平台等级为 D：`1`（可用于 CI 门禁）

#### 常用组合示例

```bash
# 列出 krill 平台下所有 profile
python3 lib/maas.py list-profiles --platform krill

# 只测 krill 的 GPT 入口，带缓存观察
./scripts/assess-provider.sh --platform krill --provider-profile openai_gpt --cache-check

# 测 krill 全部 profile，生成报告，稳定性重复 10 次
./scripts/assess-provider.sh --platform krill --repeat 10 --write-report

# 测全部已配置平台，输出完整 JSON
./scripts/assess-provider.sh --json

# 指定配置文件与报告日期
./scripts/assess-provider.sh --config ./provider-profiles.json --platform apikey3 --date 2026-06-17 --write-report
```

## 配置模型

一个平台可以有多个 profile。profile 用来表达同一平台下不同入口、不同协议、不同 Key、不同模型族的组合。

```json
{
  "repeat": 5,
  "concurrency": 0,
  "timeout_sec": 120,
  "platforms": {
    "example": {
      "name": "Example Provider",
      "profiles": {
        "openai_gpt": {
          "base_url": "https://api.example.com/v1",
          "api_key_env": "EXAMPLE_OPENAI_KEY",
          "protocol": "openai",
          "wires": ["chat", "responses"],
          "models": ["gpt-example"],
          "cache_test": "openai_auto_prefix"
        },
        "anthropic_claude": {
          "base_url": "https://claude.example.com",
          "api_key_env": "EXAMPLE_ANTHROPIC_KEY",
          "protocol": "anthropic",
          "wires": ["messages"],
          "models": ["claude-example"],
          "cache_test": "anthropic_ephemeral"
        }
      }
    }
  }
}
```

字段说明见 [CONFIG.md](./CONFIG.md)。

## 测试流程

| 阶段 | 测什么 | 方法 | 产出 |
|------|--------|------|------|
| 1 | Profile 与鉴权 | 读取 `base_url`、`api_key_env`，请求 `GET /v1/models` | catalog 是否可达、目标模型是否出现在列表 |
| 2 | 协议面 | 对目标 `models × wires` 发最小请求 | `chat` / `responses` / `messages` 是否返回有效文本 |
| 3 | 流式返回 | 对已通过的 wire 发 `stream=true` 请求 | SSE 标记、首包 TTFB、总耗时 |
| 4 | Smoke 场景 | 普通生成、JSON、代码、模型自报 | 必选场景是否通过，模型自报只作弱信号 |
| 5 | 轻量稳定性与短请求时延 | 默认 5 次短问题顺序请求，可选并发请求 | 成功率、平均/p50/p95/max 完整响应时延 |
| 6 | 延迟探针 | 每个可用模型跑短问题和中等任务各一次 | 区分短请求基线与轻量真实任务的完整响应时延 |
| 7 | Usage / token 统计 | 读取平台返回的 `usage`，归一化 token 字段 | input/output/total/cache/reasoning 汇总与合理性状态 |
| 8 | 缓存行为观察 | 可选 `--cache-check` | GPT 自动前缀缓存、Claude ephemeral cache 是否被观察到 |

Reliability 使用简短问题，适合做短请求延迟基线；Latency Probes 会额外给出中等任务耗时，更接近 Codex / Claude Desktop 的交互任务，但仍不等于长上下文或多轮工具调用测试。

第 7 阶段不会证明平台真实账单，只能发现明显异常：缺失 usage、字段不完整、`total_tokens < output_tokens`、缓存 token 大于输入 token、全 0、或平台返回值与本地粗估差异超过 3 倍。

第 8 阶段是行为观察，不作为硬性失败条件。GPT 类缓存由平台自动触发；Claude 类缓存需要请求体包含 `cache_control: {"type":"ephemeral"}`。

## 输出

| 产物 | 路径 |
|------|------|
| 结构化 JSON | `.runtime/{platform}-provider-assess-{YYYYMMDD}.json` |
| Markdown 报告 | `docs/reports/{platform}-平台评估报告-{YYYY-MM-DD}.md` |

报告由 `--write-report` 自动生成；同平台同日复测会覆盖同名文件。

## 评级

| 等级 | 含义 |
|------|------|
| A | 协议、stream、smoke、usage、轻量稳定性均未发现明显问题 |
| B | 可用，但有 usage 缺失/可疑、stream 异常或少量稳定性问题 |
| C | 协议能通，但必选 smoke 失败 |
| D | 目标协议完全不可用、usage 明显无效，或短测成功率低于等于 60% |

## 目录

```text
experiment/user-side/
├── provider-profiles.example.json
├── .env.example
├── CONFIG.md
├── AGENTS.md
├── lib/
│   └── maas.py
├── scripts/
│   └── assess-provider.sh
└── .runtime/        # 生成物，Git 忽略
```
