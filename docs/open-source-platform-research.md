# 中国市场低频量化平台开源选型调研

> 调研日期：2026-09-08；用途：博士课程期中项目，A 股场内 ETF 日频研究与模拟交易。  
> 证据原则：优先使用项目官方 GitHub 仓库、仓库内许可证和官方文档。“最新提交”只表示调研日当时默认分支的可见状态，不等于稳定性保证。

## 结论先行

不建议从头实现事件引擎、组合回测、撮合、风控和委托回报等通用能力；也不建议直接把整个产品寄托在任一桌面客户端自动化上。适合本项目的组合是：

1. **交易基础设施优先复用 VeighNa/vn.py**：事件引擎、`portfolio_strategy`/`cta_strategy`、回测、`paper_account`、`risk_manager` 和数据库适配均已有官方模块；MIT 许可，中国市场适配强，且仍活跃维护。
2. **策略边界由本项目掌控**：向用户暴露一个稳定的“市场快照 + 当前持仓 -> 目标组合”接口；内部再用 adapter 转换为 vn.py 等引擎的事件或委托。这样用户后续更新策略时不被某一开源框架的基类锁定。
3. **数据采集可先用 AkShare，但必须缓存和版本化**：AkShare 能取得东方财富 ETF/A 股数据，但官方声明明确存在数据风险且接口可能移除，不能在策略运行时直连网页端点。
4. **必须自带本地 `PaperBroker`**：vn.py 也有本地 `paper_account`，可作为内部实现或对照。无论同花顺/东方财富桌面端是否可用，课程演示都能完成。
5. **外部交易接入顺序**：有权限时优先官方 MiniQMT/XTP/TORA 等 API；其次才是 easytrader 的同花顺 GUI 自动化；本次未在所核查项目的官方支持列表中发现东方财富零售模拟盘交易 gateway，不把它设为验收前提。

## 候选项对比

