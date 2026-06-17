# 平台评估报告

本目录存放 `experiment/user-side` 自动生成的平台评估报告。

## 命名

```text
{platform}-平台评估报告-{YYYY-MM-DD}.md
```

示例：

```text
example-平台评估报告-2026-06-17.md
```

同一平台同日复测会覆盖同名报告；结构化证据保存在：

```text
experiment/user-side/.runtime/{platform}-provider-assess-{YYYYMMDD}.json
```

## 生成

```bash
cd experiment/user-side
./scripts/assess-provider.sh --platform <platform-id> --write-report
```

报告只记录测试事实和平台返回的 usage/token 字段。usage 合理性检查不是账单审计，缓存结果也只是行为观察。
