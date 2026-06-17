# API Compatible - 第三方模型平台轻量评估

本仓库用于在接入第三方模型平台前，快速检查平台 API 是否足够可用、稳定、可观测。当前主流程是 `experiment/user-side` 下的 provider profile 评估。

它关注的是平台 API 本身：入口、鉴权、模型目录、协议面、stream、轻量 smoke、usage/token 返回、时延统计和缓存行为观察。

## 快速开始

```bash
cd experiment/user-side
cp provider-profiles.example.json provider-profiles.json
cp .env.example .env

# 填写 provider-profiles.json 与 .env
./scripts/assess-provider.sh --platform example --write-report
```

常用命令：

```bash
python3 lib/maas.py list-profiles --config provider-profiles.json
python3 lib/maas.py assess-provider --config provider-profiles.json --platform example --repeat 5
python3 lib/maas.py assess-provider --config provider-profiles.json --platform example --cache-check --write-report
```

## 测试流程

| 阶段 | 内容 |
|------|------|
| 1 | Profile、鉴权与 `GET /v1/models` |
| 2 | `chat` / `responses` / `messages` 最小协议请求 |
| 3 | stream 基础检查与 TTFB |
| 4 | 普通生成、JSON、代码、模型自报 smoke |
| 5 | 默认 5 次轻量稳定性请求，可选并发 |
| 6 | provider-reported usage/token 归一化与合理性检查 |
| 7 | 可选缓存行为观察 |

usage 与缓存结论都是“平台返回值 + 行为观察”，不是账单审计。发现异常时，应再用平台后台账单或服务端日志复核。

## 配置

配置文件是 `experiment/user-side/provider-profiles.json`，模板见 [provider-profiles.example.json](./experiment/user-side/provider-profiles.example.json)。

一个平台可以维护多个 profile，用来表达不同入口、不同协议、不同令牌和不同模型族：

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

字段说明见 [experiment/user-side/CONFIG.md](./experiment/user-side/CONFIG.md)。

## 输出

| 产物 | 路径 |
|------|------|
| 结构化 JSON | `experiment/user-side/.runtime/{platform}-provider-assess-{YYYYMMDD}.json` |
| Markdown 报告 | `docs/reports/{platform}-平台评估报告-{YYYY-MM-DD}.md` |

## 仓库结构

```text
api_compatible/
├── experiment/user-side/     # provider profile 评估实现
├── docs/reports/             # 自动生成的平台评估报告
├── docs/research/            # 参考资料
└── upstream/                 # 可选参考源码拉取目录
```

协作规则见 [AGENTS.md](./AGENTS.md)。
