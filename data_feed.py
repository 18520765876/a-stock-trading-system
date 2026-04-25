"""
A股数据获取模块 (腾讯财经接口版)
适用于国外服务器环境
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import subprocess
import pandas as pd
import numpy as np
import re
import json
import os
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============ 配置 ============
STOCK_LIST_PATH = os.path.expanduser('~/.hermes/astock-trader/data/stock_list.csv')
DATA_CACHE_DIR = os.path.expanduser('~/.hermes/astock-trader/data')

class DataFeed:
    def __init__(self):
        self.stock_list = self._load_stock_list()
        self.cache = {}
        self.verbose = os.environ.get('ASTOCK_VERBOSE', '0') == '1'

    def _log(self, message: str):
        if self.verbose:
            print(message)

    def _load_stock_list(self) -> pd.DataFrame:
        """加载股票列表"""
        if os.path.exists(STOCK_LIST_PATH):
            df = pd.read_csv(STOCK_LIST_PATH, dtype={'code': str})
            df['code'] = df['code'].astype(str).str.zfill(6)
            return df
        else:
            # 如果列表还没生成，先用一个小测试列表
            self._log("[DataFeed] 股票列表不存在，使用默认测试列表")
            return pd.DataFrame({
                'code': ['600519', '000858', '000001', '600036', '002594', 
                        '300750', '601318', '600900', '000333', '002415',
                        '600276', '601012', '002230', '300059', '600030'],
                'name': ['茅台', '五粮液', '平安', '招行', '比亚迪',
                        '宁德', '平安', '长江', '格力', '海康',
                        '恒瑞', '隆基', '讯飞', '东财', '中信'],
                'market': ['sh', 'sz', 'sz', 'sh', 'sz', 'sz', 'sh', 'sh', 'sz', 'sz',
                          'sh', 'sh', 'sz', 'sz', 'sh']
            })

    def _tencent_query(self, codes: List[str]) -> str:
        """通过curl调用腾讯接口"""
        if not codes:
            return ""
        url = f"https://qt.gtimg.cn/q={','.join(codes)}"
        try:
            result = subprocess.run(
                ['curl', '-s', '--max-time', '15', url],
                capture_output=True, timeout=20
            )
            return result.stdout.decode('gbk', errors='replace')
        except Exception as e:
            self._log(f"[DataFeed] 查询失败: {e}")
            return ""

    def get_stock_spot(self) -> pd.DataFrame:
        """获取全市场实时行情 (带60秒缓存)"""
        # 缓存未过60秒的数据直接复用
        if 'spot' in self.cache and 'time' in self.cache:
            if (datetime.now() - self.cache['time']).total_seconds() < 60:
                return self.cache['spot']

        df_list = self.stock_list
        all_spot = []
        
        # 批量查询，每批80只
        codes = df_list.apply(lambda r: f"{r['market']}{r['code']}", axis=1).tolist()
        batch_size = 80
        
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            text = self._tencent_query(batch)
            
            for code in batch:
                match = re.search(f'v_{code}="([^"]+)"', text)
                if not match:
                    continue
                fields = match.group(1).split('~')
                if len(fields) < 35:
                    continue
                
                try:
                    # fields[35] 格式: 最新价/成交量/成交额
                    price_vol_amount = fields[35].split('/') if len(fields) > 35 and '/' in fields[35] else []
                    all_spot.append({
                        '代码': fields[2].zfill(6),
                        '名称': fields[1],
                        '最新价': float(fields[3]) if fields[3] else 0,
                        '昨收': float(fields[4]) if fields[4] else 0,
                        '今开': float(fields[5]) if fields[5] else 0,
                        '最高': float(fields[33]) if fields[33] else 0,
                        '最低': float(fields[34]) if fields[34] else 0,
                        '涨幅': float(fields[32]) if fields[32] else 0,
                        '涨跌额': float(fields[31]) if fields[31] else 0,
                        '成交量': float(fields[6]) if fields[6] else 0,
                        '成交额': float(price_vol_amount[2]) if len(price_vol_amount) >= 3 else 0,
                        '换手': float(fields[38]) if len(fields) > 38 and fields[38] else 0,
                        '量比': 0,  # 腾讯接口不提供量比，策略端会兼容处理
                        '市净率': float(fields[46]) if len(fields) > 46 and fields[46] else 0,
                        '市盈率': float(fields[39]) if len(fields) > 39 and fields[39] else 0,
                    })
                except Exception as e:
                    continue
            
            if (i // batch_size + 1) % 20 == 0:
                self._log(f"[DataFeed] 已获取 {len(all_spot)} 只行情, 进度 {min(i+batch_size, len(codes))}/{len(codes)}")
        
        result_df = pd.DataFrame(all_spot)
        if not result_df.empty:
            result_df['涨幅'] = result_df.apply(
                lambda r: round((r['最新价'] - r['昨收']) / r['昨收'] * 100, 2) if r['昨收'] > 0 else 0,
                axis=1
            )
        
        # 更新缓存
        self.cache['spot'] = result_df
        self.cache['time'] = datetime.now()
        return result_df

    def get_market_sentiment(self) -> Dict:
        """获取市场情绪"""
        text = self._tencent_query(['sh000001', 'sz399001', 'sz399006'])
        sentiment = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_stocks': len(self.stock_list),
            'up_count': 0,
            'down_count': 0,
            'up_ratio': 0.5,
            'limit_up': 0,
            'limit_down': 0,
            'top_sectors': []
        }
        
        # 获取全市场涨跌家数
        spot_df = self.get_stock_spot()
        if not spot_df.empty:
            sentiment['up_count'] = len(spot_df[spot_df['涨幅'] > 0])
            sentiment['down_count'] = len(spot_df[spot_df['涨幅'] < 0])
            total = len(spot_df)
            sentiment['up_ratio'] = sentiment['up_count'] / total if total > 0 else 0.5
            sentiment['limit_up'] = len(spot_df[spot_df['涨幅'] >= 9.5])
            sentiment['limit_down'] = len(spot_df[spot_df['涨幅'] <= -9.5])
        
        return sentiment

    def get_stock_hist(self, code: str, days: int = 20) -> pd.DataFrame:
        """获取个股历史K线 (腾讯日K线接口)"""
        market = 'sh' if code.startswith('6') else 'sz'
        end = datetime.now()
        start = end - timedelta(days=days * 2)
        
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
               f"param={market}{code},day,,,{days*2},qfq")
        
        try:
            result = subprocess.run(
                ['curl', '-s', '--max-time', '15', url],
                capture_output=True, timeout=20
            )
            data = json.loads(result.stdout.decode('utf-8', errors='replace'))
            key = f"{market}{code}"
            
            if key in data.get('data', {}):
                klines = data['data'][key].get('qfqday', data['data'][key].get('day', []))
                if klines:
                    df = pd.DataFrame(klines, columns=['日期', '开盘', '收盘', '最低', '最高', '成交量'])
                    for col in ['开盘', '收盘', '最低', '最高', '成交量']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    return df.tail(days).reset_index(drop=True)
        except Exception as e:
            self._log(f"[DataFeed] 获取 {code} 历史数据失败: {e}")
        
        return pd.DataFrame()

    def get_stock_fund_flow(self, code: str) -> Dict:
        """获取个股资金流向 (简化版: 用换手率和涨跌幅代替)"""
        spot_df = self.get_stock_spot()
        match = spot_df[spot_df['代码'] == code]
        if match.empty:
            return {}
        
        row = match.iloc[0]
        turnover = row.get('换手', 0)
        change = row.get('涨幅', 0)
        
        # 简化估算：涨幅大+换手率高 = 主力流入
        estimated_main = 1 if (change > 3 and turnover > 5) else (-1 if change < -3 else 0)
        
        return {
            'main_inflow': estimated_main * 1000000,
            'smail_inflow': 0,
            'net_pct': change,
        }

    def is_trade_time(self) -> bool:
        """检查是否为交易时间"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        time_str = now.strftime('%H:%M')
        return ('09:30' <= time_str <= '11:30') or ('13:00' <= time_str <= '15:00')

# 兼容性别名
DataFeedTencent = DataFeed
