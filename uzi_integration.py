"""
UZI-Skill 集成模块 v1.0
将 UZI 的 51 位投资大佬评审团融入 A 股短线选股系统

核心功能：
1. 对候选股票做 UZI 深度分析（22维数据采集 + 51评委打分）
2. 提取关键特征用于选股评分加成
3. 游资射程检查（F组游资只做中小盘）

用法：
    from uzi_integration import UZIAnalyzer
    uzi = UZIAnalyzer()
    score_boost = uzi.analyze_stock('600519', kline_data)
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

import os
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# UZI 核心模块
from lib.investor_db import INVESTORS
from lib.investor_evaluator import evaluate
from lib.stock_features import extract_features

@dataclass
class UZIScore:
    code: str
    name: str
    overall_score: float      # 0-100 综合评分
    bullish_count: int        # 看多评委数
    bearish_count: int        # 看空评委数
    neutral_count: int        # 中性评委数
    top_bulls: List[Dict]     # 前3名看多评委
    top_bears: List[Dict]     # 前3名看空评委
    youzi_signal: str         # 游资组信号 (bullish/bearish/neutral)
    value_signal: str         # 价值派信号
    growth_signal: str        # 成长派信号
    tech_signal: str          # 技术派信号
    score_boost: float        # 给我们选股系统的加分 (-20 ~ +20)
    key_risks: List[str]      # 关键风险点
    key_opportunities: List[str]  # 关键机会点


class UZIAnalyzer:
    """UZI 分析器 — 轻量级集成，不跑完整 pipeline"""

    # 各组权重映射到我们的选股加分
    GROUP_WEIGHTS = {
        'A': 0.15,   # 价值派
        'B': 0.20,   # 成长派
        'C': 0.10,   # 宏观派
        'D': 0.25,   # 技术派（对我们短线最重要）
        'E': 0.15,   # 中国价投
        'F': 0.15,   # 游资（对我们短线最重要）
    }

    def __init__(self):
        self.investors = INVESTORS
        self._group_map = {inv['id']: inv.get('group', '') for inv in self.investors}

    def _build_raw_stub(self, code: str, name: str, kline: List[Dict], spot_row: Optional[Dict] = None) -> Dict:
        """从我们的 kline + spot 数据构建 UZI raw_data stub"""
        # 提取基本价格数据
        latest = kline[-1] if kline else {}
        prev = kline[-2] if len(kline) >= 2 else latest

        # 计算基础技术指标
        closes = [d['close'] for d in kline]
        highs = [d['high'] for d in kline]
        lows = [d['low'] for d in kline]
        volumes = [d['volume'] for d in kline]

        # MA
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else 0

        # Stage 判断 (Minervini Stage Analysis 简化版)
        stage = "—"
        if len(closes) >= 60:
            if ma5 > ma10 > ma20 > ma60 and closes[-1] > ma5:
                stage = "Stage 2 (上升趋势)"
            elif ma5 < ma10 < ma20 and closes[-1] < ma5:
                stage = "Stage 4 (下降趋势)"
            elif ma20 > ma60 and abs(closes[-1] - ma20) / ma20 < 0.05:
                stage = "Stage 1 (底部整理)"
            else:
                stage = "Stage 3 (顶部整理)"

        # MACD 简化
        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        dif = ema12 - ema26 if ema12 and ema26 else 0
        macd_str = "—"
        if dif > 0:
            macd_str = f"金叉 水上 DIF={dif:.2f}" if dif > 0 else f"死叉 水下 DIF={dif:.2f}"

        # RSI 简化
        rsi = self._rsi(closes, 14)

        # 涨跌幅
        change_pct = ((latest.get('close', 0) - prev.get('close', 1)) / prev.get('close', 1) * 100) if prev.get('close') else 0

        # 构建 raw_data stub
        raw = {
            "ticker": code,
            "dimensions": {
                "0_basic": {"data": {
                    "code": code,
                    "name": name,
                    "price": latest.get('close', 0),
                    "change_pct": round(change_pct, 2),
                    "market_cap": spot_row.get('总市值', 0) * 1e8 if spot_row else 0,
                }},
                "2_kline": {"data": {
                    "stage": stage,
                    "ma_align": "均线多头" if ma5 > ma10 > ma20 else "均线空头" if ma5 < ma10 < ma20 else "均线纠缠",
                    "macd": macd_str,
                    "rsi": round(rsi, 1) if rsi else 0,
                    "kline_stats": {
                        "max_drawdown": self._max_drawdown(closes),
                        "volatility": self._volatility(closes),
                        "ytd_return": self._ytd_return(closes),
                    }
                }},
                "12_capital_flow": {"data": {
                    "main_force_ratio": spot_row.get('换手', 0) if spot_row else 0,
                    "net_inflow_yi": 0,
                }},
                "17_sentiment": {"data": {
                    "limit_up_count": 0,
                    "limit_down_count": 0,
                    "up_ratio": 0.5,
                }},
            }
        }
        return raw

    def _ema(self, values, period):
        if len(values) < period:
            return None
        mult = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for v in values[period:]:
            ema = (v - ema) * mult + ema
        return ema

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return None
        gains = losses = 0
        for i in range(1, period + 1):
            ch = closes[-i] - closes[-i-1]
            if ch > 0:
                gains += ch
            else:
                losses += abs(ch)
        if losses == 0:
            return 100
        return 100 - (100 / (1 + gains / losses))

    def _max_drawdown(self, closes):
        if not closes:
            return 0
        peak = closes[0]
        max_dd = 0
        for c in closes:
            if c > peak:
                peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 1)

    def _volatility(self, closes):
        if len(closes) < 20:
            return 0
        ma20 = sum(closes[-20:]) / 20
        variance = sum((c - ma20) ** 2 for c in closes[-20:]) / 20
        return round((variance ** 0.5) / ma20 * 100, 1) if ma20 else 0

    def _ytd_return(self, closes):
        if len(closes) < 60:
            return 0
        return round((closes[-1] - closes[-60]) / closes[-60] * 100, 1) if closes[-60] else 0

    def analyze_stock(self, code: str, name: str, kline: List[Dict], spot_row: Optional[Dict] = None) -> UZIScore:
        """
        对单只股票做 UZI 轻量级评审
        返回 UZIScore，包含给我们选股系统的加分建议
        """
        # 1. 构建 raw stub
        raw = self._build_raw_stub(code, name, kline, spot_row)

        # 2. 提取特征
        features = extract_features(raw, raw.get("dimensions", {}))
        features['code'] = code
        features['name'] = name

        # 3. 对每位投资者打分
        evaluations = []
        for inv in self.investors:
            ev = evaluate(inv['id'], features)
            if ev and not ev.get('skipped'):
                evaluations.append({
                    'id': inv['id'],
                    'name': inv.get('name', inv['id']),
                    'group': inv.get('group', ''),
                    'score': ev.get('score', 50),
                    'signal': ev.get('signal', 'neutral'),
                    'confidence': ev.get('confidence', 0),
                    'headline': ev.get('headline', ''),
                })

        # 4. 统计各组信号
        group_signals = {'A': [], 'B': [], 'C': [], 'D': [], 'E': [], 'F': []}
        for e in evaluations:
            g = e['group']
            if g in group_signals:
                group_signals[g].append(e)

        def _group_signal(scores):
            if not scores:
                return 'neutral'
            avg = sum(s['score'] for s in scores) / len(scores)
            if avg >= 65:
                return 'bullish'
            elif avg <= 35:
                return 'bearish'
            return 'neutral'

        # 5. 计算综合评分和加分
        overall_score = sum(e['score'] for e in evaluations) / len(evaluations) if evaluations else 50
        bullish = sum(1 for e in evaluations if e['signal'] == 'bullish')
        bearish = sum(1 for e in evaluations if e['signal'] == 'bearish')
        neutral = sum(1 for e in evaluations if e['signal'] == 'neutral')

        # 计算 score_boost: 技术派和游资权重最高
        score_boost = 0
        for g, weight in self.GROUP_WEIGHTS.items():
            sig = _group_signal(group_signals.get(g, []))
            if sig == 'bullish':
                score_boost += weight * 20
            elif sig == 'bearish':
                score_boost -= weight * 15

        # 限制加分范围
        score_boost = max(-15, min(15, score_boost))

        # 6. 提取 top bulls / bears
        bulls = sorted([e for e in evaluations if e['signal'] == 'bullish'], key=lambda x: x['score'], reverse=True)[:3]
        bears = sorted([e for e in evaluations if e['signal'] == 'bearish'], key=lambda x: x['score'])[:3]

        # 7. 关键风险/机会
        risks = []
        opportunities = []
        for e in evaluations:
            if e['signal'] == 'bearish' and e['score'] < 30:
                risks.append(f"{e['name']}: {e['headline']}")
            elif e['signal'] == 'bullish' and e['score'] > 75:
                opportunities.append(f"{e['name']}: {e['headline']}")

        return UZIScore(
            code=code,
            name=name,
            overall_score=round(overall_score, 1),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            top_bulls=bulls,
            top_bears=bears,
            youzi_signal=_group_signal(group_signals.get('F', [])),
            value_signal=_group_signal(group_signals.get('A', [])),
            growth_signal=_group_signal(group_signals.get('B', [])),
            tech_signal=_group_signal(group_signals.get('D', [])),
            score_boost=round(score_boost, 1),
            key_risks=risks[:3],
            key_opportunities=opportunities[:3],
        )

    def batch_analyze(self, candidates: List[Dict], max_workers: int = 3) -> List[UZIScore]:
        """批量分析候选股票"""
        results = []
        for c in candidates:
            try:
                score = self.analyze_stock(c['code'], c['name'], c.get('kline', []), c.get('spot_row'))
                results.append(score)
            except Exception as e:
                print(f"[UZI] {c['code']} 分析失败: {e}")
        return results


def quick_uzi_score(code: str, name: str, kline: List[Dict], spot_row: Optional[Dict] = None) -> Tuple[float, str, List[str]]:
    """快速获取 UZI 加分和理由（供 strategy.py 直接调用）"""
    try:
        analyzer = UZIAnalyzer()
        result = analyzer.analyze_stock(code, name, kline, spot_row)
        reasons = []
        if result.tech_signal == 'bullish':
            reasons.append(f"技术派看多({result.bullish_count}人看多)")
        if result.youzi_signal == 'bullish':
            reasons.append(f"游资派看多")
        if result.value_signal == 'bullish':
            reasons.append(f"价值派看多")
        if result.growth_signal == 'bullish':
            reasons.append(f"成长派看多")
        if result.key_opportunities:
            reasons.extend([f"机会: {r}" for r in result.key_opportunities[:2]])
        if result.key_risks:
            reasons.extend([f"风险: {r}" for r in result.key_risks[:2]])
        return result.score_boost, result.youzi_signal, reasons
    except Exception as e:
        print(f"[UZI快速评分] {code} 失败: {e}")
        return 0, 'neutral', []
