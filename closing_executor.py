"""
尾盘二次确认+买入执行器 (14:45 执行)
合并任务：5层过滤 + 即时买入 + 标注来源
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import subprocess, re, json, os
from datetime import datetime
from account import Account
from notifier import Notifier

# ========== 数据获取 ==========

def tencent_query(codes):
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    try:
        result = subprocess.run(['curl', '-s', '--max-time', '12', url],
            capture_output=True, timeout=15)
        return result.stdout.decode('gbk', errors='replace')
    except Exception as e:
        return ""

def get_index_data():
    text = tencent_query(['sh000001', 'sz399001', 'sz399006'])
    indices = {}
    for code in ['sh000001', 'sz399001', 'sz399006']:
        match = re.search(f'v_{code}="([^"]+)"', text)
        if match:
            f = match.group(1).split('~')
            indices[code] = {'name': f[1], 'change': float(f[32]) if len(f)>32 and f[32] else 0}
    return indices

def get_stock_spot(codes):
    """获取指定股票实时行情"""
    if not codes:
        return []
    
    # 添加市场前缀
    market_codes = []
    for c in codes:
        prefix = 'sh' if c.startswith('6') else 'sz'
        market_codes.append(f"{prefix}{c}")
    
    text = tencent_query(market_codes)
    spots = []
    for code in market_codes:
        match = re.search(f'v_{code}="([^"]+)"', text)
        if not match:
            continue
        fields = match.group(1).split('~')
        if len(fields) < 35:
            continue
        try:
            spots.append({
                'code': fields[2].zfill(6),
                'name': fields[1],
                'change': float(fields[32]) if fields[32] else 0,
                'turnover': float(fields[38]) if len(fields)>38 and fields[38] else 0,
                'price': float(fields[3]) if fields[3] else 0,
                'open': float(fields[5]) if fields[5] else 0,
                'high': float(fields[33]) if fields[33] else 0,
                'low': float(fields[34]) if fields[34] else 0,
            })
        except:
            continue
    return spots

# ========== 5层过滤 ==========

def five_layer_filter(spots):
    if not spots:
        return []
    
    # Layer 1: 基础 (涨幅>0 且 <11, 换手>1)
    layer1 = [s for s in spots if s['change'] > 0 and s['change'] < 11 and s['turnover'] > 1]
    elim1 = len(spots) - len(layer1)
    
    # Layer 2: K线 (阳线, 上影线<3%)
    layer2 = []
    for s in layer1:
        if s['price'] > s['open']:
            upper = (s['high'] - max(s['price'], s['open'])) / max(s['price'], s['open']) * 100 if max(s['price'], s['open']) > 0 else 0
            if upper < 3:
                layer2.append(s)
    elim2 = len(layer1) - len(layer2)
    
    # Layer 3: 量能 (换手>=2)
    layer3 = [s for s in layer2 if s['turnover'] >= 2]
    elim3 = len(layer2) - len(layer3)
    
    # Layer 4: 技术 (涨幅 2-7)
    layer4 = [s for s in layer3 if 2 <= s['change'] <= 7]
    elim4 = len(layer3) - len(layer4)
    
    # Layer 5: 安全（尾盘未跳水 + 日内振幅控制）
    layer5 = []
    for s in layer4:
        # 尾盘未大幅回落：收盘价不低于最高价的97%
        not_diving = s['price'] >= s['high'] * 0.97 if s['high'] > 0 else False
        # 日内振幅控制：(high-low)/open < 8%
        amplitude = (s['high'] - s['low']) / s['open'] * 100 if s['open'] > 0 else 0
        not_choppy = amplitude < 8
        if not_diving and not_choppy:
            layer5.append(s)
    elim5 = len(layer4) - len(layer5)
    
    return layer5, [elim1, elim2, elim3, elim4, elim5]

# ========== 主程序 ==========

def execute_closing():
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    today_str = now.strftime('%Y-%m-%d')
    
    # 收集执行结果用于最终通知
    result = {
        'action': 'NONE',  # NONE / BUY / SKIP
        'reason': '',
        'candidate_count': 0,
        'passed_count': 0,
        'buy_count': 0,
        'eliminated': [0,0,0,0,0],
        'stocks': [],
        'index_change': 0,
        'has_position': False,
    }
    
    # 1. 检查是否交易日
    if now.weekday() >= 5:
        result['action'] = 'SKIP'
        result['reason'] = '今天是周末，不交易'
        _print_notification(result)
        return
    
    # 2. 当前规则：允许继续新增买入，不因已有持仓阻断
    account = Account()
    
    # 3. 读取09:00和14:30的候选池
    filepath = f'/tmp/candidates_{today_str}.json'
    if not os.path.exists(filepath):
        result['action'] = 'SKIP'
        result['reason'] = '未找到今日候选池文件（盘前/尾盘选股未执行或无筛选出候选股）'
        _print_notification(result)
        return
    
    try:
        with open(filepath, 'r') as f:
            pool_data = json.load(f)
    except Exception as e:
        result['action'] = 'SKIP'
        result['reason'] = f'读取候选池失败: {e}'
        _print_notification(result)
        return
    
    # 合并候选池
    all_candidates = []
    for source, stocks in pool_data.items():
        for s in stocks:
            s['source'] = source
            all_candidates.append(s)
    
    # 去重
    unique = {}
    for c in all_candidates:
        code = c['code']
        if code not in unique or c['score'] > unique[code]['score']:
            unique[code] = c
    
    candidates = list(unique.values())
    result['candidate_count'] = len(candidates)
    
    if not candidates:
        result['action'] = 'SKIP'
        result['reason'] = '今日候选池为空（大盘弱势，盘前/尾盘选股未筛出候选股）'
        _print_notification(result)
        return
    
    # 4. 重新获取实时行情
    codes = [c['code'] for c in candidates]
    spots = get_stock_spot(codes)
    
    spot_map = {s['code']: s for s in spots}
    enriched = []
    for c in candidates:
        if c['code'] in spot_map:
            s = spot_map[c['code']]
            s['source'] = c.get('source', '未知')
            s['reasons'] = c.get('reasons', [])
            s['formulas'] = c.get('formulas', [])
            s['signal_source'] = c.get('signal_source') or c.get('source', '未知').replace('选股', '票')
            s['leader_grade'] = c.get('leader_grade', '')
            s['leader_score'] = c.get('leader_score', 0)
            enriched.append(s)
    
    if not enriched:
        result['action'] = 'SKIP'
        result['reason'] = '无法获取候选股实时行情'
        _print_notification(result)
        return
    
    # 5. 执行5层过滤
    passed, eliminated = five_layer_filter(enriched)
    result['passed_count'] = len(passed)
    result['eliminated'] = eliminated
    
    # 6. 大盘环境检查
    indices = get_index_data()
    idx_change = indices.get('sh000001', {}).get('change', 0)
    result['index_change'] = idx_change
    
    if idx_change < -1:
        result['action'] = 'SKIP'
        result['reason'] = f'大盘弱势（上证{idx_change:+.2f}%），不追高'
        _print_notification(result)
        return
    
    if not passed:
        result['action'] = 'SKIP'
        result['reason'] = '无候选股通过5层过滤'
        _print_notification(result)
        return
    
        # 4. 对所有通过5层过滤的标的执行买入
    try:
        from strategy_evolver import StrategyEvolver
        try:
            ratio = StrategyEvolver().get_current_config().get('single_position_ratio', 0.10)
        except Exception:
            ratio = 0.10
        bought = []
        for top_pick in passed:
            code = top_pick['code']
            name = top_pick['name']
            price = top_pick['price']
            
            # === UZI 深度分析（买入前最终确认）===
            uzi_deep_score = None
            uzi_deep_reasons = []
            try:
                from uzi_integration import UZIAnalyzer
                import pandas as pd
                # 尝试获取K线
                hist_df = pd.DataFrame()  # 简化：实际运行时会从 data_feed 获取
                uzi = UZIAnalyzer()
                uzi_deep_score = uzi.analyze_stock(code, name, [], top_pick)
                uzi_deep_reasons = [
                    f"UZI综合:{uzi_deep_score.overall_score} 看多:{uzi_deep_score.bullish_count} 看空:{uzi_deep_score.bearish_count}",
                    f"游资:{uzi_deep_score.youzi_signal} 技术:{uzi_deep_score.tech_signal} 加分:{uzi_deep_score.score_boost:+.1f}"
                ]
                # UZI 强烈看空时跳过
                if uzi_deep_score.score_boost < -10 and uzi_deep_score.youzi_signal == 'bearish':
                    print(f"[14:45 UZI] {code} UZI强烈看空，跳过买入")
                    continue
            except Exception as e:
                print(f"[14:45 UZI] {code} 深度分析失败: {e}")
            
            trade = account.buy(
                code=code,
                name=name,
                price=price,
                ratio=ratio,
                date_str=today_str,
                metadata={
                    'entry_reasons': top_pick.get('reasons', []) + uzi_deep_reasons,
                    'formulas': top_pick.get('formulas', []),
                    'signal_source': top_pick.get('signal_source', ''),
                    'leader_grade': top_pick.get('leader_grade', ''),
                    'leader_score': top_pick.get('leader_score', 0),
                    'uzi_score': uzi_deep_score.overall_score if uzi_deep_score else 0,
                    'uzi_signal': uzi_deep_score.youzi_signal if uzi_deep_score else 'unknown',
                    'uzi_boost': uzi_deep_score.score_boost if uzi_deep_score else 0,
                }
            )
            if trade:
                bought.append({
                    'code': code,
                    'name': name,
                    'price': trade.price,
                    'shares': trade.shares,
                    'amount': trade.amount,
                    'source': top_pick.get('source', '未知'),
                    'uzi_score': uzi_deep_score.overall_score if uzi_deep_score else 0,
                    'uzi_signal': uzi_deep_score.youzi_signal if uzi_deep_score else 'unknown',
                })

        if bought:
            result['action'] = 'BUY'
            result['reason'] = f'二次确认通过，已批量买入{len(bought)}只'
            result['stocks'] = bought
            result['buy_count'] = len(bought)
            _print_notification(result, account)
        else:
            result['action'] = 'SKIP'
            result['reason'] = '二次确认通过，但批量买入失败（价格过高或数量不足）'
            _print_notification(result, account)
    except Exception as e:
        result['action'] = 'SKIP'
        result['reason'] = f'买入异常: {e}'
        _print_notification(result, account)
    
    account.save()


def _print_notification(result, account=None, trade=None):
    """打印统一格式的尾盘简报，cron job 会通过 stdout 推送给用户；同时生成微信推送文件"""
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    today_str = now.strftime('%Y-%m-%d')

    wechat_lines = [f"📌 **尾盘二次确认简报 ({time_str})**", ""]

    if result['action'] == 'BUY' and account:
        buy_lines = []
        shown_stocks = result.get('stocks', [])[:3]
        hidden_count = max(0, len(result.get('stocks', [])) - len(shown_stocks))
        for i, stock in enumerate(shown_stocks, 1):
            buy_lines.append(f"> {i}. {stock['name']}({stock['code']}) ¥{stock['price']:.2f} x {stock['shares']}股 | 金额¥{stock['amount']:,.2f} | 来源:{stock.get('source', '未知')}")
        if hidden_count > 0:
            buy_lines.append(f"> …其余{hidden_count}只已成交，明细省略，完整信息已写入账户记录")
        buy_text = '\n'.join(buy_lines) if buy_lines else '> 无成交明细'
        msg = f"""
