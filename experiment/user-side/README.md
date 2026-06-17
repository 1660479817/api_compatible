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
| 3 | 流式返回 | 对已通过的 wire 发 `stream=true` 请求 | SSE 标记、TTFB、总耗时 |
| 4 | Smoke 场景 | 普通生成、JSON、代码、模型自报 | 必选场景是否通过，模型自报只作弱信号 |
| 5 | 轻量稳定性与时延 | 默认 5 次顺序请求，可选并发请求 | 成功率、平均/p50/p95/max 时延 |
| 6 | Usage / token 统计 | 读取平台返回的 `usage`，归一化 token 字段 | input/output/total/cache/reasoning 汇总与合理性状态 |
| 7 | 缓存行为观察 | 可选 `--cache-check` | GPT 自动前缀缓存、Claude ephemeral cache 是否被观察到 |

第 6 阶段不会证明平台真实账单，只能发现明显异常：缺失 usage、字段不完整、`total_tokens < output_tokens`、缓存 token 大于输入 token、全 0、或平台返回值与本地粗估差异超过 3 倍。

第 7 阶段是行为观察，不作为硬性失败条件。GPT 类缓存由平台自动触发；Claude 类缓存需要请求体包含 `cache_control: {"type":"ephemeral"}`。

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
