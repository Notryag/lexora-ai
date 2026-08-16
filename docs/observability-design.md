# Lexora Agent 可观测性设计

## 1. 文档定位

本文描述 Lexora 对话运行过程的产品可观测性演进方案，当前只确定契约和实施顺序，不代表功能
已经完成。

目标是让用户在等待回答时能看懂：

- 当前处于什么阶段；
- Supervisor 委派了哪个 Subagent；
- Subagent 正在执行什么可观察动作；
- 调用了什么工具，工具是否成功；
- 页面刷新后仍能查看本次分析过程。

可观测性不等于暴露模型思维链。页面只展示已发生的运行事实、受控摘要和结果计数，不展示模型
隐藏推理、System Prompt、完整工具参数或原始工具结果。

## 2. 设计结论

采用 DeerFlow 的核心模式，但不复制完整实现：

```text
North Runtime callbacks
        |
        v
Lexora RuntimeEventProjector
        |-----------------------> Live stream -> Browser
        |
        v
RunActivityJournal
        |
        v
agent_run_events
        |
        v
Run events API -> reload / history / audit
```

实时流和持久化历史是同一运行事实的两个投影：

- 实时事件命名、Subagent 生命周期和持久化事件优先同步 DeerFlow；
- `agent_run_events` 保存有界活动历史，刷新页面后从 API 恢复；
- Token delta 只实时传输，不逐 Token 落库；
- `agent_runs.status` 仍是 Run 生命周期的权威来源；
- `message.human` 和 `message.ai` 仍是用户对话历史的权威来源。

一次调用的展示身份必须来自真实运行标识：

```text
Subagent: task_id
Tool:     call_id
Model:    call_id（默认仅作诊断，用户层可以折叠为主 Agent 阶段）
```

同一次调用的 started/completed/error 更新同一行；同名工具的两次调用不能因为名称相同而合并。
委派工具与它产生的 Subagent 共用 `task_id`，用户层只显示 Subagent，不重复显示底层 delegate 工具。

已确认本阶段把 NDJSON 切换为 DeerFlow 式 SSE，并接入 North `StreamBridge`、heartbeat、事件 ID、
`Last-Event-ID` 和 gap recovery。

## 3. 与 DeerFlow 的对齐原则

### 3.1 直接同步

以下部分没有 Lexora 特有理由，应直接同步 DeerFlow：

- 持久化事件名：`run.start / run.end / run.error`；
- Subagent 事件名：`subagent.start / subagent.step / subagent.end`；
- 实时 Subagent payload：`task_started / task_running / task_completed / task_failed /
  task_cancelled / task_timed_out`；
- `task_id`、`message_index`、terminal `status` 字段；
- Thread 级严格递增 `seq`；
- `after_seq + task_id + event_types` 的服务端过滤和前向分页；
- live step 与 persisted step 使用同一个纯数据转换函数；
- terminal event 立即 flush，普通 step 批量写入；
- 事件目录由机器可读 JSON Schema 和代码 catalog 共同约束；
- consumer 忽略未知事件、字段和可选 payload。
- 子 Agent 内部的 model/tool 事件显式携带 `task_id`，前端不得通过事件时间或 `caller` 名称猜测父子关系；
- 同名工具的不同 `call_id` 保持为不同调用，只合并同一 `call_id` 的开始和终态。

### 3.2 当前暂定差异

| 差异 | DeerFlow | Lexora 建议 | 理由 |
| --- | --- | --- | --- |
| 结构化扩展位置 | `content + metadata` 可直接保存 JSON | 保留 `content` 文案和版本化 `EventExtensionEnvelope` | Agent Platform 已有稳定扩展契约，消息引用也使用该机制；迁移全部历史事件收益不足 |
| 工具生命周期 | 工具调用意图不是一等事件，官方文档列为 known gap | 新增 `tool.start / tool.end / tool.error` | 用户明确要求看到调用了什么工具、是否成功，仅保存 tool result 不够 |
| Subagent AI step 文本 | 可在 Subtask Card 展示中间 AI 文本 | schema 对齐，但用户层 `text` 只允许受控阶段文案或空值 | 法律咨询包含敏感事实，也不能把自由中间推理当成“思维链”展示 |
| 产品展示 | 通用 Subtask Card | Lexora 的紧凑分析时间线 | 角色少、流程短，且当前工作台不应引入卡片嵌套；数据契约仍保持兼容 |
| 完成后展开状态 | Subtask Card 默认折叠，主处理区保留最近步骤 | 运行中和失败时展开，最终回答完成后自动收起，可手动重开 | 用户先阅读法律答复，同时保留可审计路径 |

