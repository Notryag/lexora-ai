# Docker 部署

Lexora 在当前服务器上使用 Docker Compose 管理 API 和 Web，并使用共享 PostgreSQL：

```text
Nginx (https://lexora.selfapi.art)
  -> 127.0.0.1:3000 -> Web
  -> 127.0.0.1:8011 -> API

Lexora Docker Compose
  -> Web、API

platform-infra Compose
  -> platform-postgres 中的独立 lexora database/user
```

宿主机端口只绑定 `127.0.0.1`，Nginx 提供公网 HTTPS 入口。共享 PostgreSQL 不对公网开放，
API 通过外部 `platform-infra` Docker 网络访问 `platform-postgres`。

## 镜像构建

API 镜像使用两类共享包：

- 仓库内的 `packages/rag-core`；
- 固定到具体 Dayboard commit 的公开 `agent-application-platform` Git 依赖。

`rag-core` 与 Lexora 一起版本化，Agent Platform 仍保持 Dayboard 中的唯一源码。构建不再要求
仓库旁存在 `../rag-core` 或 `../dayboard` 目录，但首次解析 Git 依赖需要访问 GitHub。
生产服务器不构建镜像。[GitHub Actions workflow](../.github/workflows/publish-images.yml)
由 `workflow_dispatch` 手动启动，在 GitHub runner 上构建 API 和 Web，然后使用当前任务的
短期 `GITHUB_TOKEN` 推送到：

```text
ghcr.io/notryag/lexora-api:<full-commit-sha>
ghcr.io/notryag/lexora-web:<full-commit-sha>
```

两个构建任务都会在任务摘要中输出 `repository@sha256:...`，生产部署优先使用 digest。
workflow 使用 concurrency 禁止多个镜像发布任务并行运行，不发布 `latest`。

发布镜像应使用 Git commit SHA 标签并在镜像仓库启用标签不可变策略，条件允许时生产部署
直接固定到镜像 digest。不要发布或部署浮动的 `latest` 标签。

管理员命令行发布示例：

```bash
gh workflow run publish-images.yml --repo Notryag/lexora-ai --ref main
gh run watch --repo Notryag/lexora-ai
```

`../lvyan-lawtext` 以只读卷挂载到 API 容器，仅供法规同步命令使用，不进入镜像。

## 部署与更新

```bash
cd /home/zx/lexora-ai
./scripts/deploy-production.sh \
  --api-image ghcr.io/notryag/lexora-api@sha256:<api-digest> \
  --web-image ghcr.io/notryag/lexora-web@sha256:<web-digest>
```

上面的命令默认是 dry-run，只校验 Compose 和镜像参数，不修改容器。确认后增加 `--execute`
执行部署。脚本使用 `flock` 避免并行部署，只拉取并更新 API/Web；随后检查共享
`platform-postgres`、API、Web 的健康状态以及
<https://lexora.selfapi.art/api/v1/health>。失败时会打印上一组本地镜像的回滚命令，不删除
数据卷。

`docker-compose.prod.yml` 要求显式设置两个镜像变量；缺失时 Compose 会直接报错，不会回退
到本地镜像。API 容器启动时自动执行 `alembic upgrade head`。不要再额外启动宿主机 FastAPI
或 Next.js 进程。Compose 使用 `restart: unless-stopped` 在 Docker 或服务器重启后恢复服务。

首次对话请求会初始化 North 官方 PostgreSQL Checkpointer。`checkpoints`、
`checkpoint_blobs`、`checkpoint_writes` 和 `checkpoint_migrations` 由 North/LangGraph 管理，
Lexora Alembic 只管理 Thread、Run、事件和法律业务表。应用 Run 与 checkpoint 共用数据库，
但职责和迁移所有权相互独立。

### 共享数据库迁移与回滚