| 项目 | 许可证/活跃度（截至调研日） | 日频研究与回测 | 模拟/实盘 | A 股/ETF 与可插拔性 | 本项目判断 |
|---|---|---|---|---|---|
| [VeighNa/vn.py](https://github.com/vnpy/vnpy) | [MIT](https://github.com/vnpy/vnpy/blob/master/LICENSE)；[4.4.0（2026-05-14）](https://github.com/vnpy/vnpy/releases/tag/4.4.0)；[2026-08-06 提交](https://github.com/vnpy/vnpy/commit/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09) | 历史数据、CTA/组合策略回测、参数优化 | 官方 `paper_account`；多种实盘 gateway | 官方列出 XTP、TORA、OST、EMT 等 A 股接口；app/gateway/datafeed 模块化 | **作为基础设施首选**，但在外层保留自有策略 API |
| [Microsoft Qlib](https://github.com/microsoft/qlib) | [MIT](https://github.com/microsoft/qlib/blob/main/LICENSE)；[v0.9.7（2025-08-15）](https://github.com/microsoft/qlib/releases/tag/v0.9.7)；[2026-07-23 提交](https://github.com/microsoft/qlib/commit/79633dd9506ea689e5400dea0197717b5b3d74b7) | 强项：数据处理、特征、ML、组合、回测 | 有 executor/在线模型服务，但无类似 vn.py 的核心券商 gateway/独立纸面账户 | 原生 `REG_CN`/`cn_data`；`Strategy`/`Executor` 可扩展；官方数据集当前暂停 | **后续 ML/因子研究可选**，不作交易核心 |
| [RQAlpha](https://github.com/ricequant/rqalpha) | [自定义非商业许可](https://github.com/ricequant/rqalpha/blob/master/LICENSE)；[6.3.0（2026-07-23）](https://github.com/ricequant/rqalpha/releases/tag/release/6.3.0)；[2026-09-07 提交](https://github.com/ricequant/rqalpha/commit/a5fb4e43879c381e61131399dcc094d495c7080a) | A 股事件回测、税费、风控、scheduler 成熟 | `sys_simulation` 模拟撮合；Ricequant 平台可模拟/实盘 | Mod Hook 可替换 data source/broker/event source；RQData 对 A 股和基金强 | **课程内回测对照可用**；许可和服务依赖使其不适合核心 |
| [Backtrader](https://github.com/mementum/backtrader) | [GPL-3.0](https://github.com/mementum/backtrader/blob/master/LICENSE)；无 GitHub Release；[默认分支最后提交 2023-04-19](https://github.com/mementum/backtrader/commit/b853d7c90b6721476eb5a5ea3135224e33db1f14) | 成熟、简单，支持日线/多周期 | 内置回测 broker；旧的 IB/Oanda/Visual Chart 实盘适配 | `Strategy`/Feed/Broker 可扩展，但无原生 A 股交易日历、涨跌停、T+1、税费或国内 gateway | **不采用**：需补的中国市场轮子太多，且维护不活跃 |
| [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | [Apache-2.0](https://github.com/QuantConnect/Lean/blob/master/LICENSE)；[2026-09-04 提交](https://github.com/QuantConnect/Lean/commit/23b735d99a357807dc0df9f4c51d30f05fe0d277) | 专业级事件引擎，本地回测/优化成熟 | 官方支持 live，多国际券商适配 | 各模块可插拔；C# 核心；所审阅的[官方 Brokerages 列表](https://github.com/QuantConnect/Lean/tree/master/Brokerages)无中国 A 股零售券商 | **不采用**：引入语言/部署复杂度，仍要自做中国适配 |
| [easytrader](https://github.com/shidenggui/easytrader) | [MIT](https://github.com/shidenggui/easytrader/blob/master/LICENSE)；无 GitHub Release；[2026-02-28 提交](https://github.com/shidenggui/easytrader/commit/def5a8edc5ebd7d49bf92a9f39e9e30c9bf47101) | 不是回测/研究框架 | 同花顺客户端 GUI 自动化；也支持 MiniQMT 官方接口 | 交易 API 简单；同花顺专用客户端需手动登录；官方支持列表未列东方财富 | **仅可作外围可选 adapter**，不作核心或验收依赖 |
| [AKShare](https://github.com/akfamily/akshare) | [MIT](https://github.com/akfamily/akshare/blob/main/LICENSE)；[1.18.94（2026-08-21）](https://github.com/akfamily/akshare/releases/tag/release-v1.18.94)；[2026-08-28 提交](https://github.com/akfamily/akshare/commit/8e95744b79ae22326308ccd2b4e62650c5b53c55) | 只是数据工具，不是回测引擎 | 无 | 提供东方财富 A 股/ETF 日线和实时接口；函数级可替换 | **作为可替换的首个数据采集器**，必须落地快照与质量检查 |
| [WonderTrader](https://github.com/wondertrader/wondertrader) / [wtpy](https://github.com/wondertrader/wtpy) | [MIT](https://github.com/wondertrader/wondertrader/blob/master/LICENSE)；主仓库的[提交记录](https://github.com/wondertrader/wondertrader/commits/master/) 显示仍有活动 | C++ 回测；SEL 引擎专门支持多因子选股/日周月定时重算 | 从数据、回测到实盘和监控完整 | 策略设目标仓位；股票 gateway 主要是 XTP/ATP/OES 等机构接口 | **强备选，但本项目不采用**：能力过量、C++/Python 混合部署较重 |
| [QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | [MIT](https://github.com/yutiansut/QUANTAXIS/blob/master/LICENSE)；README 当前标注 `2.1.0-alpha2`；[2026-09-01 提交](https://github.com/yutiansut/QUANTAXIS/commit/5006a009fba7b8e392e32f8b577f1bcb81deba5c) | 中国市场数据、因子、账户与回测能力广 | README 列出 QMT、OMS 和 OrderGateway | 可扩展面广，但 2.1 仍是 alpha，且引入 Rust、MongoDB/ClickHouse/RabbitMQ 等较广架构 | **不作核心**：课程 MVP 不需要这个复杂度 |
| [AKQuant](https://github.com/akfamily/akquant) | [MIT](https://github.com/akfamily/akquant/blob/main/LICENSE)；新且快速演进 | Rust 内核 + Python `Strategy`，支持回测、滚动验证、风控和参数优化 | 官方 README 聚焦回测，未展示完整券商/模拟盘业务闭环 | 与 AkShare 数据直接配合，策略继承 `Strategy` | **值得跟踪/可做回测对照**，暂不承担平台核心 |

## 重点事实与选型理由

### 1. VeighNa/vn.py：复用最多，但不向用户泄漏框架耦合

vn.py 的[官方功能列表](https://github.com/vnpy/vnpy#%E5%8A%9F%E8%83%BD%E7%89%B9%E7%82%B9)同时列出：

- A 股 gateway：XTP、TORA、OST、EMT；
- `portfolio_strategy`：多合约组合策略，支持历史回测与实盘自动交易；
- [`paper_account`](https://github.com/vnpy/vnpy_paperaccount)：基于实时行情的本地模拟撮合、委托回报和持仓记录；
- [`risk_manager`](https://github.com/vnpy/vnpy_riskmanager)：交易流控、委托数、活动委托数和撤单数等事前风控；
- datafeed 与 database 适配：RQData、XtQuant、TuShare、Wind、iFinD 等，以及 SQLite/PostgreSQL 等。

因此，事件分发、历史回测、模拟撮合和交易回报不应重写。但 vn.py 原生策略通常继承特定 app 的模板类；本项目应用一层 `StrategyPlugin` 协议隔离这一点，并把 vn.py 定位为“可替换引擎 adapter”。

### 2. Qlib：适合研究层，不是零售模拟盘接入层

Qlib [官方架构说明](https://github.com/microsoft/qlib#framework-of-qlib)将数据、模型、策略、executor、分析和在线模型服务解耦，适合后续增加横截面因子、ML 预测和滚动训练。但其[数据准备说明](https://github.com/microsoft/qlib#data-preparation)明确表示官方数据集当前暂停，需社区数据或用户自备数据；“online”也不应误读为已提供东方财富/同花顺券商接入。

### 3. RQAlpha：技术匹配，但许可边界必须写清

RQAlpha 的[官方 README](https://github.com/ricequant/rqalpha#rqalpha)明确覆盖回测、实盘模拟、实盘交易和分析，其 [Mod Hook](https://rqalpha.readthedocs.io/zh-cn/latest/development/mod.html) 可替换数据源、broker 和事件源，中国市场语义很好。但该项目不是无条件 Apache-2.0：[许可证](https://github.com/ricequant/rqalpha/blob/master/LICENSE)规定非商业使用才按 Apache-2.0，商业使用需授权。当前高校教学属于其明示允许的非商业场景，但为了不给未来扩展留隐性限制，不将其作为核心依赖。

### 4. easytrader：同花顺自动化可验证，但只能是外围适配器

easytrader [README](https://github.com/shidenggui/easytrader#easytrader)的原话是“通用的同花顺客户端模拟操作”，并另列 MiniQMT 官方量化接口。它的[客户端选择代码](https://github.com/shidenggui/easytrader/blob/master/easytrader/api.py)列出同花顺、通用同花顺、多个券商客户端和 MiniQMT，未列东方财富；[使用文档](https://github.com/shidenggui/easytrader/blob/master/docs/usage.md)还指出部分券商专用同花顺客户端不支持自动登录，需先手动登录。

这种方式可以做实验性 `TongHuaShunBrokerAdapter`，但需明确以下故障面：窗口标题/表格结构变化、弹窗、验证码、手动登录、桌面会话丢失以及“提交超时但实际成功”。外层 OMS 必须先查询委托/成交再决定是否重试。

### 5. AkShare：数据采集而非数据库或交易平台

AkShare [README](https://github.com/akfamily/akshare#usage)展示了 A 股日线接口，并在接口检索示例中列出东方财富 ETF 实时行情 `fund_etf_spot_em`。但其[官方声明](https://github.com/akfamily/akshare#statement)同时写明：数据仅供学术研究，用户要注意数据风险，且部分接口可能因不可控因素被移除。因此必须有 `MarketDataProvider` 协议，并将原始响应与清洗后 Parquet 按日期/版本落地，不允许回测直接重拉可变的网络数据。

### 6. 其他平台：能力强不等于这个 MVP 更合适

- LEAN [README](https://github.com/QuantConnect/Lean#readme)明确支持本地回测、优化和 live，模块化也很好；但本项目需要 Python 为主的中国 ETF 快速交付，LEAN 的 C# 核心与缺失国内券商 gateway 会带来无额外价值的工作。
- WonderTrader [README](https://github.com/wondertrader/wondertrader#readme)展示了目标仓位、回测、风控、组合、实盘、监控和日/周/月重算，非常匹配机构式需求；但它的 C++ 核心和机构级 gateway 选择对一个单账户课程 MVP 过重。
- QUANTAXIS [README](https://github.com/yutiansut/QUANTAXIS#readme)列出数据、账户、回测、QMT、OMS 和风控，但当前 2.1 仍标记 alpha，且其广泛基础设施超过本 MVP 需要。
- AKQuant [README](https://github.com/akfamily/akquant#readme)的 Python `Strategy` + Rust 回测内核、滚动验证和 AkShare 数据配合很值得跟踪，但它当前更像回测引擎，不是含 OMS、对账和券商适配的完整模拟交易平台。

## 对实现的直接约束

开源选型落到代码时，建议遵守下列边界：

```text
StrategyPlugin (project-owned, stable)
    -> TargetPortfolio
    -> PortfolioPlanner (project-owned)
    -> RiskEngine / OMS (project-owned business policy and audit)
    -> BrokerPort (project-owned interface)
        -> VnPyPaperAdapter or internal PaperBroker
        -> MiniQMT/VnPyGatewayAdapter (optional)
        -> EasyTraderTHSAdapter (experimental, optional)

MarketDataProvider (project-owned interface)
    -> AkShareCollector (first implementation)
    -> local versioned Parquet snapshot
    -> strategy/backtest only reads snapshots
```

需保留自有 `RiskEngine`/OMS 外层，不是否定 vn.py 的现成风控和订单能力，而是因为课程验收需要清楚展示幂等、审批、暂停/恢复、差异对账和审计记录。开源引擎负责通用机制，本项目负责可解释的业务政策。

## 现实的外部模拟盘判断

1. **同花顺**：easytrader 证明了通过 Windows 客户端 GUI 操作的可行性，但其官方文档也显示手动登录等限制。它是一个可失效的 adapter，不是可依赖的远程交易 API。
2. **东方财富**：AkShare 可复用东方财富的行情数据端点，但“有行情采集接口”不等于“有委托交易 API”。本次核查的 vn.py 与 easytrader 官方支持列表均未列东方财富零售模拟盘交易 gateway。
3. **更稳的路径**：如用户后续能获得 MiniQMT、XTP、TORA 等合规 API 权限，再新增 broker adapter；在此前，系统默认永远是本地模拟账户。

## 最终决策

- **立即复用**：vn.py 事件/组合回测/本地模拟/基础风控的成熟实现，AkShare 数据采集接口。
- **自行保留的产品核心**：策略插件协议、目标组合数据结构、版本/审批、OMS 幂等约束、对账、审计与 Web API。
- **可选扩展**：Qlib 用于后续因子/ML；MiniQMT 或 vn.py 证券 gateway 用于获权后的外部模拟/实盘对接；easytrader 仅用于同花顺技术演示。
- **不作核心**：RQAlpha（自定义非商业许可与服务依赖）、Backtrader（中国市场缺口与维护停滞）、LEAN（C#/国内 gateway 缺口）、WonderTrader 与 QUANTAXIS（对本 MVP 过重）、AKQuant（当前缺完整交易业务闭环）。