这些差异是当前实施选择，不是永久架构承诺。每项都必须保持适配边界和测试，后续继续跟踪 DeerFlow
演进；如果 DeerFlow 补齐一等工具事件、敏感内容投影或兼容的扩展信封，应重新评估并优先收敛。

### 3.3 已确认的传输收敛

DeerFlow 使用 SSE、`StreamBridge`、heartbeat、事件 ID、`Last-Event-ID` 和 gap recovery。Lexora
已经同步为该传输模型，并继续使用 `fetch()` 发送 POST 和消费响应，不受浏览器 `EventSource`
只能 GET 的限制。实现复用 North `StreamBridge`，没有创建第二套 replay 缓冲。

## 4. 当前基础与缺口

### 4.1 已有能力

Lexora 已经具备：

- `agent_runs`；
- `agent_run_events`，并以 Thread 级 `seq` 排序；
- `message.human`、`message.ai` 和 `agent.input` 事件；
- 按 Run 查询事件的仓储方法；
- SSE `metadata / custom / messages / complete / error / end` 对话流；
- 一个产品 Run 对应一次用户请求。
- North RuntimeEvent 到 `agent_run_events` 的安全投影；
- 最新 Run 的有界活动历史 API；
- 前端实时活动聚合和刷新后的最新 Run 恢复；
- 浏览器取得 `run_id` 后保存最后一个完整 SSE 事件 ID，连接中断时通过 GET SSE
  和 `Last-Event-ID` 有界重连，不会重新 POST 或创建第二个 Run；游标过期时从持久化记录恢复。

North 已经具备：

- `RuntimeJournal` callback；
- `model.started / model.completed / model.error`；
- `tool.started / tool.completed / tool.error`；
- `lead_agent`、`subagent:{name}`、`middleware:{name}` caller tag；
- model latency 和 token usage；
- `RuntimeEventSink` 与 `stream_observer` 接口。

### 4.2 主要缺口

1. 当前历史接口只恢复案件最新 Run，尚未在每条助手消息旁按 `run_id` 展示各自历史。
2. RunJournal 第一阶段逐事件提交，尚未增加有界批量写入。
3. 取消或异常终止后的活动收口仍以产品 Run 状态投影，尚未持久化合成的每项取消终态。

## 5. 三层可观测性

### 5.1 用户活动层

默认展示，回答“系统正在做什么”。只包含：

- 案件分析师开始、完成或失败；
- 法律研究员开始、完成或失败；
- 检索案件材料、法规、类案；
- 执行确定性计算；
- 整理最终回答；
- Run 完成、失败或取消。

### 5.2 开发诊断层

默认不在个人用户页面展开，用于调试和评测：

- 每次模型调用的 caller、序号、耗时和 token usage；
- 工具 call ID、父调用 ID、耗时和错误类型；
- 中间件事件；
- 未识别或被过滤的运行事件。

### 5.3 外部追踪层

Langfuse、LangSmith 或 OpenTelemetry 属于并行的运维追踪能力，不从 `agent_run_events` 反推。
通过 `thread_id / run_id / task_id / call_id` 关联即可。个人版第一阶段不引入外部追踪服务。

## 6. 产品事件契约

### 6.1 Envelope

继续使用现有 `AgentRunEvent`，不另建事件表：

```json
{
  "id": "event UUID",
  "thread_id": "thread UUID",
  "run_id": "run UUID",
  "seq": 27,
  "event_type": "subagent.start",
  "category": "subagent",
  "content": "正在梳理案件事实与争议焦点",
  "extension": {
    "kind": "runtime.activity",
    "schema_version": 1,
    "payload": {}
  },
  "created_at": "2026-08-16T12:00:00+08:00"
}
```

