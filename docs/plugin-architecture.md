# Lexora 插件与能力模型

## 文档状态

本文记录 Lexora 与 North 的插件化架构及当前迁移状态。North 已完成最小插件运行时、Lexora/Dayboard 组合根和按委派懒创建子 Agent；标题能力当前仍由 Lexora Plugin 安装的 North Middleware 执行，完整异步 Title Service 属于后续切片。

本文参考 DeepSeek Harness 的官方架构，尤其是 Cordis 插件、能力 seam、Session Title Service 和 Subagent Runtime 的设计，但不直接复制其 TypeScript/Cordis 实现。

参考：

- [DeepSeek Harness 架构](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/architecture.zh.md)
- [DeepSeek Harness Subagent](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/subsystems/subagent.zh.md)
- [DeepSeek Harness Session Title](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/session/session-title/README.zh.md)

## 先回答一个问题

不是所有对象都要做成 Plugin。

“一切都是 Plugin”指的是：所有可替换的产品能力、基础设施能力和运行时扩展，都必须通过 Plugin 安装、注册和管理，而不是散落在 Agent 工厂里写死。

以下对象不应做成 Plugin：

| 对象 | 原因 |
|---|---|
| 一次 Run | 是一次执行实例，不是可替换能力 |
| 一个 Thread | 是持久化会话对象 |
| 一个 Agent 实例 | 是 Plugin 注册的 Definition/Provider 创建出来的运行时实例 |
| 一条消息 | 是事件或领域数据 |
| 一次 Tool Call | 是执行过程中的事件 |
| 一个事件 payload | 是通信数据，不拥有生命周期 |

以下是能力 seam 中的注册角色，可以由一个或多个 Plugin 安装、实现或消费：

| 对象 | Plugin 的职责 |
|---|---|
| Tool | 作为 Consumer 或能力实现，注册工具 schema、执行器、权限和展示信息 |
| Skill | 作为资源或 Provider 被发现，并声明作用域 |
| Middleware/Hook | 作为 Plugin 的实现机制，注册 Agent 或 Tool 执行链的拦截行为 |
| Provider | 实现模型、Embedding、Retrieval 或 Subagent 后端 |
| Agent Definition | 声明一个可创建的 Agent 角色、Prompt、工具集合和输出协议 |
| Service Definition | 声明标题、Subagent、事件、持久化等能力的接口；它本身不是运行时实例 |
| Consumer | 使用某个 Service；它可以是 Plugin、工具、API 或普通产品代码 |

这些角色不是 Plugin 的同义词。一个 `LegalSubagentsPlugin` 可以同时注册
`SubagentRuntime` 的 Provider 和多个 Agent Definition；一个产品 API 也可以直接消费
Service，而不需要再包装成 Plugin。Plugin 是负责装配和生命周期的单位，角色是它安装或使用的
能力面。实际运行中的 Service 仍然由一个 Service Plugin 安装；Definition 只是它对外暴露的
接口契约。

## Plugin 与 Middleware 的区别

Plugin 是能力的组合、依赖和生命周期单位。它可以注册 Service、Provider、Tool、Agent Definition、事件监听器或 Middleware，并在卸载时撤销这些注册。

Middleware 是执行链上的一种技术机制。它只能在指定的生命周期 hook 中观察、修改或阻止请求、模型调用、工具调用或结果。

两者关系是：

```text
Plugin
  ├── 注册 Service
  ├── 注册 Provider
  ├── 注册 Tool
  ├── 注册 Agent Definition
  ├── 监听 Typed Event
  └── 安装 Middleware/Hook
```

因此：

- 每个 Middleware 可以由 Plugin 安装；
- 但不是每个 Plugin 都是 Middleware；
- Title 和 Subagent 都是完整能力，不应只建模成 Middleware；
- `additional_middlewares=[...]` 是底层组件注入，不等于完整的 Plugin 系统。

## DeepSeek Harness 的关键借鉴

DeepSeek Harness 将一个能力拆成三个角色：

```text
Service Definition
        ↓
Service Provider
        ↓
Consumer
```

例如 Subagent：

