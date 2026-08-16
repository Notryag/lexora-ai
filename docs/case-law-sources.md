# 类案来源与审核

## 当前范围

Lexora 的首批类案来自最高人民法院官网公开的指导性案例和人民法院案例库入库参考案例。
受控清单保存在 `src/lexora_ai/resources/case_law_sources.json`，目前包含 11 个案例，覆盖合同、
消费者权益、劳动关系和盗窃等主题。入库参考案例与指导性案例使用相同的来源审核、版本管理、
分块、检索和引用链路，但在用户界面中保留各自准确的来源类型与编号。

这不是完整裁判文书库。目标是先验证“官方来源 -> 结构解析 -> 人工审核 -> 检索 -> 对话引用”
的产品闭环，再根据真实使用问题扩充语料。

案例语料同时可以支持离线 factor 发现，但研究数据集不能自动成为用户可见的类案来源。
数据分级、CAIL2018 / LeCaRDv2 用途、人民法院案例库扩展方式、许可审查和 catalog 发布门槛见
[Factor Discovery Data](factor-discovery-data.md)。

## 安全边界

- 连接器只接受并跟随到 `https://*.court.gov.cn`。
- 网页解析结果默认 `pending`，未审核内容不能进入对话。
- 只有 `approved + active` 的案例 Chunk 可被检索。
- 类案用于比较相似点、差异点和裁判思路，不证明本案事实，也不保证相同裁判结果。
- 每条用户可见引用保留最高法原文链接和 `C...:S...` Chunk 编号。

## 运维命令

```bash
uv run lexora-case-law sync
uv run lexora-case-law review <source-id> approve
uv run lexora-case-law embed
```

同步按清单串行执行，默认保证相邻官方页面请求至少间隔 20 秒，命令行不允许设置为低于
10 秒。日常增量同步应通过 `--url` 只提交新增页面，不应反复读取完整清单。连接器不遍历
列表页、不跟随站内链接，也不进行全站抓取。

山东省高级人民法院统一站点及其省、市、区县法院栏目可作为下一批来源，但必须使用独立适配器
解析发布机关、案例标题和正文，并通过单独域名白名单与人工审核后才能进入生产检索。

重复同步相同 URL 和内容会返回 `unchanged`。网页发生变化时会创建新的待审核版本，不会自动
替换已经批准的版本；审核人应先比较来源、案号、标题、发布日期、关键词和各裁判段落。

## 检索评测

评测集位于 `evaluation/case_law_retrieval.jsonl`，每条问题指定预期指导案例和必须存在于官方
正文的证据短语。运行：

```bash
uv run lexora-evaluate-case-law-retrieval \
  --output docs/evaluation-results/case-law-retrieval.json
```

首批 7 个来源共 52 个 Chunk；7 条查询的词法检索 Recall@1/3/5 和 MRR@5 均为 1.0。该结果只
验证当前小语料的检索行为，不是回答正确率、裁判预测能力或大规模语料效果。
