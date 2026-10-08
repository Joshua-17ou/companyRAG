#!/bin/bash
#
# 生产环境应用启动垫片（由 docker-compose.prod.yml 的 app 服务覆盖 ENTRYPOINT 调用）
#
# 职责：把 /run/secrets/ 下的密钥组装成应用需要的环境变量，然后前台启动 FastAPI。
# 与开发环境不同点：不启动 Streamlit，密钥不出现在任何配置文件里。
#
set -euo pipefail

SECRETS_DIR="/run/secrets"

read_secret() {
    local name="$1"
    local path="${SECRETS_DIR}/${name}"
    if [ ! -r "${path}" ]; then
        echo "❌ 缺少密钥文件: ${path}" >&2
        echo "   请检查 /opt/company-rag/shared/secrets/ 是否已按规范创建（chown root:10001, chmod 0440）" >&2
        exit 1
    fi
    # 去掉文件末尾换行，避免 DATABASE_URL 里混入 \n
    tr -d '\n' < "${path}"
}

echo "🔐 从 ${SECRETS_DIR} 组装生产环境变量..."

# 应用数据库账号：仅数据读写，无 DDL 权限
export DATABASE_URL="postgresql://rag_app:$(read_secret db_app_password)@postgres:5432/knowledge_base"

# MinIO：使用 root 账号（单实例自建，最小可用）
export MINIO_SECRET_KEY="$(read_secret minio_root_password)"

# LLM
export DEEPSEEK_API_KEY="$(read_secret deepseek_api_key)"

# 原网页版登录态签名密钥
export SECRET_KEY="$(read_secret app_secret_key)"

# 飞书免登
export LARK_APP_SECRET="$(read_secret lark_app_secret)"
export LARK_JWT_SECRET="$(read_secret lark_jwt_secret)"

echo "✅ 环境变量组装完成，启动 FastAPI..."

cd /app
exec python /app/scripts/start_backend.py