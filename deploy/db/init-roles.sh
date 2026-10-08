#!/bin/bash
#
# 创建/校正三个最小权限数据库角色（幂等，可反复执行）
#
#   rag_migration —— 迁移专用：public schema 的 CREATE + 既有对象属主（可执行 DDL）
#   rag_app       —— 应用专用：仅业务表 SELECT/INSERT/UPDATE/DELETE
#   rag_backup    —— 备份专用：仅业务表 SELECT
#
# 说明：admin 是官方 postgres 镜像创建的超级用户，本脚本以 admin 身份执行。
#      口令取自 /run/secrets/，仅以 hex 字符生成，避免 SQL 引号转义问题。
#
set -euo pipefail

HOST="${POSTGRES_HOST:-postgres}"
PORT="${POSTGRES_PORT:-5432}"
DB="${POSTGRES_DB:-knowledge_base}"
ADMIN_USER="${POSTGRES_ADMIN_USER:-admin}"

read_secret() {
    local path="/run/secrets/$1"
    [ -r "${path}" ] || { echo "❌ 缺少密钥文件: ${path}" >&2; exit 1; }
    tr -d '\n' < "${path}"
}

ADMIN_PW="$(read_secret db_admin_password)"
MIGRATION_PW="$(read_secret db_migration_password)"
APP_PW="$(read_secret db_app_password)"
BACKUP_PW="$(read_secret db_backup_password)"

export PGPASSWORD="${ADMIN_PW}"
export PGCONNECT_TIMEOUT=10

echo "🔧 校正数据库角色（库=${DB} 管理员=${ADMIN_USER}）..."

psql -h "${HOST}" -p "${PORT}" -U "${ADMIN_USER}" -d "${DB}" \
    -v ON_ERROR_STOP=1 -q -w -X <<SQL
-- ---------- 1. 角色（不存在则建，存在则只重置口令/属性） ----------
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_migration') THEN
        CREATE ROLE rag_migration LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
        CREATE ROLE rag_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_backup') THEN
        CREATE ROLE rag_backup LOGIN;
    END IF;
END
\$\$;

ALTER ROLE rag_migration WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    PASSWORD '${MIGRATION_PW}';
ALTER ROLE rag_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    PASSWORD '${APP_PW}';
ALTER ROLE rag_backup WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    PASSWORD '${BACKUP_PW}';

-- ---------- 2. 连接与 schema 使用 ----------
GRANT CONNECT ON DATABASE ${DB} TO rag_migration, rag_app, rag_backup;
GRANT USAGE ON SCHEMA public TO rag_app, rag_backup;
GRANT USAGE, CREATE ON SCHEMA public TO rag_migration;

-- ---------- 3. 既有对象属主移交给 rag_migration（使其能执行 ALTER TABLE） ----------
DO \$\$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO rag_migration', r.tablename);
    END LOOP;
    FOR r IN SELECT viewname FROM pg_views WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER VIEW public.%I OWNER TO rag_migration', r.viewname);
    END LOOP;
    FOR r IN
        SELECT sequence_name FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO rag_migration', r.sequence_name);
    END LOOP;
END
\$\$;

-- ---------- 4. 业务权限 ----------
-- 应用：只做数据读写，不能改表结构
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rag_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_app;
-- 备份：只读
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rag_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_backup;

-- ---------- 5. 后续新建对象自动授权（属主为 rag_migration，故 FOR ROLE rag_migration） ----------
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migration IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migration IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO rag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_migration IN SCHEMA public
    GRANT SELECT ON TABLES TO rag_backup;
SQL

echo "✅ 数据库角色校正完成"
psql -h "${HOST}" -p "${PORT}" -U "${ADMIN_USER}" -d "${DB}" -q -w -X -tAc \
    "SELECT rolname FROM pg_roles WHERE rolname LIKE 'rag_%' ORDER BY rolname"