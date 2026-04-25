"""
收盘简报 (15:00 推送)
总结当日市场情况和持仓状态
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

from datetime import datetime

def generate_brief():
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    date_str = now.strftime('%m-%d')
    
    # 读取账户状态
    try:
        from account import Account
        account = Account()
        positions = account.get_position_summary()
        cash = account.cash
        total_asset = account.total_asset
        total_pnl = account.total_pnl
        total_pnl_pct = account.total_pnl_pct
    except:
        positions = []
        cash = 1000000
        total_asset = 1000000
        total_pnl = 0
        total_pnl_pct = 0
    
    # 持仓摘要
    pos_lines = []
    for p in positions:
        emoji = "📈" if p['unrealized_pnl'] >= 0 else "📉"
        pos_lines.append(
            f"> {emoji} {p['name']}({p['code']}): "
            f"{p['shares']}股 ¥{p['current_price']:.2f} "
            f"浮盈{p['unrealized_pnl']:+.0f}({p['unrealized_pnl_pct']:+.2%})"
        )
    
    pos_text = "\n".join(pos_lines) if pos_lines else "> 当前空仓"
    
    pnl_emoji = "🤑" if total_pnl >= 0 else "😭"
    
    brief = f"""
🌅 **{date_str} 收盘简报 ({time_str})**

{pnl_emoji} 账户概况
> 总资产: ¥{total_asset:,.2f}
> 可用现金: ¥{cash:,.2f}
> 累计盈亏: ¥{total_pnl:,.2f} ({total_pnl_pct:+.2%})

**当前持仓** ({len(positions)}只)
{pos_text}

今日交易结束，20:00推送详细日报。
"""
    
    print(brief)

if __name__ == '__main__':
    generate_brief()
