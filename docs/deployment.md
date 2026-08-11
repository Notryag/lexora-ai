# Docker 部署

Lexora 在当前服务器上使用 Docker Compose 管理 PostgreSQL、API 和 Web：

```text
future HTTPS reverse proxy
  -> 127.0.0.1:3000 -> Web
  -> 127.0.0.1:8011 -> API

Lexora Docker Compose
  -> Web、API、PostgreSQL
```

宿主机端口只绑定 `127.0.0.1`。PostgreSQL 不对公网开放；在登录鉴权完成前，不配置公网
Nginx 入口。

## 镜像构建

API 镜像通过 Docker BuildKit 的附加上下文安装共享包：

- `../dayboard/packages/agent-platform`
- `../rag-core`

它们仍是独立包和唯一源码，不复制进 Lexora。构建机需要 Docker Compose 2.17 以上。
生产服务器不构建镜像。开发机或 CI 使用 `docker-compose.build.yml` 构建，将 API 和 Web
镜像推送到镜像仓库；生产服务器使用 `docker-compose.prod.yml` 拉取指定版本。

发布镜像应使用 Git commit SHA 标签并在镜像仓库启用标签不可变策略，条件允许时生产部署
直接固定到镜像 digest。不要发布或部署浮动的 `latest` 标签。

构建机示例：

```bash
export LEXORA_API_IMAGE=registry.example.com/lexora-api:0123456789abcdef
export LEXORA_WEB_IMAGE=registry.example.com/lexora-web:0123456789abcdef
docker compose -f docker-compose.yml -f docker-compose.build.yml build api web
docker compose -f docker-compose.yml -f docker-compose.build.yml push api web
```

`../lvyan-lawtext` 以只读卷挂载到 API 容器，仅供法规同步命令使用，不进入镜像。

## 首次部署

```bash
cd /home/zx/lexora-ai
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
export LEXORA_API_IMAGE=registry.example.com/lexora-api:0123456789abcdef
export LEXORA_WEB_IMAGE=registry.example.com/lexora-web:0123456789abcdef
docker compose config --quiet
docker compose pull api web
docker compose up -d --no-build
docker compose ps
```

`docker-compose.prod.yml` 要求显式设置两个镜像变量；缺失时 Compose 会直接报错，不会回退
到本地镜像。API 容器启动时自动执行 `alembic upgrade head`。不要再额外启动宿主机 FastAPI
或 Next.js 进程。Compose 使用 `restart: unless-stopped` 在 Docker 或服务器重启后恢复服务。

首次对话请求会初始化 North 官方 PostgreSQL Checkpointer。`checkpoints`、
`checkpoint_blobs`、`checkpoint_writes` 和 `checkpoint_migrations` 由 North/LangGraph 管理，
Lexora Alembic 只管理 Thread、Run、事件和法律业务表。应用 Run 与 checkpoint 共用数据库，
但职责和迁移所有权相互独立。

## 资源隔离

Compose 默认给三个服务设置硬内存、交换区和 PID 上限：

| 服务 | 内存上限 | `memory + swap` 上限 | PID 上限 |
|---|---:|---:|---:|
| API | 768 MiB | 768 MiB | 256 |
| PostgreSQL | 512 MiB | 512 MiB | 128 |
| Web | 256 MiB | 256 MiB | 128 |

`memory + swap` 与内存上限相等，表示容器不能继续占用宿主机交换区。这样应用发生内存回归
时，故障会被限制在对应容器，不会再次把整台主机拖入换页风暴。限制是最后一道隔离措施，
不能代替有界查询；2026-08-11 事故的根因修复仍是数据库侧 Top-K 和受限查询并发。

如确需调整，应先按宿主机容量核算三个容器总额和操作系统余量，再通过部署环境变量覆盖：

```bash
export LEXORA_API_MEMORY_LIMIT=768m
export LEXORA_API_MEMORY_SWAP_LIMIT=768m
export LEXORA_POSTGRES_MEMORY_LIMIT=512m
export LEXORA_POSTGRES_MEMORY_SWAP_LIMIT=512m
export LEXORA_WEB_MEMORY_LIMIT=256m
export LEXORA_WEB_MEMORY_SWAP_LIMIT=256m
docker compose up -d --force-recreate
```

部署后验证实际生效值；结果单位为字节，且每个服务的 `MemorySwap` 应等于 `Memory`：

```bash
docker inspect lexora-ai-api-1 lexora-ai-postgres-1 lexora-ai-web-1 \
  --format '{{.Name}} memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} pids={{.HostConfig.PidsLimit}}'
docker stats --no-stream
```

## 验证

```bash
curl -fsS http://127.0.0.1:8011/api/v1/health
curl -fsS http://127.0.0.1:3000/api/v1/health
docker compose ps
```

API、Web 和 PostgreSQL 都应显示 `healthy`。生产前端当前只能从服务器本机访问
<http://127.0.0.1:3000>。

## 更新

```bash
export LEXORA_API_IMAGE=registry.example.com/lexora-api:fedcba9876543210
export LEXORA_WEB_IMAGE=registry.example.com/lexora-web:fedcba9876543210
docker compose config --quiet
docker compose pull api web
docker compose up -d --no-build api web
docker compose ps
```

更新单个服务时只修改对应镜像变量，并缩小拉取和重建范围：

```bash
export LEXORA_WEB_IMAGE=registry.example.com/lexora-web:fedcba9876543210
docker compose pull web
docker compose up -d --no-build --no-deps web
```

同一生产环境的部署任务必须串行执行。部署脚本应通过 `flock` 或 CI concurrency 控制避免
多个 `compose pull/up` 同时运行。生产服务器禁止执行 `docker compose build` 或
`docker compose up --build`。

## 日志

```bash
docker compose logs --tail=100 api web
docker compose logs -f api
```

不要通过打印完整 `.env` 排查配置。模型和 Embedding 凭据只通过根目录 `.env` 注入运行时
容器，不进入镜像构建上下文。

## 数据安全

PostgreSQL 数据保存在 `lexora-ai_lexora-postgres-data` 命名卷。部署前的校验备份保存在
`storage/backups/`，该目录不进入 Git。禁止执行 `docker compose down -v` 或删除该命名卷。
普通停止和恢复使用：

```bash
docker compose stop
docker compose start
```
