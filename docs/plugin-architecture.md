# Lexora 插件与能力模型

## 文档状态

本文记录 Lexora 与 North 的插件化架构及当前迁移状态。当前优先保持插件简单：一个 Plugin
可以完整拥有一项能力及其 Middleware、Tool 和 Agent Definition。本文参考 DeepSeek Harness
的可替换能力设计，但不直接复制其运行时复杂度。

参考：

- [DeepSeek Harness 架构](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/architecture.zh.md)
- [DeepSeek Harness Subagent](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/subsystems/subagent.zh.md)
- [DeepSeek Harness Session Title](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/session/session-title/README.zh.md)

## 核心原则

> 抽象必须消除真实复杂度。

默认让一个 Plugin 完整拥有一项能力及其 Middleware、Tool 或 Agent Definition。只有出现
多个独立消费者、多个真实 Provider，或跨运行时生命周期时，才抽取 Service seam。不要为了
结构对称预先建立不会被真实消费者使用的 Service/Provider Registry。

Plugin 是能力的装配、依赖和生命周期单位。Run、Thread、Agent 实例、Message 和 Tool Call
是运行时对象或事件，不是 Plugin。

## Plugin 与能力角色

Plugin 可以注册或使用以下角色，但这些角色不是 Plugin 的同义词：

| 角色 | 含义 |
|---|---|
| Tool | 提供模型可调用的 schema、执行器、权限和展示信息 |
| Middleware/Hook | 参与 Agent、模型或工具执行链的生命周期 hook |
| Agent Definition | 声明可创建的 Agent 角色、Prompt、工具集合和输出协议 |
| Provider | 在确实需要替换实现时提供模型、Embedding、Retrieval 或 Subagent 后端 |
| Consumer | 使用某项能力的工具、API、渲染器或其他产品代码 |

DeepSeek Harness 将可替换能力描述为 Service Definition、Provider、Consumer 三个角色。这
是一种识别替换点的模型，不是每个 Plugin 的固定模板。一个 `LegalSubagentsPlugin` 可以
同时注册多个 Agent Definition、Provider 和委派工具；一个产品 API 也可以直接消费能力，不
需要再包装成 Plugin。

## Plugin 与 Middleware 的区别

Middleware 是执行链上的一种技术机制，只在指定 hook 中观察、修改或阻止执行。Plugin 是
拥有能力、依赖和卸载边界的装配单位，能够注册 Middleware，也能同时注册 Tool 和 Agent
Definition：

```text
Plugin
  ├── register_tool()
  ├── register_middleware()
  ├── register_agent_definition()
  └── optional provider / event hooks
```

因此每个 Middleware 可以由 Plugin 安装，但 Plugin 不是 Middleware。`additional_middlewares`
这种裸参数注入也不等于完整的 Plugin 系统。

## North 与 Lexora 的目标结构

```text
North Agent Plugin Host
├── tools
├── middleware
└── agent definitions

Lexora Agent Plugins
├── Lexora tools plugin
├── Lexora title plugin
├── Legal supervisor definition
├── Legal subagents plugin
│   ├── Case Analyst Definition
│   └── Legal Researcher Definition
└── Legal retrieval / observability plugins
```

North 负责 Agent 运行时和类型明确的注册表，不读取 Lexora 的业务仓储或法律配置。Lexora
负责组合根、法律 Prompt、工具和子 Agent Definition。Dayboard 使用同一套 North Plugin
契约，由自己的组合根注册日程领域能力。

## Title 设计

标题是 Agent 的可选运行时能力，不单独抽取 Service。`LexoraTitlePlugin` 完整拥有标题
Prompt、fallback 规则和 `TitleMiddleware`，通过 North Plugin Context 注册 Middleware：

```text
LexoraTitlePlugin
├── title prompt
├── fallback / normalization
└── TitleMiddleware
        ↓ register_middleware()
North Agent Runtime
```

删除或替换 `LexoraTitlePlugin` 就会删除或替换整套标题行为，North 不需要理解法律标题规则，
也不需要维护空的 Title Service Registry。只有标题未来需要脱离 LangChain、被 API 和后台
任务共同调用，或者出现多个独立 Provider 时，才评估抽取 Service seam。

## Subagent 设计

第一阶段只实现进程内 Provider。Provider 是子 Agent 能力的实现角色，先由同一个
`LegalSubagentsPlugin` 持有，不预先建立通用 Service Registry：

```text
Supervisor
    ↓ delegation tool
North SubagentRuntime
    ↓
Lexora LegalSubagentsPlugin
    ├── CaseAnalystDefinition
    └── LegalResearcherDefinition
```

Agent Definition 声明：