数据库列已经能够容纳这些字段。Agent Platform 的 `AgentRunEventCategory` 需要在保留既有枚举值
兼容性的前提下，补充 DeerFlow 使用的 `trace / outputs / subagent / middleware / context /
workspace`；Lexora 新增的一等工具事件继续使用已有 `tool` 分类。

### 6.2 运行关联字段

```text
task_id                 Subagent 委派的稳定 ID，与 DeerFlow 一致
call_id                 model/tool callback 调用 ID
parent_call_id          LangChain 父调用 ID
actor_type              supervisor | subagent | tool | model | middleware
actor_name              case_analyst / legal_researcher / search_legal_authorities ...
caller                   lead_agent | subagent:{name} | middleware:{name}
status                   running | completed | failed | cancelled
phase                    case_understanding | research | retrieval | calculation | synthesis
duration_ms              终态事件可选
safe_detail              经过 allow-list 处理的结构化展示数据
error_code               安全、稳定的错误代码；终态失败时可选
```

前端可以把 `task_id` 和 `call_id` 投影为统一 Activity；持久化协议不额外发明一套替代 DeerFlow
的 ID。`parent_call_id` 用于构建以下层级：

```text
Legal Researcher
    +-- search_legal_authorities
    +-- search_guiding_cases
```

不能用时间顺序或工具名称猜测父子关系。North 必须保存 callback `parent_run_id`，并在 Subagent
调用边界把稳定的 `task_id` 传播到子 Agent 内部的 model/tool 事件。`caller` 仅用于角色标签和
旧事件兼容，不再作为新事件的主要关联键。

### 6.3 第一版事件目录

| Event type | Category | 页面默认展示 | 说明 |
| --- | --- | --- | --- |
| `run.start` | `trace` | 是 | 与 DeerFlow 同名；产品 Run 开始 |
| `subagent.start` | `subagent` | 是 | 与 DeerFlow 同名；委派专家 |
| `subagent.step` | `subagent` | 是 | 与 DeerFlow 同 shape；用户层过滤自由推理文本 |
| `subagent.end` | `subagent` | 是 | 与 DeerFlow 同名；status 区分完成、失败、取消、超时 |
| `tool.start` | `tool` | 是 | Lexora 对 DeerFlow known gap 的增量扩展 |
| `tool.end` | `tool` | 是 | status、耗时和结果计数 |
| `tool.error` | `error` | 是 | 工具失败 |
| `answer.start` | `trace` | 是 | Supervisor 开始生成用户答案 |
| `run.end` | `outputs` | 是 | 图执行结束证据；RunRow 状态仍权威 |
| `run.error` | `error` | 是 | Run 失败 |
| `run.cancelled` | `trace` | 是 | Lexora 产品取消扩展 |
| `llm.start` | `trace` | 否 | 开发诊断扩展 |
| `llm.end` | `trace` | 否 | 延迟和 usage，不保存完整输出 |
| `llm.error` | `trace` | 否 | 与 DeerFlow 同名；开发诊断 |

现有 `message.human`、`message.ai` 和 `agent.input` 保持不变。事件名一旦发布即视为 API 契约；
后续只能新增事件或可选字段，重命名需要版本迁移或双写。

## 7. 安全展示规则

### 7.1 可以展示

- Subagent 的产品名称和状态；
- 工具的产品名称和状态；
- 经过清洗的检索词预览，最多 120 字；
- 命中候选数量、最终引用数量、提取事实数量；
- 耗时；
- 稳定错误码和面向用户的错误说明。

### 7.2 禁止展示或落入用户事件

- System Prompt、Skill 全文和模型配置；
- 模型隐藏 reasoning 或完整中间回答；
- 完整 Case Analyst / Researcher 结构化结果；
- 完整工具参数、材料正文、法规 Chunk 和工具原始输出；
- API key、Authorization header、数据库地址；
- Provider 原始异常消息和堆栈。

North 原始 `model.completed.content` 和 `tool.completed.content` 不能直接写入产品事件。Lexora 的
`RuntimeEventProjector` 必须按 actor/tool allow-list 生成摘要。

示例：

