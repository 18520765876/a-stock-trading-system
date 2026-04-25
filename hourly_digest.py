#!/usr/bin/env python3
"""
A股模拟交易系统 - 每小时扫描汇总
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

from datetime import datetime
from data_feed import DataFeed
from strategy import Strategy
from strategy_evolver import StrategyEvolver
from account import Account

def market_score(sentiment):
    """大盘环境评分 0-3"""
    up_ratio = sentiment.get('up_ratio', 0.5)
    limit_up = sentiment.get('limit_up', 0)
    limit_down = sentiment.get('limit_down', 0)
    
    if limit_down > 30 or up_ratio < 0.25:
        return 0, "恐慌模式"
    if up_ratio < 0.40 or limit_down > 10:
        return 1, "防守模式"
    if up_ratio < 0.55:
        return 2, "震荡模式"
    return 3, "进攻模式"

def categorize_signals(signals):
    """按公式类型和龙头评级归类信号"""
    categories = {}
    leader_count = {'🏆 真龙级': 0, '⭐ 强势龙头': 0, '🟡 潜力龙头': 0}
    
    for sig in signals:
        # 公式统计
        if sig.formulas:
            for f in sig.formulas:
                categories[f] = categories.get(f, 0) + 1
        else:
            # 从 reasons 推断回退
            reasons_text = ' '.join(sig.reasons)
            cat = "综合评分"
            if "突破" in reasons_text or "新高" in reasons_text:
                cat = "箱体突破"
            elif "回踩" in reasons_text or "支撑" in reasons_text:
                cat = "回踩共振"
            elif "金叉" in reasons_text or "MACD" in reasons_text:
                cat = "MACD金叉"
            elif "量能" in reasons_text or "量比" in reasons_text:
                cat = "量能突破"
            elif "均线多头" in reasons_text:
                cat = "均线多头"
            elif "主力" in reasons_text:
                cat = "资金流入"
            categories[cat] = categories.get(cat, 0) + 1
        
        # 龙头统计
        if sig.leader_grade:
            leader_count[sig.leader_grade] = leader_count.get(sig.leader_grade, 0) + 1
    
    return categories, leader_count

def summarize_top_items(items_dict, limit=3):
    """压缩展示 TopN 项，避免推送过长"""
    ranked = sorted(items_dict.items(), key=lambda x: -x[1])
    shown = ranked[:limit]
    summary = [f"{name}({count}只)" for name, count in shown]
    remaining = len(ranked) - len(shown)
    if remaining > 0:
        summary.append(f"其余{remaining}类")
    return ' | '.join(summary)

def main():
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    
    feed = DataFeed()
    sentiment = feed.get_market_sentiment()
    score, mode = market_score(sentiment)
    
    evolver = StrategyEvolver()
    strategy = Strategy(evolver)
    
    # 扫描买入候选
    buy_signals = strategy.scan_buy_candidates(max_candidates=10)
    
    # 检查持仓卖出信号
    account = Account()
    sell_signals = []
    if account.positions:
        spot_df = feed.get_stock_spot()
        price_map = {}
        for code in account.positions:
            match = spot_df[spot_df['代码'] == code]
            if not match.empty:
                price_map[code] = float(match.iloc[0]['最新价'])
        account.update_prices(price_map)
        positions = account.get_position_summary()
        sell_signals = strategy.check_sell_signals(positions, price_map)
    
    # 汇总
    total_signals = len(buy_signals) + len(sell_signals)
    
    print(f"📊 【{time_str} 扫描摘要】")
    print(f"大盘环境：{score}分（{mode}）")
    
    if total_signals == 0:
        if score <= 1:
            print(f"无触发信号，继续空仓观察。")
        else:
            print(f"无触发信号，继续观察。")
    else:
        # 活跃公式统计
        all_signals = buy_signals + sell_signals
        categories, leader_count = categorize_signals(all_signals)
        
        # 构建公式统计行
        formula_parts = []
        for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:3]:
            formula_parts.append(f"{cat}({count}只)")
        if len(categories) > 3:
            formula_parts.append(f"其余{len(categories)-3}类")
        
        if formula_parts:
            print(f"活跃公式：{' | '.join(formula_parts)}")
        else:
            print(f"活跃公式：综合评分({total_signals}只)")
        
        # 龙头统计（如有）
        leader_parts = []
        for grade, count in leader_count.items():
            if count > 0:
                leader_parts.append(f"{grade}({count})")
        if leader_parts:
            print(f"龙头评级：{' | '.join(leader_parts)}")
        
        # 候选池（最多3只）
        candidates = [s.code for s in all_signals[:3]]
        if candidates:
            suffix = f" 等{len(all_signals)}只" if len(all_signals) > 3 else ""
            print(f"候选池：{'、'.join(candidates)}{suffix}")
    
    print("─────────────────────")
    
    # 15:00 收盘附加全天总结
    if time_str >= "15:00":
        print(f"\n📋 【全天总结】")
        print(f"今日涨跌比：{sentiment.get('up_ratio', 0):.1%}")
        print(f"涨停家数：{sentiment.get('limit_up', 0)} | 跌停家数：{sentiment.get('limit_down', 0)}")
        print(f"账户总资产：¥{account.total_asset:,.2f}")
        print(f"当日盈亏：¥{account.total_pnl:+.2f} ({account.total_pnl_pct:+.2%})")
        
        # 公式触发统计
        all_signals = buy_signals + sell_signals
        if all_signals:
            cats, leaders = categorize_signals(all_signals)
            if cats:
                cat_str = summarize_top_items(cats, limit=3)
                print(f"公式触发：{cat_str}")
            
            # 龙头级标总结
            true_dragons = sum(1 for s in all_signals if s.leader_grade == '🏆 真龙级')
            strong_leaders = sum(1 for s in all_signals if s.leader_grade == '⭐ 强势龙头')
            if true_dragons > 0 or strong_leaders > 0:
                print(f"龙头级标：🏆真龙{true_dragons}只 | ⭐强势{strong_leaders}只")
        
        if score >= 2:
            print(f"\n📝 次日策略：市场氛围尚可，维持正常仓位运作，关注早盘量能。")
        elif score == 1:
            print(f"\n📝 次日策略：市场偏弱，控制仓位在半仓以下，优选防御板块。")
        else:
            print(f"\n📝 次日策略：市场恐慌，建议空仓或极轻仓观望，等待情绪修复。")

if __name__ == "__main__":
    main()
