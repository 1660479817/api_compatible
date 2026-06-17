# user-side 配置说明

本目录只有一份业务配置：`provider-profiles.json`。它描述第三方平台的多个 profile，每个 profile 是一组可独立调用的 API 入口。

## 文件

| 文件 | 职责 | 是否提交 |
|------|------|----------|
| `provider-profiles.example.json` | 配置模板 | 是 |
| `provider-profiles.json` | 本地实际平台配置 | 否 |
| `.env.example` | 密钥变量模板 | 是 |
| `.env` | 本地密钥值 | 否 |

## `provider-profiles.json`

顶层字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `repeat` | number | 默认顺序重复请求次数，默认 5 |
| `concurrency` | number | 默认并发请求数，默认 0 |
| `timeout_sec` | number | 单次请求超时秒数，默认 120 |
| `platforms` | object | 平台集合，key 是平台 ID |

## 延迟指标

报告中有三类延迟，含义不同：

| 报告位置 | 指标 | 含义 |
|----------|------|------|
| `Stream` | `TTFB ms` | 流式请求发出后，收到第一行 SSE 数据的时间，近似首字/首包延迟 |
| `Reliability` | `Latency avg/p50/p95/max ms` | 默认短问题 `Reply with exactly OK.` 的完整响应耗时统计 |
| `Latency Probes` | `Short baseline` / `Medium task` | 每个可用模型的短问题和中等任务完整响应耗时 |

短问题适合筛平台基础响应速度；中等任务更接近交互式客户端体验，但仍不覆盖长上下文、长输出、多轮工具调用或限流压测。

平台字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 展示名 |
| `profiles` | object | profile 集合 |
| 其他字段 | any | 可作为 profile 默认值，被 profile 内同名字段覆盖 |

profile 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `base_url` | string | 是 | API 入口；可写到 `/v1`，脚本会自动拼接端点 |
| `api_key_env` | string | 是 | `.env` 中的密钥变量名 |
| `protocol` | string | 是 | `openai`、`anthropic`、`mixed`，也支持 `*-compatible` 别名 |
| `wires` | array | 否 | 要测的 wire：`chat`、`responses`、`messages` |
| `models` | array/string | 是 | 目标模型 ID |
| `cache_test` | string | 否 | `openai_auto_prefix` 或 `anthropic_ephemeral` |
| `repeat` | number | 否 | 覆盖顶层重复次数 |
| `concurrency` | number | 否 | 覆盖顶层并发数 |
| `timeout_sec` | number | 否 | 覆盖顶层超时 |

## 多入口、多 Key

同一平台如果同时提供 GPT 和 Claude 两类入口，建议拆成两个 profile：

```json
{
  "platforms": {
    "vendor": {
      "profiles": {
        "openai_gpt": {
          "base_url": "https://api.vendor.example/v1",
          "api_key_env": "VENDOR_OPENAI_KEY",
          "protocol": "openai",
          "wires": ["chat", "responses"],
          "models": ["gpt-example"]
        },
        "anthropic_claude": {
          "base_url": "https://claude.vendor.example",
          "api_key_env": "VENDOR_ANTHROPIC_KEY",
          "protocol": "anthropic",
          "wires": ["messages"],
          "models": ["claude-example"]
        }
      }
    }
  }
}
```

这样报告会在同一个平台下分别给出两个 profile 的协议、时延、usage 与缓存观察结论。

## Usage / token 统计

脚本只读取平台响应中的 `usage`，不会调用平台后台账单。归一化字段包括：

| 归一化字段 | 常见来源 |
|------------|----------|
| `input_tokens` | `input_tokens`、`prompt_tokens` |
| `output_tokens` | `output_tokens`、`completion_tokens` |
| `total_tokens` | `total_tokens` 或 input + output |
| `cache_read_tokens` | `cache_read_input_tokens`、`prompt_tokens_details.cached_tokens`、`input_tokens_details.cached_tokens` |
| `cache_write_tokens` | `cache_creation_input_tokens`、`input_tokens_details.cache_creation_tokens` |
| `reasoning_tokens` | `reasoning_tokens`、`completion_tokens_details.reasoning_tokens` |

合理性检查只做粗筛：本地按字符估算 token，并标记缺失、字段不完整、明显不可能或差异过大的 usage。它不能证明平台一定按真实 token 计费。

## 缓存观察

`--cache-check` 会对每个 profile 选择一个可用模型做两次相同前缀请求：

| 类型 | 条件 | 观察字段 |
|------|------|----------|
| `openai_auto_prefix` | 长前缀完全一致，缓存由平台自动触发 | `prompt_tokens_details.cached_tokens` 或同类字段 |
| `anthropic_ephemeral` | 请求体显式加入 `cache_control: {"type":"ephemeral"}` | `cache_creation_input_tokens`、`cache_read_input_tokens` |

未观察到缓存不一定表示平台不支持，可能是阈值、TTL、模型、网关隐藏 usage 或计费策略导致。