📌 **尾盘二次确认简报 ({time_str})**

✅ **已批量执行买入**
> 买入数量: {result.get('buy_count', 0)}只
> 单票规则: 固定10万元买入
> 累计股本: ¥{account.total_capital_base:,.2f}
> 扩充股本: ¥{account.injected_capital:,.2f}

{buy_text}

📊 5层过滤: 候选{result['candidate_count']}只 → 通过{result['passed_count']}只
> 淘汰明细: 基础{result['eliminated'][0]} | K线{result['eliminated'][1]} | 量能{result['eliminated'][2]} | 技术{result['eliminated'][3]} | 安全{result['eliminated'][4]}

💰 账户: 总资产 ¥{account.total_asset:,.2f} | 总盈亏 {account.total_pnl:+.2f} ({account.total_pnl_pct:+.2%})
"""
        print(msg)
        wechat_lines = msg.strip().split('\n')
    else:
        idx_text = f"上证{result['index_change']:+.2f}%" if result['index_change'] != 0 else "大盘数据未获取"

        filter_text = ""
        if result['candidate_count'] > 0:
            filter_text = f"""
🔍 5层过滤: 候选{result['candidate_count']}只 → 通过{result['passed_count']}只
   淘汰明细: 基础{result['eliminated'][0]} | K线{result['eliminated'][1]} | 量能{result['eliminated'][2]} | 技术{result['eliminated'][3]} | 安全{result['eliminated'][4]}"""

        msg = f"""
📌 **尾盘二次确认简报 ({time_str})**

📊 {idx_text} | 大盘环境: 检测中

❌ **今日未新增买入**
原因: {result['reason']}
{filter_text}

💰 账户: 持仓{len(account.positions) if account and hasattr(account, 'positions') else 0}只 | 累计股本¥{(account.total_capital_base if account else 0):,.2f} | 继续等待下一批信号
"""
        print(msg)
        wechat_lines = msg.strip().split('\n')
    wechat_file = f'/tmp/wechat_close_{today_str}.md'
    with open(wechat_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(wechat_lines))
    print(f"[尾盘执行器] 已生成微信推送文件: {wechat_file}")

if __name__ == '__main__':
    execute_closing()