| Runtime actor | 用户文案 | `safe_detail` |
| --- | --- | --- |
| `case_analyst` | 正在梳理案件事实与争议焦点 | 完成后仅记录事实、争点、回答目标数量 |
| `legal_researcher` | 正在检索并核验法律依据 | 完成后仅记录 finding/reference 数量 |
| `search_legal_authorities` | 正在检索法规 | query preview、命中数量 |
| `search_guiding_cases` | 正在检索类案 | query preview、命中数量 |
| `search_case_materials` | 正在查阅案件材料 | query preview、命中数量 |
| `calculate_employment_termination_compensation` | 正在计算补偿金额 | 不重复保存完整输入，只记录计算已完成 |

这里的名称映射是展示注册表，不参与 Agent 路由，也不根据法律关键词判断案由。

## 8. North 与 Lexora 的职责边界

### 8.1 North 负责

1. 统一产出 product-neutral model/tool/subagent 生命周期事件。
2. 所有 model 和 tool 事件携带 `call_id`、`parent_call_id`、`caller`。
3. `delegate_{subagent}` 边界产出明确的 Subagent start/complete/error 事件，而不要求产品解析模型文本。
4. 传播 timeout/cancellation 和耗时。
5. 保证 callback sink 失败不会泄露模型内容或破坏 Agent 语义。

North 不负责中文展示文案、法律阶段名、事件持久化或用户权限。

### 8.2 Lexora 负责

1. 将 North `RuntimeEvent` 投影为 Lexora `runtime.activity` v1。
2. 对参数、结果和异常做 allow-list 摘要与脱敏。
3. 将活动写入 `agent_run_events` 并推送实时连接。
4. 维护 Run、Case、Thread 的权限边界。
5. 将技术 actor 映射为案件分析、法律研究、材料检索、计算和回答生成等产品阶段。
6. 决定哪些事件面向用户，哪些只进入开发诊断 API。

### 8.3 Agent Platform 负责

1. 扩展通用 `AgentRunEventCategory.subagent`。
2. 保持 `EventExtensionEnvelope` 的版本化扩展机制。
3. 如多个应用需要，沉淀事件目录校验和通用分页契约。

不得把 Lexora 的 Subagent 名称、法律阶段或脱敏规则放入 Agent Platform。

## 9. 写入与实时传输

### 9.1 RunJournal

Lexora `RunJournal` 接收 North `RuntimeJournal` 投影后的事件：

```text
North callback
    -> RuntimeEventProjector
    -> RunJournal
        +-> StreamBridge
        +-> agent_run_events
```

建议语义：

- Subagent 使用稳定 `task_id`，model/tool 使用 callback `call_id`；
- live 事件携带稳定事件 ID，持久化时复用该 ID；
- 第一阶段按事件持久化，先稳定事件语义和失败隔离；批量写入作为后续性能优化；
- 事件先完成安全投影，再写入 `agent_run_events` 并发送到 StreamBridge；
- Subagent/tool/Run 终态事件使用稳定事件 ID；
- `complete` 事件在最终消息持久化后发送；
- 写入失败记录服务日志，但不能把成功的法律分析改成失败；
- 队列和 payload 都必须有大小上限。

后续性能优化可增加 `append_batch`，一次锁定 Thread 并分配连续 `seq`，避免每条事件执行一次
`max(seq)` 和行锁。事件量第一版应保持在每 Run 数十条，不保存 token delta。`RunJournal`
不是独立数据表：它写入现有 `agent_run_events`；`agent_runs` 仍只维护 Run 生命周期。

### 9.2 当前 SSE 协议

现有 POST stream 端点使用 `text/event-stream`，使用带类型和 ID 的帧：

```text
event: metadata
data: {"run_id":"...","thread_id":"..."}
id: 1

event: messages
data: {"delta":"..."}
id: 2

event: custom
data: {"type":"task_started","task_id":"...","subagent_type":"legal_researcher"}
id: 3

event: end
data: null
id: 4
```

工具生命周期作为 Lexora/North 的 additive custom event：

```json
{
  "type": "tool_started",
  "call_id": "tool call UUID",
  "parent_call_id": "subagent call UUID",
  "caller": "subagent:legal_researcher",
  "tool_name": "search_legal_authorities",
  "safe_detail": {"query_preview": "分居是否自动解除婚姻关系"}
}
```

