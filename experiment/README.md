# experiment — 实验设计的可复现实现

本目录与 [`docs/experiment/`](../docs/experiment/) **一一对应**：设计稿在文档，可运行骨架在子目录。新增实验点时，先写 `docs/experiment/*.md`，再在本目录增加同名 slug 子目录。

| 设计文档 | 代码目录 | 状态 |
|----------|----------|------|
| [EC2-用户侧隔离实验点设计](../docs/experiment/EC2-用户侧隔离实验点设计.md) | [user-side/](./user-side/) | 源 → LiteLLM → `t_*` 测试端点 |
| [EC2-中转站原型实验点设计](../docs/experiment/EC2-中转站原型实验点设计.md) | [gateway-prototype/](./gateway-prototype/) | 占位（Compose / Channel 脚本待实施） |
| [中转站语料采集插件设计](../docs/experiment/中转站语料采集插件设计.md) | [corpus-tap/](./corpus-tap/) | **Tap** 采集+存储 S0–S5；**分析**见 [analysis/ARCHITECTURE.md](./corpus-tap/analysis/ARCHITECTURE.md) |

**不在此目录**：[`upstream/`](../upstream/) 为 research 用参考源码 clone，不属于实验实现。

## 快速入口

```bash
# 标准：源 → LiteLLM → Agent
cd experiment/user-side
cp .env.example .env
./scripts/run-source-agent-test.sh --site <site-id> --agent claude --smoke

# 语料采集（插在中转站 New API 前端）
cd experiment/corpus-tap
cp .env.example .env
go run ./cmd/corpus-tap

# 首次建库 + 分析（需 LiteLLM）
make db-reset
make build-profile
# 见 corpus-tap/analysis/profile/.env.example
./bin/corpus-profile
```

协作细则：用户侧见 [user-side/AGENTS.md](./user-side/AGENTS.md)。
