"""
周度策略进化任务 (周日 23:00 执行)
- 归因分析
- 模块胜率统计
- 权重自动调整
- 策略基因池进化
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

from datetime import datetime
from executor import Executor

def run_weekly_evolution():
    print("="*60)
    print(f"⚙️ 周度策略进化 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)
    
    executor = Executor()
    
    # 运行进化分析
    result = executor.run_evolution_only()
    
    if result.get('evolved'):
        print(f"\n✅ 策略已进化到 v{result['version']}")
        print(f"原因: {result['reason']}")
    else:
        print(f"\n◦ {result.get('reason', '本周未触发进化')}")
    
    print("\n周度进化完成，下次进化: 下周日 23:00")

if __name__ == '__main__':
    run_weekly_evolution()
