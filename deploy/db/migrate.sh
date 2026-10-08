#!/bin/bash
#
# 顺序执行 deploy/migrations/*.sql（以 rag_migration 身份，具备 DDL 权限）
#
# 约定：
#   - 文件名以数字前缀排序，例如 001_chat_tables.sql
#   - 每个迁移脚本必须自身幂等（CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS）
#   - 单个文件整体在一个事务里执行，失败即整体回滚并中断发布
#
set -euo pipefail

HOST="${POSTGRES_HOST:-postgres}"
PORT="${POSTGRES_PORT:-5432}"
DB="${POSTGRES_DB:-knowledge_base}"
MIGRATION_USER="${POSTGRES_MIGRATION_USER:-rag_migration}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/deploy/migrations}"

read_secret() {
    local path="/run/secrets/$1"
    [ -r "${path}" ] || { echo "❌ 缺少密钥文件: ${path}" >&2; exit 1; }
    tr -d '\n' < "${path}"
}

export PGPASSWORD="$(read_secret db_migration_password)"
export PGCONNECT_TIMEOUT=10

if [ ! -d "${MIGRATIONS_DIR}" ]; then
    echo "❌ 迁移目录不存在: ${MIGRATIONS_DIR}" >&2
    exit 1
fi

shopt -s nullglob
files=("${MIGRATIONS_DIR}"/*.sql)
if [ ${#files[@]} -eq 0 ]; then
    echo "⚠️  ${MIGRATIONS_DIR} 下没有 .sql 迁移文件，跳过"
    exit 0
fi

mapfile -t sorted < <(printf '%s\n' "${files[@]}" | sort)

echo "🗃️  开始执行迁移（库=${DB} 身份=${MIGRATION_USER}，共 ${#sorted[@]} 个文件）..."
for f in "${sorted[@]}"; do
    echo "▶ $(basename "$f")"
    psql -h "${HOST}" -p "${PORT}" -U "${MIGRATION_USER}" -d "${DB}" \
        -v ON_ERROR_STOP=1 --single-transaction -q -w -X -f "$f"
done

echo "✅ 迁移全部执行完成"