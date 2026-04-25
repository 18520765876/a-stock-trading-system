"""
A股虚拟短线交易系统 - 配置文件
"""
import os

# ==================== 账户配置 ====================
INITIAL_CAPITAL = 1_000_000.0  # 初始资金 100万（仅作初始参考）
MAX_POSITIONS = 9999           # 不限制持仓数量，所有符合买入条件的股票都买入
SINGLE_POSITION_RATIO = 0.10   # 保留兼容字段，不再作为实际买入约束
MIN_POSITION_RATIO = 0.10      # 保留兼容字段，不再作为实际买入约束
FIXED_TRADE_AMOUNT = 100_000.0 # 用户硬规则：每只股票固定买入10万元

# ==================== 费用配置 ====================
COMMISSION_RATE = 0.0001       # 佣金万分之一
COMMISSION_MIN = 5.0           # 最低佣金5元
STAMP_TAX_RATE = 0.0005        # 印花税卖出时千分之0.5（2023减半后）
TRANSFER_FEE_RATE = 0.00001    # 过户费沪市万分之0.1，深市免（简化统一收）

# ==================== 交易时间配置 ====================
TRADE_DAYS = [0, 1, 2, 3, 4]  # 周一到周五
AM_START = "09:30"
AM_END = "11:30"
PM_START = "13:00"
PM_END = "15:00"

# ==================== 策略参数 ====================
SCAN_INTERVAL_MINUTES = 5      # 每5分钟扫描一次
STOP_LOSS_PCT = -0.05          # 硬性止损 -5%
TAKE_PROFIT_HALF = 0.06        # 6%止盈一半
TAKE_PROFIT_TRAIL = 0.05       # 剩余一半从最高点回落5%清仓
MAX_HOLD_DAYS = 5              # 最大持股天数（短线）

# ==================== 企微Webhook配置 ====================
# 已禁用：所有信息只在当前对话框交流
WECHAT_WEBHOOK = None

# ==================== 数据配置 ====================
DATA_CACHE_DIR = os.path.expanduser("~/.hermes/astock-trader/data")
LOG_DIR = os.path.expanduser("~/.hermes/astock-trader/logs")
REPORT_DIR = os.path.expanduser("~/.hermes/astock-trader/reports")

# ==================== 情绪阈值 ====================
MARKET_BULL_RATIO = 0.6        # 涨跌家数比 > 60% 视为情绪偏多
MARKET_BEAR_RATIO = 0.4        # 涨跌家数比 < 40% 视为情绪偏空
MAX_DAILY_LIMIT_UP = 80        # 涨停家数 > 80 视为情绪过热
MAX_DAILY_LIMIT_DOWN = 30      # 跌停家数 > 30 视为情绪恐慌

for d in [DATA_CACHE_DIR, LOG_DIR, REPORT_DIR]:
    os.makedirs(d, exist_ok=True)
