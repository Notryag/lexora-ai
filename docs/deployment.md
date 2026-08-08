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

## 构建上下文

API 镜像通过 Docker BuildKit 的附加上下文安装共享包：

- `../dayboard/packages/agent-platform`
- `../rag-core`

它们仍是独立包和唯一源码，不复制进 Lexora。构建服务器需要 Docker Compose 2.17 以上。
`../lvyan-lawtext` 以只读卷挂载到 API 容器，仅供法规同步命令使用。

## 首次部署

```bash
cd /home/zx/lexora-ai
docker compose config --quiet
docker compose build api web
docker compose up -d
docker compose ps
```

API 容器启动时自动执行 `alembic upgrade head`。不要再额外启动宿主机 FastAPI 或 Next.js
进程。Compose 使用 `restart: unless-stopped` 在 Docker 或服务器重启后恢复服务。

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
docker compose build api web
docker compose up -d --no-build api web
docker compose ps
```

只更新单个服务时可以缩小范围：

```bash
docker compose build web
docker compose up -d --no-build --no-deps web
```

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
