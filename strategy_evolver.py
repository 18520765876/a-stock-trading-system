"""
策略进化器 - 自进化系统核心
根据历史交易分析，自动调整策略参数
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import json
import os
import pandas as pd
from datetime import datetime
from typing import Dict, List

EVOLVE_DIR = os.path.expanduser('~/.hermes/astock-trader/data/evolution')
os.makedirs(EVOLVE_DIR, exist_ok=True)

class StrategyEvolver:
    def __init__(self):
        self.config_file = os.path.join(EVOLVE_DIR, 'strategy_config.json')
        self.history_file = os.path.join(EVOLVE_DIR, 'evolution_history.json')
        self.config = self._load_config()
        self.history = self._load_history()

    def _load_config(self) -> Dict:
        """加载当前策略配置"""
        default = {
            'version': 1,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            # 技术因子参数（当前加法评分：技术约60分 + 资金约30分 + 板块/公式/龙头加分）
            'ma_weight': 15,           # 均线因子权重（占技术分15分，占总分9分）
            'volume_weight': 12,       # 量能因子权重（占技术分12分，占总分7.2分）
            'breakout_weight': 12,     # 突破因子权重（占技术分12分，占总分7.2分）
            'macd_weight': 9,          # MACD因子权重（占技术分9分，占总分5.4分）
            'change_weight': 9,        # 涨幅因子权重（占技术分9分，占总分5.4分）
            'turnover_score_weight': 3, # 换手率在技术分中的加分（使技术分满分=60）
            
            # 资金因子参数（占总分30%）
            'fund_flow_weight': 25,    # 资金流入权重（占资金分25分，占总分7.5分）
            'turnover_weight': 5,      # 换手率加分（占资金分5分，占总分1.5分）
            
            # 过滤参数（保留为兜底值；实盘扫描优先使用动态阈值）
            'min_change': 1.0,         # 最小涨幅%
            'max_change': 8.0,         # 最大涨幅%
            'min_turnover': 2.0,       # 最小换手率%
            'max_turnover': 20.0,      # 最大换手率%
            'min_ratio': 1.5,          # 最小量比
            'dynamic_lookback_days': 20,
            'change_threshold_floor': 0.8,
            'change_threshold_cap': 8.0,
            'turnover_threshold_floor': 1.5,
            'turnover_threshold_cap': 20.0,
            'volume_ratio_threshold_floor': 1.2,
            'volume_ratio_threshold_cap': 3.0,

            # 市场模式 / 情绪周期
            'market_normal_score': 3,
            'market_defense_score': 1,
            'sentiment_ice_limit_up_max': 30,
            'sentiment_warm_limit_up_max': 60,
            'sentiment_hot_limit_up_min': 80,

            # 分级门槛
            'yellow_required_normal': 2,
            'yellow_required_oscillation': 2,
            'yellow_required_defense': 1,
            
            # 买入阈值
            # 板块加分
            'sector_bonus': 10,        # 热点板块加分（占总分10%）
            
            # V3.0 新增：公式+龙头参数
            'formula_weight': 3,       # 每触发1套公式 +3分
            'leader_weight': 2,        # 每1分龙头评分 ×2分
            
            'buy_score_threshold': 50,  # 买入阈值（与当前加法评分体系匹配）
            'buy_score_threshold_defense': 55,

            # 卖出参数
            'stop_loss': -0.05,        # 用户硬规则：硬性止损-5%，不得自动放宽/收紧
            'take_profit_half': 0.06,  # 止盈一半
            'take_profit_trail': 0.05, # 回落清仓
            'max_hold_days': 5,        # 最大持股天数

            # 市场情绪参数
            'market_bull_ratio': 0.6,
            'market_bear_ratio': 0.4,
            'max_limit_up': 80,
            'max_limit_down': 30,
            
            # 账户管理（兼容字段保留：实际买入固定10万元，允许自动注资，不再使用仓位比例做买入约束）
            'max_positions': 9999,
            'single_position_ratio': 0.10,
            'min_position_ratio': 0.10,
            'fixed_trade_amount': 100000,
        }
        
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            # 合并，确保新增字段也有默认值
            for k, v in default.items():
                if k not in loaded:
                    loaded[k] = v
            return loaded
        return default

    def _load_history(self) -> List[Dict]:
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def save_config(self):
        self.config['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def record_evolution(self, reason: str, changes: Dict):
        """记录一次策略进化"""
        record = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': self.config['version'],
            'reason': reason,
            'changes': changes,
            'config_snapshot': self.config.copy()
        }
        self.history.append(record)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def evolve(self, trade_analyses: List[Dict]) -> Dict:
        """
        根据交易分析结果进化策略
        返回: {修改的参数, 原因}
        """
        if len(trade_analyses) < 10:
            return {'evolved': False, 'reason': '交易样本不足(<'+str(len(trade_analyses))+'/10)'}

        df = pd.DataFrame(trade_analyses)
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] < 0]
        
        total = len(df)
        win_rate = len(wins) / total if total > 0 else 0
        
        changes = {}
        reasons = []

        # 规则1: 胜率低于40%时收紧入场条件（选股不严，提高门槛）
        if win_rate < 0.40:
            old = self.config['buy_score_threshold']
            self.config['buy_score_threshold'] = min(75, old + 5)
            changes['buy_score_threshold'] = {'old': old, 'new': self.config['buy_score_threshold']}
            reasons.append(f"胜率{win_rate:.1%}偏低，收紧买入阈值 {old} -> {self.config['buy_score_threshold']}")
        
        # 规则2: 胜率高于60%时放宽入场（标准适当，降低门槛获取更多机会）
        elif win_rate > 0.60:
            old = self.config['buy_score_threshold']
            self.config['buy_score_threshold'] = max(50, old - 3)
            changes['buy_score_threshold'] = {'old': old, 'new': self.config['buy_score_threshold']}
            reasons.append(f"胜率{win_rate:.1%}优秀，放宽买入阈值 {old} -> {self.config['buy_score_threshold']}")

        # 规则3: 亏损交易持仓天数偏长时缩短持股
        if len(losses) > 0:
            avg_loss_hold = losses['hold_days'].mean()
            if avg_loss_hold > 3:
                old = self.config['max_hold_days']
                self.config['max_hold_days'] = max(3, old - 1)
                changes['max_hold_days'] = {'old': old, 'new': self.config['max_hold_days']}
                reasons.append(f"亏损交易平均持仓{avg_loss_hold:.1f}天，缩短最大持股天数 {old} -> {self.config['max_hold_days']}")

        # 规则4: 用户硬规则，止损固定 -5%，不参与自动进化
        recent_losses = df.tail(5)
        if False and len(recent_losses[recent_losses['pnl'] < 0]) >= 4:
            old = self.config['stop_loss']
            self.config['stop_loss'] = max(-0.05, old - 0.005)
            changes['stop_loss'] = {'old': old, 'new': self.config['stop_loss']}
            reasons.append(f"近5笔亏4笔，收紧止损 {old} -> {self.config['stop_loss']}")

        # 规则5: 连续赚钱但赚得少时放宽止盈
        recent_wins = df.tail(10)
        wins_10 = recent_wins[recent_wins['pnl'] > 0]
        if len(wins_10) >= 7 and wins_10['pnl'].mean() < wins_10['pnl'].quantile(0.3):
            old = self.config['take_profit_half']
            self.config['take_profit_half'] = min(0.10, old + 0.01)
            changes['take_profit_half'] = {'old': old, 'new': self.config['take_profit_half']}
            reasons.append(f"连续小赚，提高止盈目标 {old} -> {self.config['take_profit_half']}")

        # 规则6: 根据市场环境调整板块加分
        if len(wins) > 0:
            win_bull_ratio = len(wins[wins['market_condition'] == 'bull']) / len(wins) if len(wins) > 0 else 0
            if win_bull_ratio > 0.7:
                old = self.config['sector_bonus']
                self.config['sector_bonus'] = min(10, old + 1)
                changes['sector_bonus'] = {'old': old, 'new': self.config['sector_bonus']}
                reasons.append(f"牛市赚钱概率高，提高板块加分 {old} -> {self.config['sector_bonus']}")

        if changes:
            self.config['version'] += 1
            self.save_config()
            reason_text = "\n".join(reasons)
            self.record_evolution(reason_text, changes)
            return {
                'evolved': True,
                'version': self.config['version'],
                'reason': reason_text,
                'changes': changes
            }
        
        return {'evolved': False, 'reason': '当前策略无需调整'}

    def get_current_config(self) -> Dict:
        return self.config.copy()

    def get_evolution_report(self) -> str:
        """生成策略进化报告"""
        if not self.history:
            return "暂无策略进化历史"
        
        lines = ["=== 策略进化历史 ===", ""]
        for h in self.history[-5:]:
            lines.append(f"v{h['version']} ({h['timestamp']})")
            lines.append(f"  原因: {h['reason']}")
            lines.append(f"  变更: {json.dumps(h['changes'], ensure_ascii=False)}")
            lines.append("")
        
        lines.append(f"\n当前配置 v{self.config['version']}:")
        for k in ['buy_score_threshold', 'buy_score_threshold_defense', 'stop_loss', 'take_profit_half', 'max_hold_days', 'fixed_trade_amount']:
            lines.append(f"  {k}: {self.config.get(k, 'N/A')}")
        
        return "\n".join(lines)
