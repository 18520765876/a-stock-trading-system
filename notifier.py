"""
企微Webhook消息推送模块
负责成交明细和每日报告的推送
"""
import requests
import json
from datetime import datetime
from typing import Dict, List
from config import WECHAT_WEBHOOK

class Notifier:
    def __init__(self):
        self.webhook = WECHAT_WEBHOOK

    def _send(self, content: str, msg_type: str = "text") -> bool:
        """发送消息到企微群 - 已禁用webhook，通过stdout输出到当前聊天"""
        # Webhook已禁用，通过stdout输出（cron job会捕获stdout推送到当前聊天）
        if not self.webhook:
            print(content)
            return True
        try:
            if msg_type == "text":
                data = {
                    "msgtype": "text",
                    "text": {
                        "content": content
                    }
                }
            elif msg_type == "markdown":
                data = {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": content
                    }
                }
            else:
                return False

            resp = requests.post(
                self.webhook,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            result = resp.json()
            if result.get('errcode') == 0:
                return True
            else:
                print(f"[推送] 失败: {result}")
                return False
        except Exception as e:
            print(f"[推送] 异常: {e}")
            return False

    def send_trade(self, trade: Dict, account_pnl: float, account_pnl_pct: float, extra: Dict = None):
        """推送成交明细"""
        extra = extra or {}
        action_emoji = "🔴" if 'SELL' in trade['action'] else "🟢"
        action_text = "买入" if trade['action'] == 'BUY' else ("卖出一半" if trade['action'] == 'SELL_HALF' else "清仓")
        extra_text = ""
        if extra:
            capital_base = extra.get('capital_base', 0)
            injected_capital = extra.get('injected_capital', 0)
            fixed_trade_amount = extra.get('fixed_trade_amount', 0)
            extra_text = f"\n>累计股本: ¥{capital_base:,.2f}\n>扩充股本: ¥{injected_capital:,.2f}\n>单票定额: ¥{fixed_trade_amount:,.2f}"

        content = f"""{action_emoji} **模拟盘成交提醒**

>股票: {trade['name']} ({trade['code']})
>操作: {action_text}
>价格: ¥{trade['price']:.2f}
>数量: {trade['shares']}股
>金额: ¥{trade['amount']:,.2f}
>费用: 佣金¥{trade['commission']:.2f} + 印花¥{trade['stamp_tax']:.2f} + 过户¥{trade['transfer_fee']:.2f}
>实际: ¥{trade['total_cost']:,.2f}
>时间: {trade['trade_time']}{extra_text}

盘后账户总盈亏: ¥{account_pnl:,.2f} ({account_pnl_pct:+.2%})
"""
        self._send(content, "markdown")

    def send_daily_report(self, date_str: str, account_data: Dict):
        """推送每日盈亏报告"""
        positions = account_data.get('positions', [])
        trades = account_data.get('today_trades', [])
        cash = account_data.get('cash', 0)
        capital_base = account_data.get('capital_base', 0)
        injected_capital = account_data.get('injected_capital', 0)
        fixed_trade_amount = account_data.get('fixed_trade_amount', 0)
        total_asset = account_data.get('total_asset', 0)
        total_pnl = account_data.get('total_pnl', 0)
        total_pnl_pct = account_data.get('total_pnl_pct', 0)
        today_pnl = account_data.get('today_pnl', 0)

        # 持仓表
        pos_lines = []
        for p in positions:
            emoji = "📈" if p['unrealized_pnl'] >= 0 else "📉"
            pos_lines.append(
                f"> {emoji} {p['name']}({p['code']}): 成本¥{p.get('cost_amount', 0):,.0f} | "
                f"现价¥{p['current_price']:.2f} | 浮盈¥{p['unrealized_pnl']:+,.0f} ({p.get('position_pnl_pct', p['unrealized_pnl_pct']):+.2%})"
            )

        pos_text = "\n".join(pos_lines) if pos_lines else "当前空仓"

        # 今日成交
        trade_lines = []
        for t in trades:
            emoji = "🟢" if t['action'] == 'BUY' else "🔴"
            action = "买" if t['action'] == 'BUY' else ("卖半" if t['action'] == 'SELL_HALF' else "卖")
            trade_lines.append(
                f"> {emoji} {action} {t['name']} ¥{t['price']:.2f}x{t['shares']}"
            )
        trade_text = "\n".join(trade_lines) if trade_lines else "今日无成交"

        pnl_emoji = "🤑" if total_pnl >= 0 else "😭"
        today_emoji = "🎉" if today_pnl >= 0 else "⚠️"

        content = f"""{pnl_emoji} **{date_str} 模拟账户日报** {today_emoji}

**资金概况**
>累计股本: ¥{capital_base:,.2f}
>其中扩充: ¥{injected_capital:,.2f}
>总资产: ¥{total_asset:,.2f}
>可用现金: ¥{cash:,.2f}
>总账户盈亏: ¥{total_pnl:,.2f} ({total_pnl_pct:+.2%})
>今日盈亏: ¥{today_pnl:+.2f}
>单票固定买入额: ¥{fixed_trade_amount:,.2f}

**当前持仓（重点看个股盈亏比）** ({len(positions)}只)
{pos_text}

**今日成交** ({len(trades)}笔)
{trade_text}
"""
        self._send(content, "markdown")

    def send_market_open(self):
        """开盘提醒"""
        self._send("☕ **早！A股已开盘，小巴开始扫描市场...** 📈", "text")

    def send_market_close(self):
        """收盘提醒"""
        self._send("🌅 **收盘！今日交易结束，等待晚95报告...**", "text")
