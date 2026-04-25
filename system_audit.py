import os, re

base = '/home/agentuser/.hermes/astock-trader'
issues = []

# 1. 虚拟环境路径一致性
paths = {}
for f in os.listdir(base):
    if f.endswith('.py'):
        p = os.path.join(base, f)
        with open(p, 'r', encoding='utf-8') as fh:
            content = fh.read()
        for m in re.finditer(r"sys\.path\.insert\(0,\s*'([^']+)'\)", content):
            if 'site-packages' in m.group(1):
                paths.setdefault(m.group(1), []).append(f)
if len(paths) > 1:
    issues.append(f"⚠️ 虚拟环境路径不一致: {list(paths.keys())}")

# 2. notifier stdout
with open(os.path.join(base, 'notifier.py'), encoding='utf-8') as f:
    notifier = f.read()
if not ('print(content)' in notifier and 'if not self.webhook:' in notifier):
    issues.append('❌ notifier.py 缺少stdout输出机制')

# 3. ghost script
active = [f for f in os.listdir(base) if f.endswith('.sh') and not f.endswith('.DISABLED')]
if 'run_closing_validation.sh' in active:
    issues.append('⚠️ run_closing_validation.sh 仍然活跃! 会产生冲突信号')

# 4. stop loss protection
with open(os.path.join(base, 'strategy_evolver.py'), encoding='utf-8') as f:
    evolver = f.read()
if 'stop_loss' not in evolver or '-0.05' not in evolver:
    issues.append('⚠️ 策略进化器未显式固定 -5% 止损')

# 5. data cache
with open(os.path.join(base, 'data_feed.py'), encoding='utf-8') as f:
    data_feed = f.read()
if "self.cache['spot']" not in data_feed:
    issues.append('⚠️ get_stock_spot() 缺少60秒缓存')

# 6. 权重数学（兼容注释/额外空格）
tech_keys = ['ma_weight','volume_weight','breakout_weight','macd_weight','change_weight','turnover_score_weight']
fund_keys = ['fund_flow_weight','turnover_weight']
weights = {k:int(v) for k,v in re.findall(r"'([a-z_]+_weight)'\s*:\s*(\d+)", evolver)}
sector_match = re.search(r"'sector_bonus'\s*:\s*(\d+)", evolver)
sector = int(sector_match.group(1)) if sector_match else 0
tech_sum = sum(weights.get(k, 0) for k in tech_keys)
fund_sum = sum(weights.get(k, 0) for k in fund_keys)
if tech_sum + fund_sum + sector < 90:
    issues.append(f'⚠️ 权重总和偏低: 技术{tech_sum} + 资金{fund_sum} + 板块{sector} < 90')

# 7. 固定金额买入规则
with open(os.path.join(base, 'config.py'), encoding='utf-8') as f:
    cfg = f.read()
if 'FIXED_TRADE_AMOUNT = 100_000.0' not in cfg:
    issues.append('⚠️ 未检测到固定10万元买入规则')

print('发现问题:' if issues else '✅ 全部检查通过')
for i in issues:
    print('-', i)