```text
SubagentRuntime Service
        │
        ├── In-process Provider
        ├── ACP Provider
        ├── Codex Provider
        └── Claude Code Provider
                │
                ├── Delegation Tool Consumer
                ├── Control Tool Consumer
                └── Report Tool Consumer
```

这种设计解决了几个问题：

- 主 Agent 不需要知道子 Agent 如何执行；
- 子 Agent 不被写死为主 Agent Graph 的一个节点；
- Provider 可以替换执行方式；
- Consumer 可以决定是否把能力暴露给模型；
- Provider 能力不足时，在启动前明确失败；
- `subagent/start` 和 `subagent/end` 可以作为统一可观测事件。

## Lexora 的目标插件结构

```text
North Runtime Plugins
├── Agent Runtime Plugin
├── Tool Registry Plugin
├── Stream/Run Journal Plugin
├── Subagent Runtime Plugin
├── In-process Subagent Provider Plugin
└── Conversation Title Service Plugin

Lexora Application Plugins
├── Legal Supervisor Definition Plugin
├── Legal Subagents Plugin
│   ├── Case Analyst Definition
│   └── Legal Researcher Definition
├── Legal Retrieval Tool Plugin
├── Case Context Plugin
├── Legal Title Provider Plugin
└── Legal Observability Plugin
```

这里的 `Case Analyst` 和 `Legal Researcher` 是由 `LegalSubagentsPlugin` 注册的 Agent
Definition，不是两个固定写在 Supervisor 工厂里的子 Agent 实例。只有当两个角色拥有独立的
配置开关、依赖或生命周期时，才拆成不同的 Plugin。

运行时关系是：

```text
CaseAnalystPlugin
    ↓ 注册 CaseAnalystDefinition
SubagentRuntime
    ↓ 根据 Supervisor 的委派请求创建实例
Case Analyst Agent Instance
    ↓ 产生 subagent.start / tool.* / subagent.end 事件
Lexora RunJournal
```

子 Agent 实例仍然拥有自己的上下文、工具、取消信号和生命周期，但它不是 Plugin。Plugin 注册的是“如何创建这种角色”和“允许它使用什么能力”。

## Title 的目标设计

当前实现是 North 的 `TitleMiddleware` 在首轮 `after_model` 中调用辅助模型。目标设计改为：

```text
North TitleServicePlugin
        │
        ├── Title Service Definition
        └── Title Service Runtime Instance
                │
                └── LexoraTitleProviderPlugin
```

North 的 `TitleServicePlugin` 安装的 `ConversationTitleService` 负责：

- 读取已接受的用户消息；
- 生成确定性的短标题 fallback；
- 管理并发、取消和过期结果；
- 保护用户手动重命名；
- 将标题写入统一事件或线程元数据；
- 不阻塞主 Agent 的回答。

`LexoraTitleProviderPlugin` 负责：

- 选择标题模型；
- 定义法律应用的标题提示词；
- 把模型结果交给 Title Service 校验和持久化。

Lexora 的第一版目标以 `conversation_threads.title` 作为产品侧标题权威，所有自动标题和手动
重命名都通过 Conversation Service 的条件更新进入该表，并同步案件列表所需的案件标题。若
North 以后提供通用 Thread Title Service，必须定义对应的持久事件和投影规则，不能假设 Lexora
已经存在 DeepSeek 的 `session/title` 事件。

标题生成是否使用 `after_model` 只是实现细节，不再是公共架构契约。目标实现应允许在用户消息
成功接收后异步生成标题，因此标题模型变慢时不会延迟主回答；迁移期间仍要保留当前
`TitleMiddleware` 的 fallback 和“用户标题不可覆盖”语义。

## Lexora Subagent 的目标设计

第一阶段只实现进程内 Provider，但保留可替换的 Service/Provider/Consumer 分层：

```text
North SubagentRuntime
        │
        └── InProcessSubagentProvider
                │
                ├── CaseAnalystDefinition
                └── LegalResearcherDefinition
                        │
                        └── Delegation Consumer Tool
```

Lexora 的 Agent Definition 应声明：

- 稳定名称和中文展示名；
- system prompt 或 persona；
- 可使用的 Tool/Skill；
- 输出 Schema；
- 最大递归深度和超时；
- 是否允许继续对话；
- 允许继承哪些上下文。

