"""
从腾讯接口构建A股全市场股票列表
保存为 data/stock_list.csv
"""
import subprocess
import re
import csv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

def query_batch(codes):
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '8', url],
            capture_output=True, timeout=10
        )
        text = result.stdout.decode('gbk', errors='replace')
        return text
    except:
        return ""

def parse_stock(text, code):
    pattern = f'v_{code}="([^"]+)"'
    match = re.search(pattern, text)
    if not match:
        return None
    fields = match.group(1).split('~')
    if len(fields) < 3 or not fields[2]:
        return None
    return {
        'code': fields[2],
        'name': fields[1],
        'market': 'sh' if code.startswith('sh') else 'sz'
    }

# 生成所有可能的代码
ranges = []
# 沪市主板
ranges.extend([f"sh{i}" for i in range(600000, 610000, 1)])
ranges.extend([f"sh{i}" for i in range(601000, 602000, 1)])
ranges.extend([f"sh{i}" for i in range(603000, 604000, 1)])
ranges.extend([f"sh{i}" for i in range(605000, 606000, 1)])
# 深市主板
ranges.extend([f"sz{i:06d}" for i in range(1, 10000, 1)])
# 创业板
ranges.extend([f"sz{i}" for i in range(300000, 302000, 1)])
# 科创板
ranges.extend([f"sh{i}" for i in range(688000, 690000, 1)])
# 北交所
ranges.extend([f"bj{i}" for i in range(430000, 431000, 1)])
ranges.extend([f"bj{i}" for i in range(830000, 840000, 1)])
ranges.extend([f"bj{i}" for i in range(870000, 900000, 1)])
ranges.extend([f"bj{i}" for i in range(920000, 921000, 1)])

print(f"Total codes to check: {len(ranges)}")

# 分批查询，每批60只
BATCH_SIZE = 60
all_codes = []
batches = [ranges[i:i+BATCH_SIZE] for i in range(0, len(ranges), BATCH_SIZE)]

for idx, batch in enumerate(batches):
    text = query_batch(batch)
    for code in batch:
        stock = parse_stock(text, code)
        if stock:
            all_codes.append(stock)
    if (idx + 1) % 50 == 0:
        print(f"Progress: {idx+1}/{len(batches)} batches, found {len(all_codes)} stocks")

print(f"\nDone! Total valid stocks: {len(all_codes)}")

# 保存
output_path = os.path.expanduser('~/.hermes/astock-trader/data/stock_list.csv')
with open(output_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['code', 'name', 'market'])
    writer.writeheader()
    writer.writerows(all_codes)

print(f"Saved to {output_path}")
