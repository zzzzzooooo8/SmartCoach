# SmartCoach 前端

SmartCoach 的 Next.js 16 前端，负责首次建档、对话交互、资料来源展示与每日减脂数据面板。

## 本地开发

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

页面默认访问 `http://127.0.0.1:8000` 的后端。如需修改：

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## 验证

```powershell
pnpm lint
pnpm build
```

完整项目说明见仓库根目录的 [`README.md`](../README.md)。
