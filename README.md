# 低频量化研究与模拟交易平台

面向课程项目的可运行 MVP：策略研究、历史回测、目标仓位、事前风控、模拟成交、持仓与审计形成一个闭环。策略通过独立插件目录接入，交易核心不依赖具体策略实现。

## 快速启动

PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn lowfreq.app:app --reload
```

打开 <http://127.0.0.1:8000>，接口文档位于 <http://127.0.0.1:8000/docs>。

平台默认通过 AkShare 获取东方财富股票/ETF历史行情，并按日缓存到 `data/cache/eastmoney_etf.csv`。通过“选股”可维护浏览器本地标的池并立即回测；东方财富单只证券接口连续失败时使用 AkShare 的新浪日线接口作为备用，已有证券仍优先读取本地缓存。点击“运行回测”可以选择1个月、3个月、半年、1年或全部历史区间；点击“执行模拟调仓”会经过策略、订单规划、风控和模拟成交。

默认研究池为10只跨行业大盘分红股票：贵州茅台、美的集团、伊利股份、长江电力、中国神华、中国移动、中国石油、工商银行、招商银行和中国平安。该池用于课程回测示例，不构成投资建议；正式研究应记录样本池形成日期，并检验幸存者偏差和调仓规则。

总览页还提供独立的 `OTC Pink` 研究组，默认选择腾讯、罗氏、雀巢、大众汽车、比亚迪、软银、任天堂、巴斯夫、德国电信和中国银行的OTC ADR。该组通过 AkShare 的新浪美股日线接口获取并缓存美元行情，按1股为交易单位，并采用50基点滑点假设。为避免陈旧报价，组合截止日期取所有入选证券共同拥有行情的最后日期；它不与A股缓存、币种或标的池混合。免费行情仅适合课程模拟，正式研究仍需用OTC Markets授权数据校验市场层级、退市、公司行动和历史证券池。

开源选型以 VeighNa/vn.py 为后续交易基础设施首选。当前 `0.1` 骨架保持轻量且不安装 vn.py 的完整桌面依赖；策略接口、目标组合和风控政策由本项目掌控，下一阶段通过适配器接入 vn.py 的事件、组合回测或模拟账户模块。选型证据见 `docs/open-source-platform-research.md`。

## 新增或更新策略

复制 `strategy_plugins/simple_trend.py`，修改策略 ID 和实现，然后在控制台点击“重新加载策略”。插件只需实现：

```python
def create_strategy() -> Strategy: ...
```

策略的核心调用是：

```python
result = strategy.generate(context)
```

`context.bars` 只包含 `context.as_of` 当日及之前的数据；策略返回各证券的目标权重，不允许直接下单。完整约束见 `src/lowfreq/strategy_api.py`。

插件是受信任的 Python 代码，会在平台进程中执行。真实生产环境应将研究策略放入隔离进程或容器，审批后再发布固定版本。

## 数据格式

CSV 适配器接受以下列：

```text
date,symbol,open,high,low,close,volume
```

日期应为交易日；价格必须为正数；成交量不能为负数。默认数据源为 `LOWFREQ_DATA_SOURCE=eastmoney`；测试或完全离线演示可改为 `demo`，自有数据可改为 `csv`。东方财富、CSV和演示行情均实现同一个 `MarketDataSource` 接口。

## 项目结构

```text
src/lowfreq/             平台核心
strategy_plugins/        用户维护的策略插件
static/                  Web 控制台
tests/                   接口级测试
docs/                    架构及开源调研
data/                    运行期数据库
```