Definition 可以声明递归深度、超时和工具范围等意图，但最终约束必须由
SubagentRuntime/Provider 在执行时强制，不能只依赖 Prompt 或 Definition 字段。

Supervisor 只看到受控的委派工具，不直接创建子 Agent，也不提交 case id、user id 等产品标识。工具闭包和运行时上下文负责注入可信的案件上下文。

## 当前实现到目标模型

| 当前实现 | 目标模型 | 迁移风险 |
|---|---|---|
| North 根据 `AppConfig` 自动追加 `TitleMiddleware` | North 提供 Title Service Definition，Lexora 注册标题 Provider | 标题触发时机、取消、持久化权威和首轮延迟会变化 |
| `TitleMiddleware` 在同一 Run 的 `after_model` 调用辅助模型 | Title Service 在用户消息接收后异步生成并投影到 Lexora 标题 | 需要保留 fallback、手动重命名保护和并发条件更新 |
| `SubagentSpec` 在 `build_agent` 时预编译子 Agent | SubagentRuntime 按 Definition 和 Provider 在委派时创建实例 | 影响取消、超时、Checkpointer、事件归属和结果 Schema |
| `additional_middlewares` 传入裸 middleware 实例 | Lexora Plugin 通过注册表安装 Middleware/Hook | 需要定义作用域、顺序、重复注册和 disposer |
| Lexora Gateway 直接持有法律工具和子 Agent 工厂 | Legal Plugin 注册 Definition、Tool Consumer 和领域 Provider | 需要保证产品上下文仍由可信闭包注入 |

这张表中的目标模型不是当前 North 已有的契约。每一行都必须先有独立的迁移切片和回归测试，不能通过批量重命名完成。

## 本次实施计划

本次迁移采用直接切换，不保留旧装配入口。旧的 `AppConfig.auto_title_enabled`、
`title_model_name`、`title_max_chars`、裸 `additional_middlewares` 和 `SubagentSpec` 都会在
对应阶段移除，North、Lexora 和 Dayboard 一起更新。

### Phase 0：插件运行时契约

North 增加最小的 `Plugin`、`PluginContext`、`RegistrationHandle` 和分作用域注册表。
插件安装顺序由显式依赖决定；重复注册、缺少依赖和非法作用域在安装阶段失败。每次注册都
返回可撤销句柄，RunJournal 使用稳定的 `plugin_id` 记录来源。

验收标准：North 能在无业务代码的测试中安装、查询和卸载一个插件；插件卸载后工具、Hook、
Definition 和事件监听器均不再生效。

### Phase 1：宿主组合根

`build_agent()` 只接收宿主提供的插件集合和基础运行参数。North 负责创建 Agent Runtime，
插件负责注册工具、Hook、Agent Definition 和 Provider。Lexora 与 Dayboard 分别建立自己的
组合根，不再依赖 North 根据配置猜测产品能力。

验收标准：两个宿主都能在同一 North 版本上启动，插件列表和作用域可通过测试事件观察到。

### Phase 2：标题能力（下一切片）

North 提供 `TitleServicePlugin`；Lexora 和 Dayboard 各自注册标题 Provider。标题生成从主
Agent 的模型 middleware 中移出，采用异步服务调用；产品侧保留手动重命名保护、fallback、
条件更新和失败不影响主回答的语义。

验收标准：标题辅助模型失败不会改变主 Run 结果；同一线程不会重复生成；用户重命名后自动
标题不会覆盖；标题事件和数据库投影可回放。

### Phase 3：子 Agent 能力

North 提供 `SubagentRuntimePlugin` 和首个进程内 Provider。Lexora 的
`LegalSubagentsPlugin` 注册 Case Analyst 与 Legal Researcher Definition，并注册受控委派
Consumer。现有 `SubagentSpec` 直接替换为 Definition、Provider 和 Runtime 请求协议，不增加
兼容适配层。

验收标准：委派时创建独立子 Agent；取消、超时、递归限制、工具范围、结果 Schema 和
`subagent.start/end` 事件均有测试；主 Agent 不直接持有子 Agent 实例。

### Phase 4：观察性和产品投影

RunJournal、StreamBridge 和前端活动时间线统一消费插件和能力事件。事件包含插件 ID、能力
角色、Agent 作用域、显示名称和生命周期状态；同一工具或子 Agent 的状态在前端更新同一条活动
记录，不生成重复行。

