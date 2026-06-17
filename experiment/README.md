# experiment - 可运行评估实现

当前可运行主流程在 [user-side/](./user-side/)：第三方模型平台 provider profile 评估。

```bash
cd experiment/user-side
cp provider-profiles.example.json provider-profiles.json
cp .env.example .env
./scripts/assess-provider.sh --platform example --write-report
```

其他子目录为参考或后续扩展：

| 目录 | 说明 |
|------|------|
| [user-side/](./user-side/) | 平台 API 轻量评估 |
| [gateway-prototype/](./gateway-prototype/) | 网关原型占位 |
| [corpus-tap/](./corpus-tap/) | 语料采集实验 |
