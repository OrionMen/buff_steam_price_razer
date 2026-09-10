# 饰差雷达（MVP）

一个只读、本地运行的 CS2 饰品价差观察器。它用 `market_hash_name` 匹配 BUFF 与 Steam，记录每次扫描到 SQLite，并按“实际 Steam 余额成本率”展示 Top 50。

页面优先展示 BUFF 返回的中文名称，同时保留英文 `market_hash_name` 作为跨市场匹配键。

> 本工具不自动买卖，不保存 Steam 登录凭证，也不把 BUFF Cookie 写入数据库。接口属于站点内部接口，可能变更；请低频使用并遵守平台规则。

## Windows（Git Bash）快速运行

需要先安装 Python 3.10 或更高版本，并在安装 Python 时勾选“Add Python to PATH”。Git for Windows 自带的 Git Bash 和 `curl` 可直接使用。

```bash
git clone https://github.com/OrionMen/buff_steam_price_razer.git
cd cs2-buff-steam-radar
bash start-windows.sh
```

第一次运行会自动创建虚拟环境、安装依赖，并生成 `.env`。请用文本编辑器打开 `.env`，按下方“切换到实时模式”填写 BUFF Cookie，然后再次执行：

```bash
bash start-windows.sh
```

浏览器打开 <http://127.0.0.1:5050>。以后启动只需在项目目录运行同一条命令。停止服务请在 Git Bash 中按 `Ctrl+C`。

## macOS / Linux 快速运行

需要 Python 3.10 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

浏览器打开 <http://127.0.0.1:5050>，点击“立即扫描”。默认 `SCAN_MODE=demo`，会写入一组仅用于验证界面和计算的示例数据，因此无需 Cookie 即可运行。端口可通过 `.env` 中的 `APP_PORT` 修改。

## 切换到实时模式

1. 在浏览器登录 BUFF，在浏览器开发者工具的网络请求中复制发往 `buff.163.com` 的 Cookie。Cookie 等同于临时登录凭证，只能保存在自己的电脑上。
2. 编辑本地 `.env`：

```dotenv
SCAN_MODE=live
BUFF_COOKIE=你的完整Cookie
BUFF_MIN_PRICE=20
BUFF_MAX_PRICE=2000
BUFF_PAGE_SIZE=20
```

重启应用后再扫描。Cookie 只从当前进程环境读取，不会写入页面、日志或 SQLite；`.env` 已加入 `.gitignore`。请勿分享 `.env`。

如果 Cookie 曾经被提交到 GitHub、发给别人或出现在截图中，请立即退出 BUFF 的其他登录会话并重新登录，以使旧 Cookie 失效。更多说明见 `SECURITY.md`。

## 指标

- 表面折扣 = BUFF 买价 / Steam 买家支付价
- Steam 预计实收 = Steam 买家支付价 / 1.15
- 余额成本率 = BUFF 买价 / Steam 预计实收（越低越好）
- 余额收益率 = Steam 预计实收 / BUFF 买价 - 1
- Steam 成交量来自 `priceoverview` 的 `volume` 字段，用于流动性参考
- 7 日波幅 = 最近 7 日最高价与最低价之差 / 7 日均价
- 7 日最大回撤 = 7 日内从阶段高点到随后低点的最大跌幅
- 压力收益 = 按最近 7 日最低 Steam 价卖出时的预计余额收益
- 脱手速度：24 小时销量 ≥100 为“快”，20–99 为“中”，低于 20 为“慢”

稳定性必须至少积累 4 个价格样本，并覆盖 5.5 天，才会显示“稳定 / 一般 / 波动大”。此前显示“积累中”。建议每天固定扫描 2–4 次；同一天反复点击不能代替跨天数据。

Steam 的低价物品存在最低手续费和分币取整，MVP 使用 `/ 1.15` 估算，不能视为承诺收益。页面评级只是初筛：A/B 同时要求较低余额成本和一定成交量。

## 关键文件

- `app.py`：本地网页入口与扫描按钮
- `start-windows.sh`：Windows Git Bash 一键安装与启动脚本
- `scanner/clients.py`：BUFF、Steam HTTP 客户端与 Steam 缓存/限频
- `scanner/pricing.py`：金额解析和四项核心指标
- `scanner/db.py`：SQLite 表结构、历史记录与 Top 50 查询
- `scanner/service.py`：一次扫描的编排
- `templates/index.html`、`static/style.css`：本地仪表盘
- `data/watchlist.json`：演示数据（不是真实行情）

## 数据与限频

数据库默认位于 `data/scanner.db`。Steam 查询默认间隔 1.5 秒，同一饰品结果缓存 15 分钟；都可在 `.env` 调整。实时模式先读取 Steam 热门候选20件，再用 `priceoverview` 的24小时销量重新排序，最后到 BUFF 精确查询同款；不会扫描全部市场。遇到 429 或临时服务器错误会做最多三次指数退避；单件失败不会中断整批扫描。如果仍频繁出现 429，请稍后再扫或提高 `STEAM_REQUEST_INTERVAL`。

如果 Steam `priceoverview` 返回 429，扫描器会自动改用 Steam 市场搜索接口的实时美元最低价，并通过 Frankfurter 的当日 USD/CNY 汇率换算。降级接口提供当前在售数量，但不提供过去 24 小时销量，所以销量与脱手速度会标记为未知。汇率服务不可用时使用 `USD_CNY_FALLBACK_RATE`。

Top 50 默认按“风险调整成本”排序：余额成本率之外，对历史不足、价格波动和低销量分别加入保守惩罚。它适合做候选池初筛，不是实际成交时间或收益承诺。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 开源许可

本项目使用 MIT License。它只提供行情观察与估算，不构成投资建议，也不保证价格、销量、手续费或预期收益准确。
