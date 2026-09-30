# RAG 知识库助手 - 前端

React + TypeScript + Ant Design 实现的现代化对话界面

## 功能特性

- ✅ 部门登录与权限控制
- ✅ 实时对话界面
- ✅ 意图识别开关
- ✅ Markdown 渲染
- ✅ 图片展示
- ✅ 来源文档展示
- ✅ 响应式设计

## 技术栈

- React 18
- TypeScript
- Ant Design 5
- Zustand (状态管理)
- Vite (构建工具)
- Axios (HTTP 客户端)
- React Markdown (Markdown 渲染)

## 快速开始

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run dev
```

访问 http://localhost:3000

### 生产构建

```bash
npm run build
```

构建产物在 `dist` 目录

## 项目结构

```
src/
├── components/          # 组件
│   ├── Auth/           # 登录相关
│   ├── Chat/           # 对话相关
│   └── Layout/         # 布局相关
├── hooks/              # 自定义 Hooks
├── services/           # API 服务
├── store/              # 状态管理
├── styles/             # 全局样式
├── types/              # TypeScript 类型
├── App.tsx             # 主应用
└── main.tsx            # 入口文件
```

## API 配置

后端 API 地址在 `vite.config.ts` 中配置：

```typescript
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true
  }
}
```

## 环境变量

可选创建 `.env` 文件：

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## 部署

### Docker 部署

参考根目录的 `docker-compose.yml`

### Nginx 部署

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    root /path/to/dist;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://localhost:8000;
    }
}
```

## 开发规范

- 使用 TypeScript 严格模式
- 遵循 ESLint 规则
- 组件使用函数式 + Hooks
- 状态管理使用 Zustand
- API 调用统一通过 services 层
