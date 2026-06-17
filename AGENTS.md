# AGENTS.md - 本仓库协作规则

本仓库当前主流程是第三方模型平台 provider profile 评估。改动时优先保持 `experiment/user-side` 的代码、配置模板和文档一致。

## 目录职责

| 路径 | 说明 |
|------|------|
| `experiment/user-side/` | 评估实现、配置模板、运行脚本 |
| `docs/reports/` | 自动生成的平台评估报告 |
| `docs/research/` | 背景参考资料 |
| `upstream/` | 可选参考源码拉取目录，拉取内容不提交 |

## 安全

- 禁止提交 `.env`、`.runtime/`、真实 API Key、含密钥的配置。
- `provider-profiles.example.json` 只写示例域名和示例变量名。
- 报告中只记录 `api_key_env`，不记录密钥值。
- usage/token 检查只能写成合理性观察，不写成账单审计结论。

## 文档同步

修改评估流程、配置字段或输出格式时，同步更新：

- [README.md](./README.md)
- [experiment/user-side/README.md](./experiment/user-side/README.md)
- [experiment/user-side/CONFIG.md](./experiment/user-side/CONFIG.md)
- [experiment/user-side/AGENTS.md](./experiment/user-side/AGENTS.md)
- [docs/reports/README.md](./docs/reports/README.md)

## 验证

提交前至少运行：

```bash
cd experiment/user-side
python -m py_compile lib/maas.py
python lib/maas.py assess-provider --help
python -m json.tool provider-profiles.example.json
```
