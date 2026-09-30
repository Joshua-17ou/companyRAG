# CompanyRAG — 企业知识库问答系统

基于 RAG（检索增强生成）的企业内部知识库问答系统，支持扫描版 PDF 入库、多轮对话、意图识别与权限过滤。

## 系统架构

```
用户浏览器
    │
    ▼
React 前端 (端口 3000)
    │  REST / SSE
    ▼
FastAPI 后端 (端口 8000)
    ├── 意图识别 (IntentAgent)
    ├── 向量检索 (LlamaIndex + Qdrant)
    ├── Reranker (本地模型)
    └── LLM 生成答案 (DeepSeek / Claude)
         │
    ┌────┴────┐
    ▼         ▼
Qdrant    PostgreSQL
向量库      关系库
```

## 主要功能

- **文档入库**：支持 `.md`、`.txt`、`.pdf`（含扫描版 OCR）
- **智能问答**：流式 SSE 输出，支持多轮对话上下文
- **意图识别**：自动识别查询医院、文档类型，优化检索精度
- **权限过滤**：按部门（`owner_dept`）控制文档可见范围
- **页图展示**：扫描版 PDF 命中时返回原页图片和 OCR bbox 高亮
- **知识库管理**：前端上传/删除文档，查看入库状态

## 快速开始（Docker Compose）

```bash
# 1. 复制环境变量配置
cp .env.example .env
# 编辑 .env，填入 LLM API Key 等必要配置

# 2. 启动全部服务
docker compose up -d

# 3. 访问
#   前端：http://localhost:3000
#   后端 API：http://localhost:8000
#   API 文档：http://localhost:8000/docs
```

## 环境变量

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://admin:password@postgres:5432/knowledge_base` |
| `QDRANT_URL` | Qdrant 地址 | `http://qdrant:6333` |
| `QDRANT_COLLECTION_NAME` | 向量集合名 | `rag_documents` |
| `LLM_PROVIDER` | LLM 提供商 | `deepseek` 或 `claude` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | `sk-...` |
| `DEEPSEEK_API_BASE` | DeepSeek API 地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-chat` |
| `CLAUDE_API_KEY` | Claude API Key（可选） | `sk-ant-...` |
| `PDF_OCR_ENABLED` | 是否启用扫描版 PDF OCR | `true` |
| `PDF_OCR_DPI` | OCR 渲染分辨率 | `200` |
| `ANSWER_MAX_TOKENS` | 生成答案最大 token 数 | `4096` |

完整配置项见 `src/backend/core/config.py`。

## 项目结构

```
.
├── src/backend/
│   ├── api/routes/         # FastAPI 路由（ingestion, images, sessions, auth）
│   ├── agent/
│   │   ├── intent_agent.py # 意图识别与查询重写
│   │   ├── rag_orchestrator.py
│   │   └── prompts/        # 集中管理所有提示词
│   ├── ingestion/
│   │   ├── rag_service.py  # 核心 RAG 服务（搜索 + 生成）
│   │   ├── chunking.py     # 文档切块策略
│   │   └── scanned_pdf_ocr.py  # 扫描版 PDF OCR
│   ├── db/                 # SQLAlchemy 模型
│   └── core/               # 配置、日志
├── frontend/               # React + TypeScript 前端
├── tests/                  # 单元测试与回归测试
├── scripts/                # 数据库初始化等脚本
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 切分策略

上传文档时选择切分策略（建议选**自动识别**）：

| 策略 | 适用场景 |
|------|----------|
| `auto` | 自动检测，推荐默认 |
| `scanned_pdf` | 扫描版 PDF（OCR 文本，有页码标记） |
| `markdown` | Markdown 格式文档 |
| `hospital_markdown` | 医院 SPD 操作指南（按医院边界切分） |
| `character` | 普通纯文本 |

## 运行测试

```bash
python -m pytest tests/ -q
```

## License

MIT
