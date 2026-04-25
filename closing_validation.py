"""
尾盘二次确认 (14:45 执行)
5层过滤：基础 / K线 / 量能 / 技术 / 安全
输出：买/不买 决策简报
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import subprocess, re, json
from datetime import datetime

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
            indices[code] = {
                'name': f[1],
                'change': float(f[32]) if len(f)>32 and f[32] else 0,
            }
    return indices

def get_spot_sample():
    try:
        import pandas as pd
        stock_list_path = '/home/agentuser/.hermes/astock-trader/data/stock_list.csv'
        df = pd.read_csv(stock_list_path, dtype={'code': str}, nrows=400)
        df['code'] = df['code'].astype(str).str.zfill(6)
        codes = df.apply(lambda r: f"{r['market']}{r['code']}", axis=1).tolist()[:80]
        text = tencent_query(codes)
        all_spot = []
        for code in codes:
            match = re.search(f'v_{code}="([^"]+)"', text)
            if not match: continue
            fields = match.group(1).split('~')
            if len(fields) < 35: continue
            try:
                all_spot.append({
                    'code': fields[2].zfill(6),
                    'name': fields[1],
                    'change': float(fields[32]) if fields[32] else 0,
                    'turnover': float(fields[38]) if len(fields)>38 and fields[38] else 0,
                    'price': float(fields[3]) if fields[3] else 0,
                    'open': float(fields[5]) if fields[5] else 0,
                    'high': float(fields[33]) if fields[33] else 0,
                    'low': float(fields[34]) if fields[34] else 0,
                })
            except: continue
        return all_spot
    except Exception as e:
        print(f"[尾盘] 样本获取失败: {e}")
        return []

def five_layer_filter(spot_sample):
    """5层过滤，返回通过的股票和每层淘汰数"""
    if not spot_sample:
        return [], [0,0,0,0,0]
    
    # Layer 1: 基础过滤 (排除ST、涨跌幅异常)
    layer1 = [s for s in spot_sample 
              if s['change'] > 0 and s['change'] < 11 and s['turnover'] > 1]
    eliminated_1 = len(spot_sample) - len(layer1)
    
    # Layer 2: K线形态 (阳线、未长上影)
    layer2 = []
    for s in layer1:
        if s['price'] > s['open']:  # 阳线
            upper_shadow = (s['high'] - max(s['price'], s['open'])) / max(s['price'], s['open']) * 100 if max(s['price'], s['open']) > 0 else 0
            if upper_shadow < 3:  # 上影线<3%
                layer2.append(s)
    eliminated_2 = len(layer1) - len(layer2)
    
    # Layer 3: 量能 (换手率>2%)
    layer3 = [s for s in layer2 if s['turnover'] >= 2]
    eliminated_3 = len(layer2) - len(layer3)
    
    # Layer 4: 技术 (涨幅适中 2%-7%，不过高)
    layer4 = [s for s in layer3 if 2 <= s['change'] <= 7]
    eliminated_4 = len(layer3) - len(layer4)
    
    # Layer 5: 安全 (尾盘未大幅回落)
    layer5 = []
    for s in layer4:
        pullback = (s['high'] - s['price']) / s['high'] * 100 if s['high'] > 0 else 0
        if pullback < 3:  # 从最高点回落<3%
            layer5.append(s)
    eliminated_5 = len(layer4) - len(layer5)
    
    return layer5, [eliminated_1, eliminated_2, eliminated_3, eliminated_4, eliminated_5]

def generate_closing_brief():
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    
    # 获取数据
    indices = get_index_data()
    spot_sample = get_spot_sample()
    candidates, eliminated = five_layer_filter(spot_sample)
    
    # 大盘情绪
    idx_change = indices.get('sh000001', {}).get('change', 0)
    if idx_change > 1: market_env = "偏强"
    elif idx_change > 0: market_env = "中性偏强"
    elif idx_change > -1: market_env = "中性偏弱"
    else: market_env = "弱势"
    
    # 总样本和通过率
    total_sample = len(spot_sample)
    passed = len(candidates)
    pass_rate = passed / total_sample * 100 if total_sample > 0 else 0
    
    # 决策
    if market_env in ["弱势"] and passed == 0:
        decision = "❌ 不买"
        reason = "大盘弱势且无候选股通过5层过滤"
    elif market_env in ["弱势"] and passed > 0:
        decision = "⚠️ 观望"
        reason = f"大盘弱势，虽有{passed}只通过过滤，建议不追"
    elif passed == 0:
        decision = "❌ 不买"
        reason = "无候选股通过5层过滤"
    elif passed >= 1 and passed <= 3:
        decision = "✅ 可买"
        reason = f"{passed}只通过5层过滤，可轻仓试"
    else:
        decision = "✅ 可买"
        reason = f"{passed}只通过5层过滤，择优而入"
    
    # 候选股列表
    candidate_lines = []
    for c in candidates[:3]:
        candidate_lines.append(f"> {c['name']}({c['code']}) +{c['change']:.1f}% 换手{c['turnover']:.1f}%")
    candidate_text = "\n".join(candidate_lines) if candidate_lines else "> 无"
    
    brief = f"""
📋 **尾盘二次确认简报 ({time_str})**

📉 上证{idx_change:+.2f}%  大盘环境：**{market_env}**

**5层过滤结果** ({total_sample}只样本)
- 基础层：淘汰{eliminated[0]}只 → 剩余{total_sample-eliminated[0]}只
- K线层：淘汰{eliminated[1]}只 → 剩余{len(spot_sample)-eliminated[0]-eliminated[1] if spot_sample else 0}只
- 量能层：淘汰{eliminated[2]}只 → 剩余{len(spot_sample)-sum(eliminated[:3]) if spot_sample else 0}只
- 技术层：淘汰{eliminated[3]}只 → 剩余{len(spot_sample)-sum(eliminated[:4]) if spot_sample else 0}只
- 安全层：淘汰{eliminated[4]}只 → **最终通过{passed}只**

**决策：{decision}**
{reason}

**候选池：**
{candidate_text}

{('14:50-15:00 执行挂单买入' if decision.startswith('✅') else '今日空仓观望，等待明天')}
"""
    
    print(brief)

if __name__ == '__main__':
    generate_closing_brief()
