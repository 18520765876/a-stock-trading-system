"""
A股虚拟短线交易系统 - 主程序
使用: python main.py scan    # 执行一次市场扫描
      python main.py report  # 生成每日报告
      python main.py init    # 初始化账户
      python main.py evolve  # 运行自进化分析
      python main.py test    # 测试数据连接和webhook
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import argparse
from executor import Executor
from account import Account
from config import INITIAL_CAPITAL
from notifier import Notifier

def init_account():
    """初始化账户"""
    account = Account()
    print(f"[系统] 账户已初始化")
    print(f"  初始资金: ¥{INITIAL_CAPITAL:,.2f}")
    print(f"  当前现金: ¥{account.cash:,.2f}")
    print(f"  持仓数量: {len(account.positions)}")
    print(f"  总资产:   ¥{account.total_asset:,.2f}")

def run_scan():
    """运行交易扫描"""
    executor = Executor()
    executor.run_scan()

def run_report():
    """运行每日报告"""
    executor = Executor()
    executor.generate_daily_report()

def run_evolve():
    """运行自进化分析"""
    executor = Executor()
    executor.run_evolution_only()

def run_test():
    """测试系统连通性"""
    print("="*60)
    print("[测试] 系统连通性测试")
    print("="*60)
    
    # 1. 测试股票列表
    from data_feed import DataFeed
    feed = DataFeed()
    print(f"[测试] 股票列表: {len(feed.stock_list)} 只")
    
    # 2. 测试实时行情
    print("[测试] 获取实时行情...")
    spot = feed.get_stock_spot()
    print(f"[测试] 获取到 {len(spot)} 只行情")
    if not spot.empty:
        print(f"[测试] 样例: {spot.iloc[0]['名称']} {spot.iloc[0]['代码']} ¥{spot.iloc[0]['最新价']}")
    
    # 3. 测试市场情绪
    print("[测试] 获取市场情绪...")
    sentiment = feed.get_market_sentiment()
    print(f"[测试] 涨跌比: {sentiment.get('up_ratio', 0):.1%}")
    
    # 4. 测试历史数据
    print("[测试] 获取历史K线...")
    hist = feed.get_stock_hist('600519', days=5)
    print(f"[测试] 获取到 {len(hist)} 天数据")
    if not hist.empty:
        print(f"[测试] 最新收盘: ¥{hist.iloc[-1]['收盘']}")
    
    # 5. 测试webhook
    print("[测试] 测试企微推送...")
    notifier = Notifier()
    ok = notifier._send("🧪 A股模拟交易系统测试消息\n\n系统已就绪，等待开盘！📈", "text")
    print(f"[测试] 推送{'成功' if ok else '失败'}")
    
    print("\n[测试] 全部测试完成！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='A股模拟交易系统')
    parser.add_argument('command', choices=['scan', 'report', 'init', 'evolve', 'test'],
                       help='执行命令: scan=扫描, report=报告, init=初始化, evolve=进化, test=测试')
    args = parser.parse_args()

    if args.command == 'init':
        init_account()
    elif args.command == 'scan':
        run_scan()
    elif args.command == 'report':
        run_report()
    elif args.command == 'evolve':
        run_evolve()
    elif args.command == 'test':
        run_test()
