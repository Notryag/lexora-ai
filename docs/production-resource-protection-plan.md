# 生产服务器资源保护实施计划

## 1. 文档目的

本文用于将镜像构建移出当前生产服务器，并为同机运行的全部服务建立可验证的资源边界。
这是实施任务单，不是要求一次性修改所有系统配置的最终架构。

执行者必须分阶段实施，每个阶段独立验证、独立提交。不要根据本文直接重启全部服务。

## 2. 当前环境

截至 2026-08-16，服务器资源与运行状态为：

- 2 vCPU；
- 3.3 GiB 物理内存；
- 2 GiB Swap，`vm.swappiness=10`；
- 根磁盘 59 GiB，已使用约 88%；
- cgroup v2 与 Docker systemd cgroup driver 已启用；
- 同时运行 Lexora、Dayboard、Sub2API、Debug Relay 及共享 PostgreSQL/Redis，共 12 个容器；
- SSH 的 `OOMScoreAdjust=-1000`，`dockerd=-500`，`containerd=-999`；
- `systemd-oomd` 未安装；
- Docker Build Cache 约 2.58 GiB 可回收，但清理不是本任务的默认授权。

Lexora 已配置运行时限制：

| 服务 | Memory | Memory + Swap | PIDs |
|---|---:|---:|---:|
| API | 768 MiB | 768 MiB | 256 |
| PostgreSQL | 512 MiB | 512 MiB | 128 |
| Web | 256 MiB | 256 MiB | 128 |

以下运行容器当前没有 Docker 内存、Swap 或 PID 上限：

- `dayboard-api-1`、`dayboard-worker-1`、`dayboard-web-1`；
- `platform-postgres`、`platform-redis`；
- `sub2api`、`sub2api-postgres`、`sub2api-redis`；
- `debug-relay-api-1`。

相关 Compose 文件：

```text
/home/zx/lexora-ai/docker-compose.yml
/home/zx/dayboard/docker-compose.yml
/home/zx/dayboard/docker-compose.platform.yml
/home/zx/platform-infra/docker-compose.yml
/opt/sub2api/docker-compose.yml
/home/zx/debug-relay/docker-compose.yml
```

## 3. 事故背景

2026-08-16 在生产服务器执行 Docker Web 镜像构建。Next.js/Turbopack 和 BuildKit 的构建
进程不受 Compose 中 Web 运行容器的 `mem_limit` 约束。服务器随后失去响应，SSH 无法连接，
最终由用户手动重启。

现有证据能够确认资源争用和人工重启，不能确认内核 OOM、kernel panic 或云平台自动恢复。
不要在事故记录中写成“服务器自动重启”或“已确认 OOM”。

此前的检索内存事故见
[2026-08-11 Full-Corpus Retrieval Memory Thrashing](./incident-2026-08-11-memory-thrashing.md)。
两次事故触发源不同，但都说明这台 3.3 GiB 主机不能承受无边界工作负载。

## 4. 目标

1. 生产服务器不再构建 API 或 Web 镜像。
2. GitHub Actions 构建不可变镜像并推送至 GHCR。
3. 生产部署只拉取指定 commit SHA 或 digest 的镜像。
4. 所有运行容器都有内存、Memory + Swap 和 PID 上限。
5. 为操作系统、SSH、Docker daemon 和 Nginx 保留可用内存。
6. 单个应用失控时应由该应用失败，而不是宿主机失联。
7. 数据库卷、案件数据、Checkpoint 和其他项目数据不因部署改造被删除。

## 5. 强制安全边界

实施期间禁止：

- 在当前服务器执行 `docker build`、`docker compose build` 或 `docker compose up --build`；
- 执行 `docker compose down -v`、删除命名卷或重建数据库目录；
- 为验证限制而在生产机运行压力测试、并发模型请求或内存填充程序；
- 未审计镜像和 Build Cache 引用关系前执行 `docker system prune`；
- 直接在 `system.slice` 或根 slice 启用 `ManagedOOMMemoryPressure=kill`；
- 一次性重建或重启所有 Compose 项目；
- 先增加 Swap 来掩盖无边界内存使用；
- 把密钥写入 GitHub workflow、镜像、Compose 或日志。

每次变更前先执行只读检查，准确解析目标 Compose 项目和容器。生产部署任务必须串行。

## 6. Phase 1：建立外部镜像构建流水线

在 Lexora 仓库新增 GitHub Actions workflow：

1. 由 `workflow_dispatch` 启动；条件稳定后再考虑 main 分支自动发布。
2. 分别构建 `apps/api/Dockerfile` 和 `apps/web/Dockerfile`。
3. 推送到：

```text
ghcr.io/notryag/lexora-api:<full-commit-sha>
ghcr.io/notryag/lexora-web:<full-commit-sha>
```

4. 使用 GitHub 提供的短期 token 登录 GHCR，不创建长期明文凭据。
5. workflow 设置 concurrency，禁止同一环境多个发布并行运行。
6. 镜像标签必须使用完整 commit SHA；不要部署 `latest`。
7. 构建结束后输出两个镜像 digest，供生产部署固定。
8. API 构建必须继续使用锁文件固定的 North、Dayboard Agent Platform 和仓库内 `rag-core`。

为生产部署增加一个默认 dry-run 的脚本。脚本应：

