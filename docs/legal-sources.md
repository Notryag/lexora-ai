# Lexora 法规来源同步

法规由服务端从本地 `lvyan-lawtext` 快照仓库同步，产品前端不提供法规上传或导入功能。
快照中的 Markdown 来源于国家法律法规数据库，包含标题、制定机关、公布日期、施行日期、
效力状态和官方原文 URL。

默认仓库路径为相对 Lexora 项目根目录的 `../lvyan-lawtext`，可通过
`LEGAL_SOURCE_REPOSITORY_PATH` 修改。

首次使用时在 Lexora 同级目录获取快照：

```bash
git clone https://github.com/gzx5418/lvyan-lawtext.git ../lvyan-lawtext
```

后续先在该目录执行 `git pull --ff-only`，再运行同步命令发现新版本。

## 首批同步

服务端清单位于 `src/lexora_ai/resources/legal_sources.json`。执行：

```bash
uv run lexora-legal-sources sync
```

也可以同步指定法律，或同步快照中的全部现行有效版本：

```bash
uv run lexora-legal-sources sync --title 中华人民共和国劳动合同法
uv run lexora-legal-sources sync --all-current
```

同步按官方 URL 和正文 SHA-256 幂等。相同版本不会重复生成 Chunk；正文变化会作为新版本
进入 `pending` 审核状态。条文切分保留 `编/章/节/条` 层级。同步不会自动废止或覆盖旧版本。

## 审核

待审核版本不参与 RAG。确认标题、制定机关、效力状态、日期、正文和官方链接后执行：

```bash
uv run lexora-legal-sources review SOURCE_ID approve
```

不接受该版本时执行：

```bash
uv run lexora-legal-sources review SOURCE_ID reject
```

只有同时满足 `status=effective`、`review_status=approved` 且具有官方 HTTPS 来源的版本才会
进入对话检索。更新本地快照仓库后重新运行同步命令，即可发现正文版本变化。

配置 Embedding 服务后，可为此前已经批准的现行法规回填或更新向量：

```bash
uv run lexora-legal-sources embed
```

该命令按模型名幂等，只处理缺少当前模型向量的已批准现行版本。每批完成后独立提交，失败后
重新运行会从未完成的 Chunk 继续。

## 数据边界

`lvyan-lawtext` 是可更新快照，不是 Lexora 的领域代码，也不进入 `rag-core`。Lexora 只拥有
快照适配、版本审核、条文切分、Embedding、检索和引用投影。官网结构核验或未来授权数据源
通过新的来源连接器接入，不改变应用层同步契约。

## 检索评测

首批评测集位于 `evaluation/legal_retrieval.jsonl`，每个问题都指定法规、法条和必须存在于
当前快照原文中的证据片段。运行：

```bash
uv run lexora-evaluate-legal-retrieval \
  --repository ../lvyan-lawtext \
  --output docs/evaluation-results/legal-retrieval.json
```

评测直接读取快照，不绕过数据库审核门槛。当前基线覆盖五部法规、1,617 个 Chunk 和 17 个
问题；精确法条、词法检索与倒数排名融合的 Recall@3/5 为 1.0，MRR@5 为 0.8725。使用当前
BGE-M3 向量的数据库混合检索 Recall@3/5 为 1.0，MRR@5 为 0.9412。

2026-08-08 首批五个版本已核对标题、制定机关、公布/施行日期、官方详情链接、条文数量和
评测证据后批准进入检索。后续快照正文发生变化时仍会生成新的 `pending` 版本，不会继承
本次批准状态。
