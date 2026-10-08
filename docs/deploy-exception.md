# 部署偏离登记表（company-rag）

依据《广州生产环境部署规范》要求，对无法完全符合条款的实现逐项登记。
每项均需在复审日期前重新评估；解除条件满足后应恢复规范条款并删除本行。

| # | 偏离条款 | 实际做法 | 原因 | 影响 | 解除条件 / 复审日期 |
|---|---------|---------|------|------|------------------|
| 1 | 规范 4.3：各服务须设置 `restart: unless-stopped` | `docker-compose.prod.yml` 的 `migrate`、`db-init` 两个一次性任务设置 `restart: "no"` | 二者是发布流程中由 `post-receive` 以 `docker compose run --rm` 调用的短命任务，任务结束后必须退出并清理容器；若设为 `unless-stopped`，非零退出会被反复重启，掩盖迁移失败并污染发布判定 | 仅限 `profiles: ["init"]` 的一次性任务；两者默认不随 `up -d` 启动，不影响常驻服务（postgres/redis/qdrant/minio/app/frontend 均为 `unless-stopped`） | 无解除条件（属这类任务的正确语义）；每次发布前复核是否仍仅是短命任务。复审日期：2026-11-08 |
| 2 | 规范「密钥文件按 `<SECRETS_GID>`=10001 组授权，容器以非 root 身份读取」 | secrets 文件按 `root:10001` + `chmod 0440` 创建；应用容器内 `app` 进程以 root 运行 | 现有 `Dockerfile` 未设置 `USER`，镜像内 Python/uvicorn 与模型加载流程均按 root 编写；发布窗口内不改动基础镜像以降低风险。`entrypoint_prod.sh` 需要读取 `/run/secrets/*` | root 进程若被攻破，容器内权限为 root（仍受容器命名空间与只读挂载约束）；`/run/secrets/*` 权限已收窄为 0440，非 10001 组进程无法读取 | 改造 `Dockerfile` 增加非 root `USER app`，并核对模型缓存目录 `/opt/company-rag/shared/models` 的属主后解除。复审日期：2026-11-08 |
| 3 | 规范「镜像标签使用 40 位 Git 哈希，保证可重现」 | 六个镜像统一打 `company-rag/<name>:<40位SHA>`；但 `qdrant`、`minio` 的基础镜像当前取 `latest` 后重打标签 | 首次上线时间紧，暂沿用开发环境一致的基础镜像来源 | 同一 SHA 标签在不同构建时间可能对应不同的基础镜像内容，包内 `*.digests.txt` 记录了实际 RepoDigest 作为补偿证据 | 在 `deploy/ci/build-offline-bundle.sh` 中把 `QDRANT_BASE`/`MINIO_BASE` 固定为具体版本号并重建离线包。复审日期：2026-11-08 |