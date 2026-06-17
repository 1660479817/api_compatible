# AGENTS.md - user-side 协作规则

本目录只维护 provider profile 评估流程。改动代码或文档时，保持 `README.md`、`CONFIG.md`、`provider-profiles.example.json` 和 `scripts/assess-provider.sh` 一致。

## 入口

```bash
cd experiment/user-side
./scripts/assess-provider.sh --platform <platform-id> --write-report
python3 lib/maas.py assess-provider --config provider-profiles.json --platform <platform-id>
```

## 配置

| 路径 | 规则 |
|------|------|
| `provider-profiles.example.json` | 只放模板和假 key 变量名 |
| `provider-profiles.json` | 本地真实平台配置，Git 忽略 |
| `.env.example` | 只放变量模板 |
| `.env` | 本地密钥，Git 忽略 |
| `.runtime/` | 运行生成物，Git 忽略 |

## 报告

`--write-report` 会写入 `docs/reports/{platform}-平台评估报告-{YYYY-MM-DD}.md`。报告正文保持事实记录，不手写密钥，不把 usage 合理性检查描述成真实账单审计。

## 验证

提交前至少运行：

```bash
python -m py_compile lib/maas.py
python lib/maas.py assess-provider --help
python -m json.tool provider-profiles.example.json
```
