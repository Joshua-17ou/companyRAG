#!/usr/bin/env python
"""启动FastAPI后端服务"""
import uvicorn
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backend.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info"
    )
