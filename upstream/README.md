# upstream — 参考源码（本地拉取）

按需 clone **OpenCode / New API / Codex** 上游仓库，用于对照 Relay、Agent wire 等实现。**不** 提交 Git，**不** 参与 `experiment/user-side/t_*` 运行。

```bash
./upstream/pull.sh newapi    # → upstream/newapi/
./upstream/pull.sh codex     # → upstream/codex/
./upstream/pull.sh opencode  # → upstream/opencode/
./upstream/pull.sh all       # 三者（默认）
```

| 目录 | 上游 | 用途 |
|------|------|------|
| `newapi/` | [QuantumNous/new-api](https://github.com/QuantumNous/new-api) | 中转站 Relay / Channel 对照 |
| `codex/` | [openai/codex](https://github.com/openai/codex) | Codex CLI / Responses wire |
| `opencode/` | [anomalyco/opencode](https://github.com/anomalyco/opencode) | OpenCode 配置与 provider |

阅读入口见 [New API 技术栈全景](../docs/research/NewAPI技术栈全景.md)、[LLM API 网关主流技术栈调研](../docs/research/LLM-API网关主流技术栈调研.md)。