SSE 行为同步 DeerFlow：15 秒 heartbeat、事件 ID、`Last-Event-ID`、有界 replay 和显式 `gap`。
第一阶段仍可使用内存 `StreamBridge`；水平扩展时再切 Redis 实现，协议不变。客户端遇到 `gap`
后读取 RunRow、消息和持久化事件恢复，不能从最早可用帧静默拼出不完整历史。

如果决定暂不切换，保留 NDJSON 时也必须使用相同 `task_*` payload 和持久化事件目录，但不具备
heartbeat、事件游标和流内 replay 保证。

## 10. 读取 API

增加：

```text
GET /api/v1/cases/{case_id}/runs/{run_id}/events
    ?after_seq=0
    &event_types=subagent.start,subagent.step,subagent.end,tool.start,tool.end
    &limit=200
```

规则：

- 必须同时校验 case、thread、run 的 owner；
- `after_seq` 前向分页，按 `seq ASC` 返回；
- 默认只返回用户活动层；
- 开发诊断层使用单独权限或显式 `view=diagnostic`，不混入普通页面；
- 响应忽略未知扩展字段；
- 单次 `limit` 设上限，避免将长 Run 全量加载到首屏。

当前第一版通过 `GET /cases/{case_id}/run/activities` 读取最新 Run，最多返回最近 256 条事件，
并只接受 `lexora.runtime.activity` v1 扩展。普通消息、工具参数、模型输出和未知扩展字段不会进入
响应；受控状态文案根据事件类型重新生成，不信任持久化的任意正文。

后续历史消息响应需要继续保留 `run_id`，页面才能把每条助手消息与对应活动关联。届时历史活动在
用户展开“分析过程”时按需读取，不随消息列表全部预加载。

## 11. 前端体验

### 11.1 当前运行

在正在生成的助手消息中显示一个紧凑、无嵌套卡片的折叠时间线：

```text
正在分析
  [完成] 案件分析师：已梳理 3 项事实、2 个争点
  [进行中] 法律研究员：正在核验法律依据
      [完成] 检索法规：找到 5 条候选依据
      [进行中] 检索类案
  [等待] 整理回答
```

约束：

- 只显示实际发生的步骤，不预画固定流程；
- 并行 Subagent 并列显示，不伪造成串行；
- 工具显示在所属 Subagent 下，Supervisor 直接工具显示为顶层步骤；
- 回答开始逐字显示后，活动区仍可折叠查看；
- 失败步骤保留，Run 仍可能由 Supervisor 降级完成；
- Run 结束后默认折叠为“分析过程 · N 个步骤 · X 秒”。

当前实现使用 DeerFlow 的短 `description` 与任务生命周期分离方式。运行中显示动作句，例如
“主 Agent 正在判断处理路径”“正在调用案件分析 Agent”“正在检索法规依据”；展开后显示固定的
安全阶段说明和终态耗时。模型生成的短 description 最多保留 120 字，不保存或展示完整任务参数。
Run 成功后活动区自动收起，历史恢复默认收起；失败时保持展开，避免隐藏错误步骤。

### 11.2 历史恢复

- `complete` 前端保留本轮活动摘要；
- 第一版刷新后调用最新 Run activities API；
- 后续按消息 `run_id` 展开各自的历史；
- reducer 以 live/persisted event ID 去重，以 `task_id` 或 `call_id` 合并状态；
- 收到 terminal 事件但没有 start 时也必须创建活动，兼容丢帧或晚订阅；
- Run 取消时将仍为 running 的活动投影为 cancelled。

### 11.3 不显示“思考过程”

UI 名称使用“分析过程”或“执行记录”，不用“思维链”。`subagent.step` 的 `kind=ai` 文本在用户层
只能来自固定阶段投影；模型自由生成的中间推理文本不得直接展示。

## 12. 实施阶段

### Phase 1：North 关联契约

1. 为 model/tool 事件补充 `caller` 和 `parent_call_id`。
2. 同步 DeerFlow 的 `task_*` live payload、`subagent.*` persistence shape 和稳定 `task_id`。
3. 增加 timeout、error、parallel delegation 的单元测试。
4. 不在 North 中加入 Lexora 展示文案或持久化代码。

验收：单次复杂咨询的事件可以重建 `Supervisor -> Subagent -> Tool` 层级，不依赖事件时间猜测。

### Phase 2：Lexora 事件投影与持久化

