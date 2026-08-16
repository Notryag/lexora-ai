# 法析 Lexora

**AI 法律案例分析助手。**

Lexora 通过连续对话理解用户描述的情况，并将案件背景、当事人主张、证据材料和待分析
问题整理成可检查的案件分析。用户不需要先填写专业表单，系统会沿用已有信息并针对关键
缺口继续追问。当前版本基于用户对话、提交材料、经人工审核的官方法规和类案
工作，强调区分事实、主张、证据和推断，不虚构法条、案例或证据。

> 当前项目处于首个纵向切片阶段，输出用于案件研究和材料整理，不构成法律意见，也不能
> 替代执业律师对事实、证据和适用法律的审查。

## 当前能力

- 创建、修改和持久化个人案件工作区；
- 在案件档案中确认并编辑案件类型、当事人、诉求、关键事实、争议焦点和信息缺口；
- 上传 PDF、DOCX、TXT、Markdown，或直接录入案件材料；
- 以 Thread 级事件日志持久化连续对话、引用卡片和 Run 状态；
- 使用 North 官方 PostgreSQL Checkpointer 恢复多轮 Agent 上下文；
- 展示当前分析 Run 状态，并允许用户取消仍在排队或运行中的分析；
- 使用 North Agent Runtime 调用 OpenAI 兼容模型；
- 由 Supervisor 编排受限 Case Analyst 和 Legal Researcher；法规与类案原始检索工具只分配给
  Researcher，子 Agent 不创建额外产品 Run 或用户消息；
- 使用仓库内独立 package `packages/rag-core` 对材料进行确定性切分，并按当前问题执行
  词法/语义混合检索；
- 生成带 `[M1:C1]` Chunk 引用的 Markdown 分析；
- 按法条编号、词法和可选向量检索人工核验的官方法规，并保存可跳转原文的
  `[L...:C...]` 引用；
- 检索已审核的最高法指导性案例、入库参考案例和典型案例，并单独保存可跳转原文的
  `[C...:S...]` 类案引用；
- 对外部案例 JSONL 进行有硬预算的 factor 发现 dry-run 规划，不调用模型或处理全量语料；
- 通过受限 HTTP Range 仅获取登记的数据集成员，拒绝回退为完整归档下载；
- 通过持久化账本对离线 factor 发现执行 100M 输入与输出 Token 累计上限；
- 对 CAIL2022-LCR、LeCaRDv2 和 STARD 执行有界规范化与来源 ID、案号、内容哈希去重 dry-run；
- 将三套研究数据的 query、相关性标签和候选 ID 规范化为可审计的检索评测计划；
- 流式核验 STARD 候选法规覆盖，并为获批后的离线磁盘 BM25 评测提供硬资源门禁；
- 以默认 dry-run、显式限量执行的核心对话评测检查流式文本、引用、案件画像和
  Thread/Run/Event 持久化一致性；
- 明确输出争议焦点、双方论证、证据评价、信息缺口和后续核查事项；
- 对材料数量、单份大小和总上下文设置确定性限制；
- 提供可替换的分析网关，测试不依赖真实模型。

当前检索针对案件中已保存的材料、已审核法规和首批官方类案，案件档案会作为用户确认的
上下文参与对话和检索。配置 Embedding API 后，新材料、法规和案例会
持久化向量并使用词法/语义混合排序；未配置时自动保持词法检索。当前版本以固定个人用户
运行，尚不包含登录权限、大规模裁判文书库、判决预测或自动法律结论。法规由服务端从
`lvyan-lawtext` 快照同步，待审核版本不会进入回答。后续边界见
[架构文档](./docs/architecture.md)和
[产品范围](./docs/product-scope.md)。

法规同步与版本审核见[法规来源同步](./docs/legal-sources.md)，官方类案见
[类案来源与审核](./docs/case-law-sources.md)，factor 数据与费用边界见
[Factor Discovery Data](./docs/factor-discovery-data.md)，核心对话回归方式见
[Core Conversation Evaluation](./docs/conversation-evaluation.md)。本机生产启动方式见
[部署说明](./docs/deployment.md)。

## Web 工作台

`apps/web` 是独立的 Lexora 前端。它沿用 Dayboard 已验证的 Next.js、React、TanStack
Query、OpenAPI 类型生成和语义设计 Token，但不导入 Dayboard 业务组件。

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.build.yml build api web
docker compose up -d --no-build
docker compose ps
```

打开 <http://127.0.0.1:3000>。容器内前端将 `/api` 代理到 API 服务，宿主机无需公开 API
或数据库端口。

## 快速开始

要求 Python 3.11+、`uv` 和 Docker。

```bash
cp .env.example .env
# 在 .env 中填写 OPENAI_API_KEY；Embedding 可单独配置 API Key 和 Base URL
docker compose up -d postgres
uv sync
uv run alembic upgrade head
uv run lexora-api
```

打开 <http://127.0.0.1:8010/docs>，或检查服务：

```bash
curl http://127.0.0.1:8010/api/v1/health
```

创建案件并保存材料：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/cases \
  -H 'Content-Type: application/json' \
  -d '{"title":"买卖合同货款争议","background":"乙方拒绝支付尾款。"}'

# 将返回的案件 id 替换到下列 URL
curl -X POST http://127.0.0.1:8010/api/v1/cases/CASE_ID/materials \
  -H 'Content-Type: application/json' \
  -d '{"title":"买卖合同","kind":"contract","content":"合同约定交货后十日内支付尾款。"}'
```

在案件中开始并继续对话：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/cases/CASE_ID/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"公司突然通知我明天不用上班了，也没有说明补偿。"}'
```

## 开发检查

```bash
uv run --project packages/rag-core ruff check .
uv run --project packages/rag-core pytest -q
uv run ruff check .
uv run pytest -q
```

## 项目结构

```text
src/lexora_ai/
  domain/          案例材料与分析结果
  application/     分析用例与网关契约
  db/              Lexora 数据模型与 Platform 持久化适配器
  infrastructure/  North Runtime 与材料解析适配器
  material_context.py  rag-core 材料切分、词法检索与产品引用投影
  api/             FastAPI 路由和依赖装配
apps/web/           Next.js 法律对话与案件材料工作台
packages/rag-core/  框架无关的切分、检索与排名融合 package
docs/               架构与产品边界
tests/              领域、应用与 API 测试
```
