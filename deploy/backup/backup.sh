#!/bin/bash
#
# 数据库备份脚本（由生产机 crontab 每日调用）
#
# 产物（默认 /opt/company-rag/backups/daily/）：
#   ragdb_<ts>.dump      pg_dump -Fc 自定义格式备份（以只读账号 rag_backup 执行）
#   kb_<ts>.tar.gz       知识库原始文件归档（/opt/company-rag/shared/kb）
#   MANIFEST.tsv         台账：时间 类型 文件 字节 sha256 校验 异地
#
# 保留策略：仅保留最近 14 天，按「精确匹配本脚本自身产物命名」清理，不误删其他文件。
# 异地备份：未配置 OFFSITE_TARGET 时明确告警，绝不静默跳过。
#
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/company-rag}"
DAILY_DIR="${DAILY_DIR:-${BASE_DIR}/backups/daily}"
SHARED_ENV="${SHARED_ENV:-${BASE_DIR}/shared/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-${BASE_DIR}/current/docker-compose.prod.yml}"
KB_DIR="${KB_DIR:-${BASE_DIR}/shared/kb}"

RETAIN_DAYS="${RETAIN_DAYS:-14}"
# 异地备份目标（如 user@47.107.86.82:/opt/procurement-backup/）；未配置时告警
OFFSITE_TARGET="${OFFSITE_TARGET:-}"

TS="$(date +%Y%m%d_%H%M%S)"
DB_DUMP="${DAILY_DIR}/ragdb_${TS}.dump"
KB_TAR="${DAILY_DIR}/kb_${TS}.tar.gz"
MANIFEST="${DAILY_DIR}/MANIFEST.tsv"

mkdir -p "${DAILY_DIR}"

compose() {
    docker compose --env-file "${SHARED_ENV}" -f "${COMPOSE_FILE}" "$@"
}

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

size_of() {
    stat -c %s "$1"
}

echo "=== 备份开始 ${TS} ==="

# ---------- 1. 数据库逻辑备份 ----------
echo "→ pg_dump（身份 rag_backup）"
compose exec -T postgres bash -c \
    'PGPASSWORD="$(cat /run/secrets/db_backup_password)" pg_dump -U rag_backup -h 127.0.0.1 -d knowledge_base -Fc' \
    > "${DB_DUMP}"

if [ ! -s "${DB_DUMP}" ]; then
    echo "❌ 备份文件为空，判定失败" >&2
    rm -f "${DB_DUMP}"
    exit 1
fi

# ---------- 2. 校验：目录可读且包含业务主表 users 的数据段 ----------
echo "→ 校验备份可读性与关键表"
if compose exec -T postgres pg_restore --list < "${DB_DUMP}" | grep -q "TABLE DATA public users"; then
    DB_VERIFY="ok(users)"
else
    DB_VERIFY="FAIL(no users table data)"
    echo "❌ 校验失败：备份中未找到 users 表数据段" >&2
fi

# ---------- 3. 知识库文件归档 ----------
echo "→ 归档知识库文件"
if [ -d "${KB_DIR}" ]; then
    tar -czf "${KB_TAR}" -C "$(dirname "${KB_DIR}")" "$(basename "${KB_DIR}")"
    KB_VERIFY="ok"
else
    echo "⚠️  知识库目录不存在，跳过归档：${KB_DIR}" >&2
    KB_TAR=""
    KB_VERIFY="skip(no dir)"
fi

# ---------- 4. 异地复制 ----------
if [ -z "${OFFSITE_TARGET}" ]; then
    OFFSITE="NOT_CONFIGURED"
    echo "⚠️  未配置 OFFSITE_TARGET，本次未做异地备份（请在 /etc/default/rag-backup 或 crontab 中设置）" >&2
elif rsync -a --timeout=180 "${DB_DUMP}" ${KB_TAR:+"${KB_TAR}"} "${OFFSITE_TARGET}"; then
    OFFSITE="ok(${OFFSITE_TARGET})"
    echo "→ 异地复制完成：${OFFSITE_TARGET}"
else
    OFFSITE="FAILED(${OFFSITE_TARGET})"
    echo "❌ 异地复制失败（本地备份仍然有效）" >&2
fi

# ---------- 5. 写台账 ----------
{
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$(date -Iseconds)" "db" "$DB_DUMP" "$(size_of "${DB_DUMP}")" "$(sha256_of "${DB_DUMP}")" "${DB_VERIFY}" "${OFFSITE}"
    if [ -n "${KB_TAR}" ]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$(date -Iseconds)" "kb" "${KB_TAR}" "$(size_of "${KB_TAR}")" "$(sha256_of "${KB_TAR}")" "${KB_VERIFY}" "${OFFSITE}"
    fi
} >> "${MANIFEST}"
echo "→ 台账已写入 ${MANIFEST}"

# ---------- 6. 保留 14 天 ----------
echo "→ 清理超过 ${RETAIN_DAYS} 天的本地备份"
while IFS= read -r old; do
    echo "   删除 ${old}"
    rm -f "${old}"
done < <(find "${DAILY_DIR}" -maxdepth 1 -type f \
    \( -name 'ragdb_[0-9]*.dump' -o -name 'kb_[0-9]*.tar.gz' \) \
    -mtime "+${RETAIN_DAYS}" -print)

echo "=== 备份结束（数据库校验：${DB_VERIFY}）==="
[ "${DB_VERIFY}" = "ok(users)" ] || exit 1