1. 增加 `RuntimeEventProjector` 和展示注册表。
2. 增加 `RunActivityJournal` 与 `append_batch`。
3. 将 North `event_sink` 接入 `NorthCaseAnalysisGateway`。
4. 按确认结果接入 SSE，或暂时在 NDJSON 上传输相同 custom payload。
5. 增加 Run events API。
6. 保证 `complete` 前 flush，失败与取消写终态。

验收：实时活动与刷新后活动一致；Run 仍只有一条用户消息和一条助手消息。

### Phase 3：前端活动时间线

1. 增加 activity 类型、reducer 和流解析。
2. 在助手消息位置展示折叠时间线。
3. 支持并行层级、工具状态、失败和取消。
4. 历史展开时按 Run 拉取活动。
5. 使用 Playwright 验证桌面和移动端无重叠、长名称可换行。

验收：用户能看到调用了哪个 Subagent、哪个工具和当前状态，但看不到 Prompt、原始工具输出和
隐藏推理。

### Phase 4：指标与外部追踪

1. 将 model usage 聚合写入 `agent_runs` 的专用列或版本化 usage 扩展，不从事件历史临时求和。
2. 增加每 Run 的 TTFT、总耗时、Subagent 耗时和工具失败率。
3. 需要跨环境分析时再接入 OpenTelemetry/Langfuse，并通过 ID 关联。

## 13. 测试与验收矩阵

| 场景 | 必须验证 |
| --- | --- |
| `hi` | 无 Subagent、无工具活动；只有生成回答阶段 |
| 具体案情 | Case Analyst 可见且画像更新 |
| 法律检索 | Legal Researcher 及其法规工具形成父子层级 |
| 并行委派 | 两个 Subagent 并列，不互相覆盖 |
| 工具失败后降级 | 失败步骤可见，最终 Run 可成功 |
| Subagent timeout | Subagent 标记失败/超时，活动不永久 running |
| 用户取消 | Run 与活动均收敛为 cancelled |
| 页面刷新 | 历史事件与实时显示一致，无重复步骤 |
| 安全快照 | 事件中没有 Prompt、密钥、完整材料和原始工具输出 |
| 多轮对话 | 每条助手消息只关联自己的 run_id |

## 14. 明确不做

第一版不做：

- 暴露模型思维链；
- 保存每个 Token；
- 把所有 LangGraph state 快照写库；
- 为可观测性单独引入 Kafka、Redis 或消息队列；
- 在前端根据工具名猜测 Subagent 归属；
- 把 Langfuse/LangSmith 当作用户页面的数据源；
- 为了展示步骤将动态 Supervisor 改回固定 Workflow。

## 15. 已确认实施顺序

先完成 North 的关联字段和 Subagent 生命周期事件，再实现 Lexora projector/journal，最后开发页面。
如果先做前端，只能根据 `delegate_*` 名称和时间顺序猜测层级，后续一定会重写事件状态模型。

已确认本阶段同步接入 DeerFlow 式 SSE 和 North `StreamBridge`。当前四项差异只作为可替换适配
记录，后续不保证保留；每次 DeerFlow 相关升级都应重新审视是否能够删除差异。

## 16. 当前实施切片

本轮按以下顺序落地：

1. North 为子 Agent 内部 model/tool 事件补充 `task_id`，并用测试固定关联关系。
2. Lexora `RunJournal` 只投影有界的任务说明、检索词预览、调用状态和耗时。
3. 前端以 `task_id/call_id` 建立每次调用的稳定 Activity；delegate 工具与 Subagent 合并，其他
   同名工具调用保持独立。
4. 用户层不展示子 Agent 的原始 AI step 文本；Subagent 行展示 Supervisor 给出的短任务说明，
   子行展示实际工具及安全检索摘要。
5. 主 Agent 只展示可证明的通用阶段：首次模型调用表示理解请求和选择能力，工具返回后的模型调用
   表示核对结果并组织答复；不再为子 Agent 猜测“规划/综合”等阶段。
6. 运行中和失败状态保持展开；最终回答完成后自动收起，用户可重新展开。

Dayboard 使用同一 North 关联契约，但保留日程、任务操作的产品摘要；两个应用不共享中文映射或
React 组件。
