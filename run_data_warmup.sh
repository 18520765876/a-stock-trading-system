#!/bin/bash
# 09:15 数据预热任务 - 预先加载股票列表和缓存
cd /home/agentuser/.hermes/astock-trader
source /home/agentuser/.venv/astock/bin/activate

python -c "
import sys
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')
from data_feed import DataFeed

print('[09:15 预热] 开始数据预加载...')
feed = DataFeed()

# 预加载股票列表
count = len(feed.stock_list)
print(f'[09:15 预热] 股票列表已加载: {count} 只')

# 预热指数数据
try:
    text = feed._tencent_query(['sh000001', 'sz399001', 'sz399006'])
    print('[09:15 预热] 指数数据预加载完成' if text else '[09:15 预热] 指数数据返回为空')
except Exception as e:
    print(f'[09:15 预热] 指数预热异常: {e}')

print('[09:15 预热] 完成，等待 09:30 开盘简报...')
"
