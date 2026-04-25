"""
A股虚拟账户管理模块
负责资金、持仓、成交记录的管理
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from config import (
    INITIAL_CAPITAL, COMMISSION_RATE, COMMISSION_MIN,
    STAMP_TAX_RATE, TRANSFER_FEE_RATE, DATA_CACHE_DIR, FIXED_TRADE_AMOUNT
)

@dataclass
class Position:
    code: str           # 股票代码
    name: str           # 股票名称
    buy_price: float    # 买入价格
    shares: int         # 持有股数
    buy_date: str       # 买入日期 YYYY-MM-DD
    current_price: float = 0.0
    highest_price: float = 0.0  # 最高价（用于移动止盈）
    half_sold: bool = False     # 是否已止盈一半
    entry_reasons: List[str] = None
    formulas: List[str] = None
    signal_source: str = ""
    leader_grade: str = ""
    leader_score: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.buy_price

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return self.unrealized_pnl / self.cost_basis

@dataclass
class Trade:
    trade_id: str
    code: str
    name: str
    action: str       # BUY / SELL_HALF / SELL_ALL
    price: float
    shares: int
    amount: float     # 成交金额
    commission: float
    stamp_tax: float
    transfer_fee: float
    total_cost: float # 总成本（含费用）
    trade_time: str
    pnl: float = 0.0  # 实现盈亏（卖出时计算）

class Account:
    def __init__(self, account_file: Optional[str] = None):
        self.account_file = account_file or os.path.join(DATA_CACHE_DIR, "account.json")
        self.cash = INITIAL_CAPITAL
        self.initial_capital = INITIAL_CAPITAL
        self.injected_capital = 0.0
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.daily_pnls: Dict[str, float] = {}  # date -> pnl
        self._load()

    def _load(self):
        """加载账户状态"""
        if os.path.exists(self.account_file):
            with open(self.account_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.cash = data.get('cash', INITIAL_CAPITAL)
            self.initial_capital = data.get('initial_capital', INITIAL_CAPITAL)
            self.injected_capital = data.get('injected_capital', 0.0)
            self.positions = {
                code: Position(**pos_data)
                for code, pos_data in data.get('positions', {}).items()
            }
            self.trades = [Trade(**t) for t in data.get('trades', [])]
            self.daily_pnls = data.get('daily_pnls', {})
            print(f"[账户] 已加载状态，现金: {self.cash:,.2f}，持仓: {len(self.positions)}")
        else:
            print(f"[账户] 创建新账户，初始资金: {self.cash:,.2f}")

    def save(self):
        """保存账户状态"""
        data = {
            'cash': self.cash,
            'initial_capital': self.initial_capital,
            'injected_capital': self.injected_capital,
            'positions': {
                code: {
                    'code': p.code,
                    'name': p.name,
                    'buy_price': p.buy_price,
                    'shares': p.shares,
                    'buy_date': p.buy_date,
                    'current_price': p.current_price,
                    'highest_price': p.highest_price,
                    'half_sold': p.half_sold,
                    'entry_reasons': p.entry_reasons or [],
                    'formulas': p.formulas or [],
                    'signal_source': p.signal_source,
                    'leader_grade': p.leader_grade,
                    'leader_score': p.leader_score,
                }
                for code, p in self.positions.items()
            },
            'trades': [
                {
                    'trade_id': t.trade_id,
                    'code': t.code,
                    'name': t.name,
                    'action': t.action,
                    'price': t.price,
                    'shares': t.shares,
                    'amount': t.amount,
                    'commission': t.commission,
                    'stamp_tax': t.stamp_tax,
                    'transfer_fee': t.transfer_fee,
                    'total_cost': t.total_cost,
                    'trade_time': t.trade_time,
                    'pnl': t.pnl
                }
                for t in self.trades
            ],
            'daily_pnls': self.daily_pnls
        }
        with open(self.account_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def ensure_capital(self, required_cash: float):
        """若现金不足则自动扩充总股本/注入资金，保证每个买入标的都能按固定金额成交"""
        if required_cash <= self.cash:
            return 0.0
        add_amount = required_cash - self.cash
        self.cash += add_amount
        self.injected_capital += add_amount
        self.save()
        return add_amount

    def calc_buy_cost(self, price: float, shares: int) -> Dict[str, float]:
        """计算买入费用"""
        amount = price * shares
        commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
        stamp_tax = 0.0  # 买入不收印花税
        transfer_fee = amount * TRANSFER_FEE_RATE
        total_cost = amount + commission + stamp_tax + transfer_fee
        return {
            'amount': amount,
            'commission': commission,
            'stamp_tax': stamp_tax,
            'transfer_fee': transfer_fee,
            'total_cost': total_cost
        }

    def calc_sell_cost(self, price: float, shares: int) -> Dict[str, float]:
        """计算卖出费用"""
        amount = price * shares
        commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
        stamp_tax = amount * STAMP_TAX_RATE
        transfer_fee = amount * TRANSFER_FEE_RATE
        total_cost = amount - commission - stamp_tax - transfer_fee
        return {
            'amount': amount,
            'commission': commission,
            'stamp_tax': stamp_tax,
            'transfer_fee': transfer_fee,
            'total_cost': total_cost
        }

    def buy(self, code: str, name: str, price: float, ratio: float, date_str: str, metadata: Optional[Dict] = None) -> Optional[Trade]:
        """
        买入股票
        ratio 参数仅为兼容保留；实际执行按固定金额 FIXED_TRADE_AMOUNT 买入。
        若现金不足，则自动扩充总股本后继续买入。
        """
        target_amount = FIXED_TRADE_AMOUNT
        metadata = metadata or {}
        shares = int(target_amount / price / 100) * 100  # A股手数整百

        if shares < 100:
            return None

        cost = self.calc_buy_cost(price, shares)
        if cost['total_cost'] > self.cash:
            self.ensure_capital(cost['total_cost'])
            cost = self.calc_buy_cost(price, shares)

        # 执行交易
        self.cash -= cost['total_cost']
        trade_id = f"B{date_str.replace('-','')}_{code}_{len(self.trades)}"
        trade = Trade(
            trade_id=trade_id,
            code=code,
            name=name,
            action='BUY',
            price=price,
            shares=shares,
            amount=cost['amount'],
            commission=cost['commission'],
            stamp_tax=cost['stamp_tax'],
            transfer_fee=cost['transfer_fee'],
            total_cost=cost['total_cost'],
            trade_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        self.trades.append(trade)

        # 更新持仓
        if code in self.positions:
            pos = self.positions[code]
            total_cost = pos.cost_basis + cost['amount']
            total_shares = pos.shares + shares
            pos.buy_price = total_cost / total_shares
            pos.shares = total_shares
            pos.entry_reasons = metadata.get('entry_reasons', pos.entry_reasons or [])
            pos.formulas = metadata.get('formulas', pos.formulas or [])
            pos.signal_source = metadata.get('signal_source', pos.signal_source)
            pos.leader_grade = metadata.get('leader_grade', pos.leader_grade)
            pos.leader_score = metadata.get('leader_score', pos.leader_score)
        else:
            self.positions[code] = Position(
                code=code,
                name=name,
                buy_price=price,
                shares=shares,
                buy_date=date_str,
                current_price=price,
                highest_price=price,
                entry_reasons=metadata.get('entry_reasons', []),
                formulas=metadata.get('formulas', []),
                signal_source=metadata.get('signal_source', ''),
                leader_grade=metadata.get('leader_grade', ''),
                leader_score=metadata.get('leader_score', 0.0)
            )

        self.save()
        return trade

    def sell(self, code: str, price: float, date_str: str, half: bool = False) -> Optional[Trade]:
        """卖出股票"""
        if code not in self.positions:
            return None

        pos = self.positions[code]
        shares = pos.shares // 2 if half else pos.shares
        if shares < 100:
            shares = pos.shares  # 如果不够半仓，全部卖出

        cost = self.calc_sell_cost(price, shares)
        realized_pnl = cost['total_cost'] - (shares * pos.buy_price)

        # 执行交易
        self.cash += cost['total_cost']
        action = 'SELL_HALF' if half and shares < pos.shares else 'SELL_ALL'
        trade_id = f"S{date_str.replace('-','')}_{code}_{len(self.trades)}"
        trade = Trade(
            trade_id=trade_id,
            code=code,
            name=pos.name,
            action=action,
            price=price,
            shares=shares,
            amount=cost['amount'],
            commission=cost['commission'],
            stamp_tax=cost['stamp_tax'],
            transfer_fee=cost['transfer_fee'],
            total_cost=cost['total_cost'],
            trade_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            pnl=realized_pnl
        )
        self.trades.append(trade)

        # 更新持仓
        if half and shares < pos.shares:
            pos.shares -= shares
            pos.half_sold = True
        else:
            del self.positions[code]

        self.save()
        return trade

    def update_prices(self, prices: Dict[str, float]):
        """更新持仓股票价格"""
        for code, price in prices.items():
            if code in self.positions:
                pos = self.positions[code]
                pos.current_price = price
                if price > pos.highest_price:
                    pos.highest_price = price

    @property
    def total_capital_base(self) -> float:
        """累计投入资本 = 初始资金 + 后续扩充资金"""
        return self.initial_capital + self.injected_capital

    @property
    def total_asset(self) -> float:
        """总资产"""
        market_value = sum(p.market_value for p in self.positions.values())
        return self.cash + market_value

    @property
    def total_pnl(self) -> float:
        """总盈亏（相对累计投入资本）"""
        return self.total_asset - self.total_capital_base

    @property
    def total_pnl_pct(self) -> float:
        """总盈亏率（相对累计投入资本）"""
        base = self.total_capital_base
        return self.total_pnl / base if base > 0 else 0.0

    def get_position_summary(self) -> List[dict]:
        """获取持仓摘要"""
        return [
            {
                'code': p.code,
                'name': p.name,
                'buy_price': p.buy_price,
                'current_price': p.current_price,
                'shares': p.shares,
                'market_value': p.market_value,
                'unrealized_pnl': p.unrealized_pnl,
                'unrealized_pnl_pct': p.unrealized_pnl_pct,
                'highest_price': p.highest_price,
                'half_sold': p.half_sold,
                'buy_date': p.buy_date,
                'cost_basis': p.cost_basis,
                'cost_amount': p.cost_basis,
                'position_pnl_pct': p.unrealized_pnl_pct,
                'entry_reasons': p.entry_reasons or [],
                'formulas': p.formulas or [],
                'signal_source': p.signal_source,
                'leader_grade': p.leader_grade,
                'leader_score': p.leader_score
            }
            for p in self.positions.values()
        ]

    def get_today_pnl(self, date_str: str) -> float:
        """获取今日盈亏"""
        return self.daily_pnls.get(date_str, 0.0)