2026-08-16 将 Lexora 的独立 PostgreSQL 迁移到 `platform-postgres` 中的独立 `lexora`
database/user。迁移归档保存在 `storage/backups/` 并带 SHA-256 校验文件。迁移验证必须比较
全部 public 表的精确行数、Alembic 版本、North checkpoint 数量、表所有者和 `vector` 扩展。

原 `lexora-ai-postgres-1` 容器和 `lexora-ai_lexora-postgres-data` 卷在观察期内保留。需要回滚
数据库连接时，先停止 API/Web，启动旧数据库容器，再使用旧主机名重建 API/Web：

```bash
docker start lexora-ai-postgres-1
export LEXORA_DATABASE_HOST=postgres
docker compose up -d --no-build api web
```

回滚后的新写入会进入旧库，不能在两个数据库之间来回切换。确认共享库稳定并完成新的平台级
备份前，不删除旧容器或命名卷。

## 资源隔离

Lexora Compose 默认给两个应用服务设置硬内存、交换区和 PID 上限。共享 PostgreSQL 的限额由
`/home/zx/platform-infra/docker-compose.yml` 管理：

| 服务 | 内存上限 | `memory + swap` 上限 | PID 上限 |
|---|---:|---:|---:|
| API | 512 MiB | 512 MiB | 256 |
| Web | 192 MiB | 192 MiB | 128 |

`memory + swap` 与内存上限相等，表示容器不能继续占用宿主机交换区。这样应用发生内存回归
时，故障会被限制在对应容器，不会再次把整台主机拖入换页风暴。限制是最后一道隔离措施，
不能代替有界查询；2026-08-11 事故的根因修复仍是数据库侧 Top-K 和受限查询并发。

如确需调整，应先按宿主机容量核算三个容器总额和操作系统余量，再通过部署环境变量覆盖：

```bash
export LEXORA_API_MEMORY_LIMIT=512m
export LEXORA_API_MEMORY_SWAP_LIMIT=512m
export LEXORA_WEB_MEMORY_LIMIT=192m
export LEXORA_WEB_MEMORY_SWAP_LIMIT=192m
docker compose up -d --force-recreate
```

部署后验证实际生效值；结果单位为字节，且每个服务的 `MemorySwap` 应等于 `Memory`：

```bash
docker inspect lexora-ai-api-1 lexora-ai-web-1 platform-postgres \
  --format '{{.Name}} memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} pids={{.HostConfig.PidsLimit}}'
docker stats --no-stream
```

## 验证

```bash
curl -fsS http://127.0.0.1:8011/api/v1/health
curl -fsS http://127.0.0.1:3000/api/v1/health
docker compose ps
```

API、Web 和共享 PostgreSQL 都应显示 `healthy`。公网健康地址是
<https://lexora.selfapi.art/api/v1/health>。

## 回滚

```bash
./scripts/deploy-production.sh --execute \
  --api-image ghcr.io/notryag/lexora-api@sha256:<previous-api-digest> \
  --web-image ghcr.io/notryag/lexora-web@sha256:<previous-web-digest>
```

保留每次 workflow 摘要中的两个 digest。回滚与更新使用相同脚本，不执行 `compose down`，
不删除 PostgreSQL 卷。生产服务器禁止执行 `docker compose build` 或
`docker compose up --build`。

## 日志

```bash
docker compose logs --tail=100 api web
docker compose logs -f api
```

不要通过打印完整 `.env` 排查配置。模型和 Embedding 凭据只通过根目录 `.env` 注入运行时
容器，不进入镜像构建上下文。

## 数据安全

Lexora 数据保存在共享 `platform-postgres` 的独立 `lexora` database 中，底层卷由
`platform-infra` 管理。迁移前的校验备份和原 `lexora-ai_lexora-postgres-data` 卷继续保留；
禁止删除任一卷。备份保存在 `storage/backups/`，该目录不进入 Git。普通应用停止和恢复使用：

```bash
docker compose stop
docker compose start
```