- 稳定名称和中文展示名；
- system prompt 或 persona；
- 可使用的 Tool/Skill；
- 输出 Schema；
- 最大递归深度和超时意图；
- 是否允许继续对话；
- 允许继承哪些上下文。

Definition 只表达静态意图，递归、超时、取消、工具范围和结果校验必须由
SubagentRuntime/Provider 在执行时强制。子 Agent 实例拥有自己的上下文、取消信号和生命
周期，但实例不是 Plugin。

## 当前实现到目标模型

| 当前实现 | 目标模型 | 迁移边界 |
|---|---|---|
| `lexora.title` Plugin 注册 `TitleMiddleware` | 继续由 Plugin 完整拥有标题实现 | 没有真实 Service 消费者前不拆分 |
| `TitleMiddleware` 在首轮模型完成后生成标题 | 保持同一 Run 内生成标题，不创建额外 Run | 先验证延迟、fallback 和持久化 |
| Lexora Plugin 注册 `AgentDefinition`，委派工具在调用时懒创建子 Agent | 继续由 SubagentRuntime 按 Definition 创建实例 | 重点验证取消、超时、Checkpointer、事件归属和结果 Schema |
| 裸 `additional_middlewares` | 宿主 Plugin 通过注册表安装 Middleware | 直接切换，不保留旧装配入口 |

目标模型不是当前 North 已全部实现的契约。每一行都必须有独立迁移切片和回归测试，不能
通过批量重命名完成。

## 最小运行时契约

第一阶段只实现进程内、类型明确的 Plugin Registry：

1. 稳定 Plugin ID；
2. 显式依赖和依赖排序；
3. `lead_agent`、`subagent` 作用域；
4. 每次注册返回可撤销的 `RegistrationHandle`；
5. 重复注册、缺少依赖和非法作用域在安装阶段失败；
6. 运行事件携带 Plugin ID，便于 RunJournal 观察来源。

最小上下文只暴露实际需要的注册入口：

```python
class PluginContext(Protocol):
    def register_tool(self, tool: object) -> RegistrationHandle: ...
    def register_middleware(self, middleware: object) -> RegistrationHandle: ...
    def register_agent_definition(self, definition: object) -> RegistrationHandle: ...
```

暂不引入动态下载、第三方 entry point、版本协商、远程插件市场或通用贡献字典。

## 实施计划

### Phase 0：插件运行时契约

North 提供最小 `Plugin`、`PluginContext`、`RegistrationHandle` 和分作用域注册表。插件
卸载后工具、Middleware 和 Definition 均不再生效。

### Phase 1：宿主组合根

`build_agent()` 接收宿主提供的插件集合和基础运行参数。Lexora 与 Dayboard 建立自己的组合
根，不再依赖 North 根据产品配置猜测能力。

### Phase 2：标题能力

Lexora 通过 `LexoraTitlePlugin` 注册 North `TitleMiddleware`。覆盖标题 Prompt、fallback、
持久化和前端体验；不增加 Title Service 或 Provider 兼容层。

### Phase 3：子 Agent 能力（基础切片已完成）

North 提供进程内 SubagentRuntime。Lexora 的 `LegalSubagentsPlugin` 已注册 Case Analyst 和
Legal Researcher Definition，并注册受控委派工具。委派工具调用时才创建子 Agent，不保留
预编译实例或兼容适配层。

下一步是用真实对话验收 Supervisor → Case Analyst → Legal Researcher 的链路，并补齐取消、
超时、事件归属、中文展示名称和前端同一活动记录的状态更新。

### Phase 4：观察性和产品投影

RunJournal、StreamBridge 和前端活动时间线消费 Plugin、Agent、Subagent、Tool 和 Middleware
事件。同一工具或子 Agent 的状态更新同一条活动记录，不生成重复行。

### Phase 5：清理与同步

删除旧字段、旧装配参数、旧工厂和失效测试；Dayboard 与 Lexora 使用同一 North Plugin 契约。
完成三仓库测试、类型检查和部署构建后再提交。

## 当前不做的事

- 不把每个 Run、Message 或 Agent 实例包装成 Plugin；
- 不为了形式统一给每个 Python 类增加 `Plugin` 后缀；
- 不立刻实现完整 Cordis 风格的动态加载系统；
- 不把 Service Definition、Provider、Consumer 强行拆成三个 Plugin；
- 不在第一阶段实现可继续子 Agent、跨进程 Provider 和完整能力协商；
- 不把所有业务流程拆成固定 Workflow；
- 不让 Plugin 绕过 RunJournal、权限和 Checkpointer 直接写数据库。

目标是让可替换能力拥有清晰的安装和生命周期，同时保持 Lexora 的法律领域逻辑在应用层，
而不是创建一个更大的框架。
