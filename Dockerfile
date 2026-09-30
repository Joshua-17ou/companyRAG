FROM python:3.11-slim

WORKDIR /app

# 使用清华镜像源
RUN apt-get update && apt-get install -y sed && \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    apt-get update

# 安装系统依赖
RUN apt-get install -y \
    build-essential \
    gcc \
    g++ \
    postgresql-client \
    curl \
    git \
    libssl-dev \
    libffi-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# 升级pip
RUN pip install --upgrade pip setuptools wheel -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

# 复制requirements
COPY requirements.txt .

# 安装Python依赖（使用清华PyPI源）
RUN pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r requirements.txt

# 复制项目代码
COPY . .

# 创建模型缓存目录
RUN mkdir -p /app/models/embeddings /app/models/reranker

# 创建PDF处理目录（页图与原始PDF留存）
RUN mkdir -p /app/docs/pdf_pages /app/docs/pdf_source

ENV HF_HOME=/app/models/embeddings

# 创建启动脚本目录
RUN mkdir -p /app/scripts

# 复制启动脚本
COPY docker-entrypoint.sh /app/scripts/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/docker-entrypoint.sh
RUN chmod +x /app/scripts/start_backend.py

# 创建Streamlit配置目录
RUN mkdir -p ~/.streamlit
COPY streamlit_config.toml ~/.streamlit/config.toml

# 暴露端口
EXPOSE 8000 8501

# 启动脚本
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