验收标准：页面能区分 Plugin、主 Agent、Subagent、Tool 和 Middleware Hook；历史 Run 可以
从 `run_events` 重建同样的活动时间线。

### Phase 5：清理与同步

删除旧字段、旧装配参数、旧工厂和失效测试；Dayboard 与 Lexora 使用同一 North 插件契约。
完成 North、Lexora、Dayboard 三个仓库的测试、类型检查和部署构建后再提交。

## Plugin 的最小运行时要求

North 不需要一开始复制完整 Cordis，但第一阶段的 Plugin 机制至少需要具备：

1. 稳定的 Plugin ID。
2. 明确的依赖声明。
3. 安装时注册 Service、Provider、Tool、Definition 或 Hook。
4. 注册返回可执行的 disposer，支持测试和服务重载。
5. 明确 `application`、`lead_agent`、`subagent` 三种安装作用域，以及子作用域是否继承注册。
6. 注册和运行事件携带 Plugin ID，便于 RunJournal 和前端展示。
7. 能力不支持时尽早失败，禁止静默降级。
8. Plugin 配置由宿主应用提供，North 不隐藏读取 Lexora 产品配置。

第一阶段只需要一个最小的安装上下文，不引入通用的“大对象贡献”协议：

```python
class Plugin(Protocol):
    plugin_id: str
    requires: tuple[str, ...]

    def install(self, context: PluginContext) -> RegistrationHandle:
        ...


class PluginContext(Protocol):
    def service(self, key: str) -> object: ...
    def register(self, key: str, value: object) -> RegistrationHandle: ...
    def on(self, event: str, handler: object) -> RegistrationHandle: ...
```

`RegistrationHandle` 必须能撤销对应注册；Provider、Tool、Agent Definition 和 Hook 使用各自
的注册表，而不是把所有对象塞进一个 `PluginContribution` 字典。冲突注册、依赖缺失和作用域
不允许都在安装阶段失败。

第一阶段采用进程内、类型明确的 Plugin Registry 即可。暂不引入动态下载、第三方 entry point、版本协商和远程插件市场；这些属于部署层能力，等有真实插件消费者后再增加。

## 迁移顺序

```text
阶段 0  确定 PluginContext、RegistrationHandle、作用域和冲突规则
阶段 1  定义 Plugin / Service / Provider / Consumer 术语和边界
阶段 2  将 TitleMiddleware 迁移为 Title Service + Lexora Provider
阶段 3  直接将 SubagentSpec 替换为 SubagentRuntime、Provider 和 Agent Definition
阶段 4  将 Case Analyst、Legal Researcher、Legal Tools 迁移为 Lexora Plugins
阶段 5  将 RunJournal、StreamBridge、Observability 迁移为可组合插件
阶段 6  Dayboard 按同一套 North Plugin 契约接入
```

阶段 3 会直接移除当前 North 在 `build_agent` 时预编译子 Agent 的路径，改为由
SubagentRuntime 在委派时根据 Definition 创建实例。该迁移会同步处理取消、Checkpointer、
事件归属和结果 Schema，不能通过简单重命名 `SubagentSpec` 完成。

本次切换不保留 `additional_middlewares` 兼容 API。当前标题仍通过 `lexora.title` Plugin 安装 Middleware；下一切片再将其替换为异步 Title Service Definition + Provider，并保持同一插件组合根。

## 当前不做的事

- 不把每个 Run、Message 或 Agent 实例包装成 Plugin。
- 不为了形式统一而给每个 Python 类增加 `Plugin` 后缀。
- 不立刻实现完整 Cordis 风格的动态加载系统。
- 不把 Service Definition、Provider、Consumer 三个角色强行拆成三个 Plugin。
- 不在第一阶段实现可继续子 Agent、跨进程 Provider 和完整能力协商。
- 不把所有业务流程拆成固定 Workflow。
- 不让 Plugin 绕过 RunJournal、权限和 Checkpointer 直接写数据库。

目标是让可替换能力拥有清晰的安装和生命周期，同时保持 Lexora 的法律领域逻辑在应用层，不是创建一个更大的框架。