- 要求显式传入 API/Web 镜像 SHA 或 digest；
- 使用 `flock` 防止并行部署；
- 先执行 `docker compose config --quiet`；
- 只执行 `docker compose pull api web`；
- 只执行 `docker compose up -d --no-build api web`；
- 检查三个容器健康状态和公网 `/api/v1/health`；
- 失败时输出回滚到前一组 digest 的命令，不删除数据卷。

### Phase 1 验收

- GitHub Actions 能从干净环境构建两个镜像；
- 镜像可由服务器拉取；
- 镜像标签与应用 commit 一致；
- 部署日志中不存在任何本机构建步骤；
- 使用新镜像更新 Web 时，PostgreSQL 不重启；
- 回滚到上一镜像版本经过一次实际验证。

## 7. Phase 2：盘点并限制全部运行服务

不要直接复制 Lexora 的限额到其他项目。先记录每个容器的：

- 空闲 RSS；
- 正常请求下的峰值 RSS；
- 进程数；
- 是否包含 PostgreSQL、Redis 或后台 Worker；
- 重启和 OOM 后的数据一致性要求。

然后逐个 Compose 项目增加可由环境变量覆盖的：

```yaml
mem_limit: ${SERVICE_MEMORY_LIMIT:-<measured-limit>}
memswap_limit: ${SERVICE_MEMORY_SWAP_LIMIT:-<same-as-memory-limit>}
pids_limit: ${SERVICE_PIDS_LIMIT:-<measured-limit>}
```

约束：

- `memswap_limit` 默认与 `mem_limit` 相等，容器不能消耗宿主机 Swap；
- 限额必须覆盖已测峰值和合理余量，不能仅按空闲 RSS 设置；
- PostgreSQL 和 Worker 分别核算，不能使用同一个随意值；
- 总体预算必须为宿主机、SSH、Docker daemon、Nginx 和文件缓存保留至少 700-800 MiB；
- 如果所有必要服务的保守预算无法放入 3.3 GiB，停止调参并提出升级到至少 8 GiB 的容量方案；
- 每次只更新一个 Compose 项目，确认健康后再处理下一个。

推荐顺序：Debug Relay、Dayboard Web/API/Worker、共享 Redis/PostgreSQL、Sub2API。Lexora 已有
限制，只需复核，不要无依据降低。

### Phase 2 验收

以下检查不得再出现 `memory=0 swap=0` 或空 PID 上限：

```bash
docker inspect CONTAINER_NAMES \
  --format '{{.Name}} memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} pids={{.HostConfig.PidsLimit}}'
```

每个项目还必须满足：

- 健康检查通过；
- 正常请求不出现 OOMKilled；
- 数据库没有执行破坏性初始化；
- `docker stats --no-stream` 显示正常工作集显著低于硬上限；
- 宿主机在正常并发下保持至少约 700 MiB `MemAvailable`，Swap 不持续增长。

## 8. Phase 3：提前终止策略

只有完成 Phase 1 和 Phase 2 后，才评估 `systemd-oomd`。当前系统支持 cgroup v2，但尚未安装
该组件。

实施前应先提交独立设计，明确：

- 监控哪个 slice；
- 哪些服务使用 `ManagedOOMPreference=avoid`；
- 触发阈值和持续时间；
- 被杀进程或 cgroup 的恢复方式；
- 如何确认不会优先终止 SSH、Docker daemon 或数据库；
- 如何回滚配置并停用服务。

不要直接监控整个 `system.slice` 并启用 kill。Docker systemd cgroup driver 创建的容器 scope
与 `docker.service` 的层级需要先实测，不能假设限制 Docker CLI 就会限制 BuildKit。

由于生产机禁止构建，不应为了允许本机构建而设计 OOM 策略。`systemd-oomd` 仅作为应用回归或
多服务同时异常时的最后保护。

### Phase 3 验收

- 使用非生产环境或严格受限的测试 cgroup 验证策略；
- 触发时只终止预期的低优先级工作负载；
- SSH、Docker daemon 和数据库保持可用；
- 生产机不运行故意耗尽内存的测试；
- 运维文档包含告警、恢复和回滚步骤。

## 9. Swap 与磁盘

当前 2 GiB Swap 保持不变。更多 Swap 不能提供隔离，只可能延长换页抖动时间。根磁盘仅剩约
7.3 GiB，增加 Swap 还会压缩 Docker 拉取新镜像和回滚所需空间。

Build Cache 当前约有 2.58 GiB 可回收。清理前必须列出缓存、正在使用的镜像和回滚镜像，获得
用户确认后才能执行精确清理。不要使用无范围的 `docker system prune -a`。

## 10. 最终交付物

执行者应交付：

1. Lexora GitHub Actions/GHCR workflow；
2. 默认 dry-run、带部署锁和健康验证的生产部署脚本；
3. 各 Compose 项目的资源测量记录与限额变更；
4. 更新后的部署和回滚说明；
5. 是否需要 `systemd-oomd` 的独立结论；
6. 每阶段的 commit、验证命令和实际结果；
7. 未完成项和需要用户批准的系统级操作清单。

任何阶段遇到未知 Compose 改动、未提交用户修改或无法证明数据安全时，应停止对应变更并报告，
不要重置或覆盖现有工作区。
