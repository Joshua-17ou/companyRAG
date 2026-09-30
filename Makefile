.PHONY: help build up down logs seed clean test install

help:
	@echo "RAG Knowledge Base System - Development Commands"
	@echo ""
	@echo "Usage:"
	@echo "  make install       - 安装Python依赖"
	@echo "  make build         - 构建Docker镜像"
	@echo "  make up            - 启动Docker Compose服务"
	@echo "  make down          - 停止Docker Compose服务"
	@echo "  make logs          - 查看服务日志"
	@echo "  make seed          - 生成测试数据"
	@echo "  make run           - 启动FastAPI服务"
	@echo "  make test          - 运行测试"
	@echo "  make clean         - 清理临时文件"

install:
	@echo "Installing Python dependencies..."
	pip install -r requirements.txt

build:
	@echo "Building Docker images..."
	docker-compose build

up:
	@echo "Starting Docker Compose services..."
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	sleep 5
	@echo "Services started successfully!"
	@echo "- Qdrant: http://localhost:6333"
	@echo "- PostgreSQL: localhost:5432"
	@echo "- Redis: localhost:6379"
	@echo "- MinIO: http://localhost:9001"

down:
	@echo "Stopping Docker Compose services..."
	docker-compose down

logs:
	docker-compose logs -f

seed:
	@echo "Generating test data..."
	python -m scripts.seed_data

run:
	@echo "Starting FastAPI server..."
	python -m uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --reload

test:
	@echo "Running tests..."
	pytest tests/ -v --cov=src

clean:
	@echo "Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov

init-dev:
	@echo "Initializing development environment..."
	make install
	make up
	sleep 10
	make seed
	@echo "Development environment is ready!"
	@echo "You can now run: make run"
