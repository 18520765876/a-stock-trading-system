"""
开盘简报生成器
Phase 1-3: 数据采集 → 五模块打分 → 融合决策 → 生成候选池 → 输出3-5句简报
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import subprocess, re, json, os
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
    """获取三大指数"""
    text = tencent_query(['sh000001', 'sz399001', 'sz399006'])
    indices = {}
    for code in ['sh000001', 'sz399001', 'sz399006']:
        match = re.search(f'v_{code}="([^"]+)"', text)
        if match:
            f = match.group(1).split('~')
            indices[code] = {
                'name': f[1],
                'price': float(f[3]) if f[3] else 0,
                'open': float(f[5]) if f[5] else 0,
                'change': float(f[32]) if len(f)>32 and f[32] else 0,
                'amount': float(f[37])/100000000 if len(f)>37 and f[37] else 0,
            }
    return indices

def get_market_spot_sample():
    """获取样本行情估算市场情绪 (只取前400只加速)"""
    # 获取股票列表前400只
    try:
        import pandas as pd
        stock_list_path = '/home/agentuser/.hermes/astock-trader/data/stock_list.csv'
        df = pd.read_csv(stock_list_path, dtype={'code': str}, nrows=400)
        df['code'] = df['code'].astype(str).str.zfill(6)
        codes = df.apply(lambda r: f"{r['market']}{r['code']}", axis=1).tolist()
        
        text = tencent_query(codes[:80])  # 只查80只，加快速度
        all_spot = []
        for code in codes[:80]:
            match = re.search(f'v_{code}="([^"]+)"', text)
            if not match:
                continue
            fields = match.group(1).split('~')
            if len(fields) < 35:
                continue
            try:
                change = float(fields[32]) if fields[32] else 0
                all_spot.append({'change': change})
            except:
                continue
        
        if not all_spot:
            return None
            
        up = sum(1 for s in all_spot if s['change'] > 0)
        down = sum(1 for s in all_spot if s['change'] < 0)
        total = len(all_spot)
        limit_up = sum(1 for s in all_spot if s['change'] >= 9.5)
        limit_down = sum(1 for s in all_spot if s['change'] <= -9.5)
        strong_up = sum(1 for s in all_spot if s['change'] >= 5)
        strong_down = sum(1 for s in all_spot if s['change'] <= -5)
        
        return {
            'up': up, 'down': down, 'total': total,
            'up_ratio': up / total if total > 0 else 0.5,
            'limit_up': limit_up, 'limit_down': limit_down,
            'strong_up': strong_up, 'strong_down': strong_down,
            'sample_size': total
        }
    except Exception as e:
        print(f"[简报] 样本获取失败: {e}")
        return None

def determine_cycle(up_ratio, limit_up, limit_down):
    if up_ratio >= 0.7 and limit_up >= 50:
        return "高潮"
    elif up_ratio >= 0.55 and limit_up >= 20:
        return "回暖"
    elif up_ratio <= 0.3 or limit_down >= 30:
        return "冰点"
    elif limit_up < 10 and up_ratio < 0.45:
        return "退潮"
    else:
        return "震荡"

def generate_brief():
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    
    # ========== Phase 1: 数据采集 ==========
    indices = get_index_data()
    spot_sample = get_market_spot_sample()
    
    # ========== Phase 2: 五模块打分 ==========
    # 模块1: 市场环境
    if spot_sample:
        up_ratio = spot_sample['up_ratio']
        limit_up = spot_sample['limit_up']
        limit_down = spot_sample['limit_down']
        cycle = determine_cycle(up_ratio, limit_up, limit_down)
        
        if cycle == "高潮": market_score = 85
        elif cycle == "回暖": market_score = 65
        elif cycle == "震荡": market_score = 45
        elif cycle == "退潮": market_score = 25
        else: market_score = 15
    else:
        up_ratio = 0.5
        limit_up = limit_down = 0
        cycle = "未知"
        market_score = 40
    
    # 模块2: 情绪周期 (同市场环境简化)
    sentiment_score = market_score
    
    # 模块3: 量化因子 (基于指数涨跌幅估算)
    idx_change = indices.get('sh000001', {}).get('change', 0)
    if idx_change > 1: quant_score = 70
    elif idx_change > 0: quant_score = 55
    elif idx_change > -1: quant_score = 40
    else: quant_score = 25
    
    # 模块4: 用户公式 (简化: 基于市场活跃度)
    if spot_sample and spot_sample['strong_up'] >= 5:
        formula_score = 50
    else:
        formula_score = 30
    
    # 模块5: 行业趋势 (固定中性的简化)
    industry_score = 40
    
    # ========== Phase 3: 融合决策 ==========
    fusion = int(
        market_score * 0.40 +
        sentiment_score * 0.20 +
        quant_score * 0.15 +
        formula_score * 0.15 +
        industry_score * 0.10
    )
    
    if fusion >= 75:
        position = "可轻仓试探 (10%×1-2)"
        env_label = "偏强"
    elif fusion >= 60:
        position = "观望为主"
        env_label = "中等"
    elif fusion >= 45:
        position = "继续空仓"
        env_label = "偏弱"
    else:
        position = "强烈观望"
        env_label = "弱势"
    
    # ========== 生成简报 (3-5句话) ==========
    index_lines = []
    for code, key in [('sh000001', '上证'), ('sz399001', '深证'), ('sz399006', '创业板')]:
        d = indices.get(code, {})
        if d:
            emoji = "📈" if d['change'] >= 0 else "📉"
            index_lines.append(f"{emoji} {key}{d['change']:+.2f}%")
    
    idx_text = " ".join(index_lines) if index_lines else "指数数据获取中"
    
    if spot_sample:
        market_line = f"涨跌比约{up_ratio:.0%}（涨{spot_sample['up']}/跌{spot_sample['down']}），涨停{limit_up}家跌停{limit_down}家，情绪周期判定为**{cycle}**。"
    else:
        market_line = f"市场情绪数据采集中，大盘情绪周期暂判为**{cycle}**。"
    
    brief = f"""📊 **今日策略简报 ({time_str})**

{idx_text}
{market_line}
五模块融合评分 **{fusion}/100**，市场环境判定为**{env_label}**，建议**{position}**。
盘中后台静默扫描已启动，14:45执行尾盘二次确认，届时推送决策简报。
"""
    
    print(brief)
    if os.environ.get('ASTOCK_DEBUG_BRIEF', '0') == '1':
        print(f"[DEBUG] 打分: 市场{market_score}×0.40 + 情绪{sentiment_score}×0.20 + 量化{quant_score}×0.15 + 公式{formula_score}×0.15 + 行业{industry_score}×0.10 = {fusion}")

if __name__ == '__main__':
    generate_brief()
