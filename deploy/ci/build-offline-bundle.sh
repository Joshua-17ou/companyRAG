#!/bin/bash
#
# 离线镜像包构建脚本（在构建机上执行，生产机不构建任何镜像）
#
# 产物：
#   dist/company-rag-images-<SHA>.tar       可直接 docker load 的镜像包（含 6 个镜像）
#   dist/company-rag-images-<SHA>.tar.sha256 校验值
#   dist/company-rag-images-<SHA>.digests.txt 各镜像 RepoDigest，便于追溯
#
# 用法：
#   deploy/ci/build-offline-bundle.sh [git-ref]        # 默认 HEAD
#
# 前置：构建机已安装 docker 且能拉取基础镜像；当前仓库已 fetch 到最新 origin/main。
#
set -euo pipefail

REF="${1:-HEAD}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${REPO_DIR}/dist}"

# 基础设施基础镜像（生产环境建议锁定到具体版本，避免 latest 不可重现）
POSTGRES_BASE="${POSTGRES_BASE:-postgres:15-alpine}"
REDIS_BASE="${REDIS_BASE:-redis:7-alpine}"
QDRANT_BASE="${QDRANT_BASE:-qdrant/qdrant:latest}"
MINIO_BASE="${MINIO_BASE:-minio/minio:latest}"

# 前端构建参数（生产必须打开飞书入口，并把 API 前缀固定为同源 /api）
VITE_LARK_ENABLED="${VITE_LARK_ENABLED:-true}"
VITE_API_URL="${VITE_API_URL:-/api}"

SHA="$(git -C "${REPO_DIR}" rev-parse --verify "${REF}^{commit}")"
if ! [[ "${SHA}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "❌ 无法把 ${REF} 解析为提交 SHA" >&2
    exit 1
fi

echo "== 发布 SHA：${SHA} =="

# 规范要求部署来源只能是 main：本 SHA 必须已是 origin/main 的祖先
if git -C "${REPO_DIR}" rev-parse --verify --quiet origin/main >/dev/null; then
    if ! git -C "${REPO_DIR}" merge-base --is-ancestor "${SHA}" origin/main; then
        echo "❌ 该提交不在 origin/main 上，规范要求部署来源只能是 main，已中止。" >&2
        exit 1
    fi
else
    echo "⚠️  本地没有 origin/main 引用，跳过 main 祖先校验（请确保已 fetch）" >&2
fi

mkdir -p "${OUT_DIR}"

IMAGES=(
    "company-rag/app:${SHA}"
    "company-rag/frontend:${SHA}"
    "company-rag/postgres:${SHA}"
    "company-rag/redis:${SHA}"
    "company-rag/qdrant:${SHA}"
    "company-rag/minio:${SHA}"
)

echo "== 1/4 构建后端镜像 =="
docker build -t "company-rag/app:${SHA}" -f "${REPO_DIR}/Dockerfile" "${REPO_DIR}"

echo "== 2/4 构建前端镜像（VITE_LARK_ENABLED=${VITE_LARK_ENABLED} VITE_API_URL=${VITE_API_URL}）=="
docker build \
    -t "company-rag/frontend:${SHA}" \
    -f "${REPO_DIR}/frontend/Dockerfile.prod" \
    --build-arg "VITE_LARK_ENABLED=${VITE_LARK_ENABLED}" \
    --build-arg "VITE_API_URL=${VITE_API_URL}" \
    "${REPO_DIR}/frontend"

echo "== 3/4 拉取并重打基础设施镜像标签 =="
for pair in "postgres:${POSTGRES_BASE}" "redis:${REDIS_BASE}" "qdrant:${QDRANT_BASE}" "minio:${MINIO_BASE}"; do
    name="${pair%%:*}"
    base="${pair#*:}"
    echo "  ${name} <= ${base}"
    case "${base}" in
        *:latest) echo "  ⚠️  ${base} 使用 latest，版本不可重现，建议锁定具体版本" >&2 ;;
    esac
    docker pull "${base}"
    docker tag "${base}" "company-rag/${name}:${SHA}"
done

echo "== 4/4 导出镜像包 =="
BUNDLE="${OUT_DIR}/company-rag-images-${SHA}.tar"
docker save -o "${BUNDLE}" "${IMAGES[@]}"

if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${BUNDLE}" > "${BUNDLE}.sha256"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${BUNDLE}" > "${BUNDLE}.sha256"
else
    echo "⚠️  未找到 sha256sum/shasum，跳过校验值生成" >&2
fi

: > "${OUT_DIR}/company-rag-images-${SHA}.digests.txt"
for img in "${IMAGES[@]}"; do
    digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "${img}" 2>/dev/null || docker image inspect --format '{{.Id}}' "${img}")"
    printf '%s\t%s\n' "${img}" "${digest}" >> "${OUT_DIR}/company-rag-images-${SHA}.digests.txt"
done

echo ""
echo "✅ 构建完成"
echo "   镜像包：${BUNDLE}"
echo "   校验值：${BUNDLE}.sha256"
echo ""
echo "下一步（把镜像包传到生产机后）："
echo "   docker load -i company-rag-images-${SHA}.tar"
echo ""
echo "若要手工核对 shared/.env，本次发布对应："
for key in APP_IMAGE FRONTEND_IMAGE POSTGRES_IMAGE REDIS_IMAGE QDRANT_IMAGE MINIO_IMAGE; do
    lower="$(echo "${key}" | sed 's/_IMAGE//' | tr 'A-Z' 'a-z')"
    echo "   ${key}=company-rag/${lower}:${SHA}"
done