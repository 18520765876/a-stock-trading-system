"""
交易分析器 - 自进化系统核心
负责分析每笔交易的赢亏原因，生成可执行的改进建议
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

ANALYSIS_DIR = os.path.expanduser('~/.hermes/astock-trader/data/analysis')
os.makedirs(ANALYSIS_DIR, exist_ok=True)

@dataclass
class TradeAnalysis:
    trade_id: str
    code: str
    name: str
    action: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    hold_days: int
    market_condition: str    # 市场环境: bull/bear/neutral
    sector_condition: str    # 板块环境
    entry_reasons: List[str] # 买入时的策略理由
    formulas: List[str]      # 买入触发公式
    signal_source: str       # 票源
    leader_grade: str        # 龙头评级
    exit_reasons: List[str]  # 卖出时的触发原因
    diagnosis: str           # 诊断结论
    lessons: List[str]       # 经验教训

class TradeAnalyzer:
    def __init__(self):
        self.analysis_file = os.path.join(ANALYSIS_DIR, 'trade_analysis.json')
        self.pattern_file = os.path.join(ANALYSIS_DIR, 'patterns.json')
        self.analyses = self._load_analyses()
        self.patterns = self._load_patterns()

    def _load_analyses(self) -> List[Dict]:
        if os.path.exists(self.analysis_file):
            with open(self.analysis_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def _load_patterns(self) -> Dict:
        if os.path.exists(self.pattern_file):
            with open(self.pattern_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'win_patterns': [],      # 赚钱模式
            'loss_patterns': [],     # 亏钱模式
            'market_bias': {},       # 市场偏好
            'factor_weights': {      # 因子权重进化
                'technical': 0.6,
                'fundamental': 0.3,
                'sentiment': 0.1
            }
        }

    def save(self):
        with open(self.analysis_file, 'w', encoding='utf-8') as f:
            json.dump(self.analyses, f, ensure_ascii=False, indent=2)
        with open(self.pattern_file, 'w', encoding='utf-8') as f:
            json.dump(self.patterns, f, ensure_ascii=False, indent=2)

    def analyze_trade(self, trade: Dict, position: Dict, market_sentiment: Dict) -> TradeAnalysis:
        """
        分析单笔交易
        """
        pnl = trade.get('pnl', 0)
        pnl_pct = trade.get('pnl_pct', 0)
        hold_days = trade.get('hold_days', 1)
        
        # 判断市场环境
        up_ratio = market_sentiment.get('up_ratio', 0.5)
        if up_ratio > 0.6:
            market_cond = 'bull'
        elif up_ratio < 0.4:
            market_cond = 'bear'
        else:
            market_cond = 'neutral'
        
        # 诊断
        diagnosis = self._diagnose(trade, position, market_cond, hold_days)
        lessons = self._extract_lessons(trade, diagnosis, hold_days)
        
        analysis = TradeAnalysis(
            trade_id=trade.get('trade_id', ''),
            code=trade.get('code', ''),
            name=trade.get('name', ''),
            action=trade.get('action', ''),
            entry_price=position.get('buy_price', 0),
            exit_price=trade.get('price', 0),
            pnl=pnl,
            pnl_pct=pnl_pct,
            hold_days=hold_days,
            market_condition=market_cond,
            sector_condition=position.get('sector', 'unknown'),
            entry_reasons=position.get('entry_reasons', []),
            formulas=position.get('formulas', []),
            signal_source=position.get('signal_source', ''),
            leader_grade=position.get('leader_grade', ''),
            exit_reasons=trade.get('reasons', []),
            diagnosis=diagnosis,
            lessons=lessons
        )
        
        self._record_analysis(analysis)
        return analysis

    def _diagnose(self, trade: Dict, position: Dict, market_cond: str, hold_days: int) -> str:
        """诊断交易成败原因"""
        pnl_pct = trade.get('pnl_pct', 0)
        
        if pnl_pct > 0:
            if market_cond == 'bull':
                return f"顺势交易成功，在{market_cond}市中获取{pnl_pct:.1%}收益"
            else:
                return f"逆势交易成功，在{market_cond}市中获取{pnl_pct:.1%}收益，运气或选股极佳"
        else:
            reasons = []
            if hold_days <= 1:
                reasons.append("持仓过短被洗")
            if hold_days >= 5:
                reasons.append("持仓过久未止损")
            if market_cond == 'bear':
                reasons.append("逆势交易")
            
            if not reasons:
                reasons.append("正常止损")
            
            return f"亏损{pnl_pct:.1%}，原因: {'+'.join(reasons)}"

    def _extract_lessons(self, trade: Dict, diagnosis: str, hold_days: int) -> List[str]:
        """提取经验教训"""
        lessons = []
        pnl_pct = trade.get('pnl_pct', 0)
        
        if pnl_pct < -0.05:
            lessons.append("大亏交易，需要审查入场时机是否太赶")
        if '逆势' in diagnosis and pnl_pct < 0:
            lessons.append("勿在弱市中主动买入，等待大盘企稳")
        if hold_days >= 5 and pnl_pct < 0:
            lessons.append("延迟止损导致亏损扩大，需更严格执行止损规则")
        if pnl_pct > 0.1:
            lessons.append("大赢交易，记录入场时的市场条件作为成功模式")
        
        return lessons if lessons else ["无特殊教训"]

    def _record_analysis(self, analysis: TradeAnalysis):
        """记录分析结果"""
        record = {
            'trade_id': analysis.trade_id,
            'code': analysis.code,
            'name': analysis.name,
            'action': analysis.action,
            'pnl': analysis.pnl,
            'pnl_pct': analysis.pnl_pct,
            'hold_days': analysis.hold_days,
            'market_condition': analysis.market_condition,
            'entry_reasons': analysis.entry_reasons,
            'formulas': analysis.formulas,
            'signal_source': analysis.signal_source,
            'leader_grade': analysis.leader_grade,
            'diagnosis': analysis.diagnosis,
            'lessons': analysis.lessons,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.analyses.append(record)
        self.save()

    def update_patterns(self):
        """更新交易模式库"""
        if len(self.analyses) < 5:
            return
        
        df = pd.DataFrame(self.analyses)
        
        # 赚钱模式
        wins = df[df['pnl'] > 0]
        if len(wins) > 0:
            win_market = wins['market_condition'].mode().tolist()
            self.patterns['win_patterns'] = win_market
        
        # 亏钱模式
        losses = df[df['pnl'] < 0]
        if len(losses) > 0:
            loss_market = losses['market_condition'].mode().tolist()
            self.patterns['loss_patterns'] = loss_market
        
        # 因子权重调整
        total = len(df)
        win_rate = len(wins) / total if total > 0 else 0
        
        if win_rate < 0.4 and total > 10:
            # 胜率低，加大资金面权重，减小技术面
            self.patterns['factor_weights']['technical'] = max(0.3, self.patterns['factor_weights']['technical'] - 0.05)
            self.patterns['factor_weights']['fundamental'] = min(0.6, self.patterns['factor_weights']['fundamental'] + 0.05)
        elif win_rate > 0.6 and total > 10:
            # 胜率高，保持或加大技术面
            self.patterns['factor_weights']['technical'] = min(0.7, self.patterns['factor_weights']['technical'] + 0.02)
        
        self.save()
        return self.patterns

    def get_performance_summary(self) -> Dict:
        """获取交易绩效摘要"""
        if not self.analyses:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_profit': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'lessons': []
            }
        
        df = pd.DataFrame(self.analyses)
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] < 0]
        
        avg_profit = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0
        profit_factor = abs(avg_profit / avg_loss) if avg_loss != 0 else float('inf')
        
        # 汇总所有教训
        all_lessons = []
        for lessons in df['lessons']:
            all_lessons.extend(lessons)
        
        from collections import Counter
        lesson_counts = Counter(all_lessons)
        top_lessons = [f"{k} ({v}次)" for k, v in lesson_counts.most_common(5)]

        def build_group_stats(records: List[Dict]) -> Dict:
            total_count = len(records)
            win_count = sum(1 for r in records if r.get('pnl', 0) > 0)
            total_pnl = sum(float(r.get('pnl', 0) or 0) for r in records)
            avg_pnl = total_pnl / total_count if total_count else 0.0
            return {
                'count': total_count,
                'win_rate': win_count / total_count if total_count else 0.0,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl,
            }

        group_breakdowns = {
            'signal_source': {},
            'formula': {},
            'leader_grade': {},
        }

        records = self.analyses
        for key in ['signal_source', 'leader_grade']:
            buckets = {}
            for rec in records:
                bucket_key = rec.get(key) or '未知'
                buckets.setdefault(bucket_key, []).append(rec)
            group_breakdowns[key] = {k: build_group_stats(v) for k, v in buckets.items()}

        formula_buckets = {}
        for rec in records:
            formulas = rec.get('formulas') or ['无公式']
            for formula in formulas:
                formula_buckets.setdefault(formula, []).append(rec)
        group_breakdowns['formula'] = {k: build_group_stats(v) for k, v in formula_buckets.items()}
        
        return {
            'total_trades': len(df),
            'win_rate': len(wins) / len(df) if len(df) > 0 else 0,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'lessons': top_lessons,
            'current_weights': self.patterns.get('factor_weights', {}),
            'group_breakdowns': group_breakdowns,
        }
