"""
短线交易策略引擎 (V3.0 进化版)
在自进化评分基础上融入用户6套公式 + 龙头过滤
综合: 市场情绪 + 板块热度 + 技术指标 + 资金流向 + 6套公式 + 龙头评级
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')
sys.path.insert(0, '/home/agentuser/a_stock_trading_system')

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from data_feed import DataFeed
from strategy_evolver import StrategyEvolver

@dataclass
class Signal:
    code: str
    name: str
    action: str      # BUY / SELL
    score: float     # 信号强度 0-100
    reasons: List[str]
    current_price: float
    suggested_ratio: float  # 建议仓位比例
    formulas: List[str] = field(default_factory=list)  # 触发的公式列表
    leader_grade: str = ""    # 龙头评级
    leader_score: float = 0   # 龙头评分
    signal_source: str = ""   # 票源：盘前票/尾盘票

class Strategy:
    def __init__(self, evolver: Optional[StrategyEvolver] = None):
        self.feed = DataFeed()
        self.evolver = evolver or StrategyEvolver()
        self.cfg = self.evolver.get_current_config()

    def reload_config(self):
        """重新加载进化后的配置"""
        self.cfg = self.evolver.get_current_config()

    def _df_to_kline(self, hist_df):
        """pandas DataFrame → evolved_trading_system 需要的 dict list"""
        kline = []
        for _, row in hist_df.iterrows():
            try:
                kline.append({
                    'date': str(row['日期']),
                    'open': float(row['开盘']),
                    'close': float(row['收盘']),
                    'low': float(row['最低']),
                    'high': float(row['最高']),
                    'volume': float(row['成交量'])
                })
            except:
                continue
        return kline

    def detect_formulas(self, hist_df):
        """检浗6套选股公式，返回触发的信号列表"""
        try:
            from evolved_trading_system import Selectors as FormulaSelectors
            kline = self._df_to_kline(hist_df)
            if len(kline) < 40:
                return []
            return FormulaSelectors.all_signals(kline)
        except Exception as e:
            print(f"[公式检测] 异常: {e}")
            return []

    def evaluate_leader(self, row, hist_df):
        """龙头评分 - 整合 leader-stock-identification 技能增强"""
        try:
            from evolved_trading_system import LeaderFilter, TI
            stock_dict = {
                'turnoverratio': float(row.get('换手', 0)),
                'changepercent': float(row.get('涨幅', 0)),
                'volume': float(row.get('成交量', 0)),
            }
            kline = self._df_to_kline(hist_df) if hist_df is not None and not hist_df.empty else None
            
            # 计算技术评分 (-5~+5) 传给 LeaderFilter 做加成
            tech_score_ev = 0
            if kline and len(kline) >= 35:
                closes = [d['close'] for d in kline]
                try:
                    tech_score_ev, _ = TI.kline_score(kline, closes)
                except Exception:
                    pass
            
            result = LeaderFilter.evaluate(stock_dict, kline, tech_score=tech_score_ev)
            result['tech_score_ev'] = tech_score_ev  # 附加，供上层使用
            return result
        except Exception as e:
            print(f"[龙头评分] 异常: {e}")
            return {'score': 0, 'grade': '⚪ 未评级', 'reasons': [], 'tech_score_ev': 0}

    def market_filter(self, sentiment: Dict) -> Tuple[bool, str]:
        """大盘情绪过滤"""
        if not sentiment:
            return False, "无法获取市场情绪"

        up_ratio = sentiment.get('up_ratio', 0.5)
        limit_down = sentiment.get('limit_down', 0)
        limit_up = sentiment.get('limit_up', 0)

        if limit_down > self.cfg['max_limit_down']:
            return False, f"跌停家数{limit_down}，市场恐慌，观望"
        if up_ratio > 0.85 and limit_up > self.cfg['max_limit_up']:
            return False, f"涨跌家比{up_ratio:.1%}，过热，防止追高"
        if up_ratio < self.cfg['market_bear_ratio']:
            return False, f"涨跌家比{up_ratio:.1%}，情绪弱，不主动"

        return True, f"情绪正常，涨跌比{up_ratio:.1%}"

    def _compute_market_mode(self, sentiment: Dict) -> Tuple[str, int, str]:
        """根据大盘与涨停/跌停结构划分三档市场模式"""
        if not sentiment:
            return 'defense', 0, '情绪缺失，按防守模式处理'

        score = 0
        up_ratio = sentiment.get('up_ratio', 0.5)
        limit_up = sentiment.get('limit_up', 0)
        limit_down = sentiment.get('limit_down', 0)

        if up_ratio >= 0.55:
            score += 1
        if limit_up >= 30:
            score += 1
        if limit_down <= 10:
            score += 1
        if up_ratio < 0.40 or limit_down > 30:
            score -= 1

        normal_score = self.cfg.get('market_normal_score', 3)
        defense_score = self.cfg.get('market_defense_score', 1)

        if score >= normal_score:
            return 'normal', score, f'正常模式(score={score})'
        if score <= defense_score:
            return 'defense', score, f'防守模式(score={score})'
        return 'oscillation', score, f'震荡模式(score={score})'

    def _detect_sentiment_cycle(self, sentiment: Dict) -> str:
        """情绪周期识别：冰点/回暖/分歧/高潮/退潮
        整合 market-sentiment 技能：加入炸板率 + 冰点/回暖/分歧/亢奋四阶段
        """
        limit_up = sentiment.get('limit_up', 0)
        limit_down = sentiment.get('limit_down', 0)
        up_ratio = sentiment.get('up_ratio', 0.5)
        # 炸板率: 如果有涨停尝试数据则计算, 否则用涨停/跌停比近似
        zt_attempt = sentiment.get('limit_up_attempt', 0)
        if zt_attempt > 0 and limit_up > 0:
            zhaban_rate = zt_attempt / (limit_up + zt_attempt) * 100
        else:
            zhaban_rate = 0  # 无数据时不作为判断依据

        # 四阶段判断 (market-sentiment 技能)
        if limit_up < self.cfg.get('sentiment_ice_limit_up_max', 30) or limit_down > 30:
            return '冰点'
        if zhaban_rate > 25:
            return '分歧'  # 炸板率高: 多空分歧大
        if limit_up >= self.cfg.get('sentiment_hot_limit_up_min', 80) and up_ratio >= 0.6 and zhaban_rate < 15:
            return '高潮'
        if limit_up <= self.cfg.get('sentiment_warm_limit_up_max', 60):
            return '回暖'
        return '退潮'

    def _dynamic_thresholds(self, spot_df: pd.DataFrame) -> Dict[str, float]:
        """根据当日全市场分布计算动态阈值，替代固定阈值硬过滤"""
        if spot_df.empty:
            return {
                'min_change': self.cfg['min_change'],
                'max_change': self.cfg['max_change'],
                'min_turnover': self.cfg['min_turnover'],
                'max_turnover': self.cfg['max_turnover'],
                'min_ratio': self.cfg['min_ratio'],
            }

        turnover_q = float(spot_df['换手'].quantile(0.60)) if '换手' in spot_df else self.cfg['min_turnover']
        change_q = float(spot_df['涨幅'].quantile(0.65)) if '涨幅' in spot_df else self.cfg['min_change']
        ratio_q = float(spot_df['量比'].quantile(0.60)) if '量比' in spot_df and spot_df['量比'].max() > 0 else self.cfg['min_ratio']

        return {
            'min_change': max(self.cfg.get('change_threshold_floor', 0.8), min(change_q, self.cfg.get('change_threshold_cap', 8.0))),
            'max_change': self.cfg['max_change'],
            'min_turnover': max(self.cfg.get('turnover_threshold_floor', 1.5), min(turnover_q, self.cfg.get('turnover_threshold_cap', 20.0))),
            'max_turnover': self.cfg['max_turnover'],
            'min_ratio': max(self.cfg.get('volume_ratio_threshold_floor', 1.2), min(ratio_q, self.cfg.get('volume_ratio_threshold_cap', 3.0))),
        }

    def _formula_allowed(self, formulas: List[str], market_mode: str, sentiment_cycle: str) -> bool:
        """不同市场模式/情绪周期下允许不同公式参与"""
        if not formulas:
            return False

        formula_text = ' '.join(formulas)
        if sentiment_cycle in ('退潮', '分歧'):
            return False  # 退潮/分歧期不参与
        if market_mode == 'defense':
            return '背离' in formula_text
        if market_mode == 'oscillation':
            return any(k in formula_text for k in ['箱体', '回踩', '背离'])
        return True

    def _tier_gate_pass(self, row, tech_score: float, fund_score: float, formulas: List[str], leader: Dict, market_mode: str) -> Tuple[bool, List[str], List[str], List[str]]:
        """红黄绿三级门槛：红色必选、黄色核心、绿色加分"""
        reds, yellows, greens = [], [], []

        change = float(row.get('涨幅', 0))
        turnover = float(row.get('换手', 0))

        if change > 0:
            reds.append('涨幅为正')
        if tech_score >= max(20, self.cfg['ma_weight']):
            reds.append('趋势方向有效')

        if tech_score >= 30:
            yellows.append('技术分达标')
        if fund_score >= self.cfg['fund_flow_weight'] * 0.5:
            yellows.append('资金面达标')
        if formulas:
            yellows.append('命中公式')
        if leader.get('score', 0) >= 3:
            yellows.append('龙头评级达标')
        if turnover >= self.cfg.get('turnover_threshold_floor', 1.5):
            yellows.append('换手有效')

        if leader.get('score', 0) >= 4:
            greens.append('强龙头加分')
        if len(formulas) >= 2:
            greens.append('多公式共振')
        if change <= 5:
            greens.append('涨幅不过热')

        all_red = len(reds) >= 2
        required_yellow = {
            'normal': self.cfg.get('yellow_required_normal', 2),
            'oscillation': self.cfg.get('yellow_required_oscillation', 2),
            'defense': self.cfg.get('yellow_required_defense', 1),
        }.get(market_mode, 2)
        return all_red and len(yellows) >= required_yellow, reds, yellows, greens

    def calc_technical_score(self, hist: pd.DataFrame) -> Tuple[float, List[str]]:
        """技术面评分"""
        if len(hist) < 10:
            return 0, ["历史数据不足"]

        score = 0
        reasons = []
        cfg = self.cfg

        close = hist['收盘'].values
        high = hist['最高'].values
        low = hist['最低'].values
        vol = hist['成交量'].values

        # 1. 均线多头排列
        ma5 = close[-5:].mean()
        ma10 = close[-10:].mean()
        ma20 = close[-20:].mean() if len(close) >= 20 else close.mean()

        if close[-1] > ma5 > ma10 > ma20:
            score += cfg['ma_weight']
            reasons.append(f"均线多头排列 MA5={ma5:.2f} > MA10={ma10:.2f}")
        elif close[-1] > ma5 > ma10:
            score += cfg['ma_weight'] * 0.6
            reasons.append(f"短期均线多头 MA5={ma5:.2f} > MA10={ma10:.2f}")
        elif close[-1] < ma5:
            score -= 10
            reasons.append(f"股价低于MA5，短期偏弱")

        # 2. 量能配合
        avg_vol = vol[-5:].mean()
        prev_avg_vol = vol[-10:-5].mean() if len(vol) >= 10 else vol.mean()
        vol_ratio = avg_vol / prev_avg_vol if prev_avg_vol > 0 else 1

        if vol_ratio > 2.0 and close[-1] > close[-2]:
            score += cfg['volume_weight']
            reasons.append(f"量能齐升，量比{vol_ratio:.1f}")
        elif vol_ratio > 1.5 and close[-1] > close[-2]:
            score += cfg['volume_weight'] * 0.5
            reasons.append(f"量能配合，量比{vol_ratio:.1f}")
        elif vol_ratio < 0.6 and close[-1] < close[-2]:
            score -= 10
            reasons.append("缩量下跌，趋势可能转弱")

        # 3. 价格形态
        recent_high = high[-5:].max()
        recent_low = low[-5:].min()

        if close[-1] >= recent_high * 0.98 and close[-2] < recent_high * 0.98:
            score += cfg['breakout_weight']
            reasons.append("创近5日新高，突破形态")
        elif close[-1] > ma5 and close[-2] < ma5:
            score += cfg['breakout_weight'] * 0.5
            reasons.append("回踩MA5支撑反弹")

        # 4. 涨幅控制
        change_pct = (close[-1] - close[-2]) / close[-2] * 100 if len(close) >= 2 else 0
        if cfg['min_change'] <= change_pct <= cfg['max_change']:
            score += cfg['change_weight']
            reasons.append(f"涨幅{change_pct:.1f}%，活跃且未过热")
        elif change_pct > 9:
            score -= 10
            reasons.append(f"涨幅{change_pct:.1f}%，追高风险高")
        elif change_pct < -3:
            score -= 15
            reasons.append(f"跌幅{change_pct:.1f}%，趋势转弱")

        # 5. MACD 简化
        if len(close) >= 12:
            ema12 = pd.Series(close).ewm(span=12).mean().values
            ema26 = pd.Series(close).ewm(span=26).mean().values
            diff = ema12 - ema26
            if len(diff) >= 2:
                if diff[-1] > 0 and diff[-2] < 0:
                    score += cfg['macd_weight']
                    reasons.append("金叉上穿，MACD转多")
                elif diff[-1] > diff[-2] > 0:
                    score += cfg['macd_weight'] * 0.6
                    reasons.append("红柱放大，多头持续")
                elif diff[-1] < diff[-2] < 0:
                    score -= 5
                    reasons.append("绿柱放大，空头持续")

        return max(0, min(100, score)), reasons

    def calc_fund_score(self, fund_data: Dict) -> Tuple[float, List[str]]:
        """资金面评分"""
        if not fund_data:
            return 0, ["无资金数据"]

        score = 0
        reasons = []
        cfg = self.cfg

        main_inflow = fund_data.get('main_inflow', 0)
        net_pct = fund_data.get('net_pct', 0)

        if main_inflow > 10000000:
            score += cfg['fund_flow_weight']
            reasons.append(f"主力大幅流入 {main_inflow/10000:.0f}万")
        elif main_inflow > 0:
            score += cfg['fund_flow_weight'] * 0.5
            reasons.append(f"主力流入 {main_inflow/10000:.0f}万")
        elif main_inflow < -5000000:
            score -= cfg['fund_flow_weight'] * 0.6
            reasons.append(f"主力大幅流出 {main_inflow/10000:.0f}万")

        if net_pct > 20:
            score += cfg['turnover_weight']
            reasons.append(f"流入出比{net_pct:.1f}%，资金活跃")

        return max(0, min(100, score)), reasons

    def scan_buy_candidates(self, max_candidates: int = 20) -> List[Signal]:
        """扫描买入候选股"""
        signals = []
        self.reload_config()

        # 1. 大盘过滤
        sentiment = self.feed.get_market_sentiment()
        can_trade, market_reason = self.market_filter(sentiment)
        print(f"[策略] 市场状态: {market_reason}")
        if not can_trade:
            return []

        market_mode, market_score, market_mode_reason = self._compute_market_mode(sentiment)
        sentiment_cycle = self._detect_sentiment_cycle(sentiment)
        print(f"[策略] 市场模式: {market_mode_reason} | 情绪周期: {sentiment_cycle}")

        # 2. 获取全市场数据
        spot_df = self.feed.get_stock_spot()
        if spot_df.empty:
            return []

        cfg = self.cfg
        dyn = self._dynamic_thresholds(spot_df)

        # 基础过滤
        spot_df = spot_df[
            ~spot_df['名称'].str.contains('ST|N|C|U|W', na=False) &
            spot_df['代码'].str.match(r'^(00|60|30)') &
            spot_df['市净率'] > 0
        ].copy()

        # 初筛
        has_ratio = '量比' in spot_df.columns and spot_df['量比'].max() > 0
        if has_ratio:
            spot_df = spot_df[
                (spot_df['涨幅'] >= dyn['min_change']) &
                (spot_df['涨幅'] <= dyn['max_change']) &
                (spot_df['换手'] >= dyn['min_turnover']) &
                (spot_df['换手'] <= dyn['max_turnover']) &
                (spot_df['量比'] >= dyn['min_ratio'])
            ].sort_values('量比', ascending=False).head(50)
        else:
            spot_df = spot_df[
                (spot_df['涨幅'] >= dyn['min_change']) &
                (spot_df['涨幅'] <= dyn['max_change']) &
                (spot_df['换手'] >= dyn['min_turnover']) &
                (spot_df['换手'] <= dyn['max_turnover'])
            ].sort_values('换手', ascending=False).head(50)

        print(f"[策略] 初筛候选股: {len(spot_df)}只")

        # 3. 逐一评分
        for _, row in spot_df.iterrows():
            code = str(row['代码']).zfill(6)
            name = row['名称']
            current_price = float(row['最新价'])

            try:
                hist = self.feed.get_stock_hist(code, days=60)
                tech_score, tech_reasons = self.calc_technical_score(hist)

                fund_data = self.feed.get_stock_fund_flow(code)
                fund_score, fund_reasons = self.calc_fund_score(fund_data)

                # 换手率评分
                turnover = float(row.get('换手', 0))
                if cfg['min_turnover'] <= turnover <= cfg['max_turnover']:
                    tech_score += cfg['turnover_score_weight']
                    tech_reasons.append(f"换手率{turnover:.1f}%，活性适中")

                # 板块加分
                sector_bonus = 0
                for sector in sentiment.get('top_sectors', [])[:5]:
                    if sector.get('板块', '') in name:
                        sector_bonus = cfg['sector_bonus']
                        break

                # === V3.0 新增：6套公式检测 + 龙头评分 ===
                formula_sigs = self.detect_formulas(hist)
                leader = self.evaluate_leader(row, hist)

                # 龙头门槛过滤：防守模式放宽到潜力龙头，其余模式保留⭐以上
                leader_floor = 2 if market_mode == 'defense' else 3
                if leader['score'] < leader_floor:
                    continue

                formula_names = [s['type'] for s in formula_sigs]
                if formula_names and not self._formula_allowed(formula_names, market_mode, sentiment_cycle):
                    continue

                # === UZI 集成：51位投资大佬评审 ===
                uzi_bonus = 0
                uzi_reasons = []
                try:
                    from uzi_integration import quick_uzi_score
                    uzi_boost, uzi_signal, uzi_reasons = quick_uzi_score(
                        code, name, self._df_to_kline(hist) if not hist.empty else [],
                        {'换手': float(row.get('换手', 0)), '总市值': float(row.get('总市值', 0))},
                        market_sentiment=sentiment  # 传递市场情绪数据用于 UZI 情绪温度计算
                    )
                    uzi_bonus = uzi_boost
                    if uzi_reasons:
                        tech_reasons.append(f"UZI评审: {', '.join(uzi_reasons[:2])}")
                except Exception as e:
                    print(f"[UZI] {code} 评分失败: {e}")

                # 公式加分
                formula_bonus = 0
                if formula_sigs:
                    formula_weight = cfg.get('formula_weight', 3)
                    formula_bonus = len(formula_sigs) * formula_weight
                    tech_reasons.append(f"触发{len(formula_sigs)}套公式: {', '.join(formula_names)}")

                # 龙头加分 (整合 leader-stock-identification 技能)
                leader_bonus = 0
                if leader['score'] >= 3:
                    leader_weight = cfg.get('leader_weight', 2)
                    leader_bonus = leader['score'] * leader_weight
                    tech_reasons.append(f"龙头: {leader['grade']} ({', '.join(leader['reasons'][:2])})")
                
                # 技术评分加成 (来自 a-stock-kline-analyzer 的 TI.kline_score)
                tech_ev_bonus = 0
                tech_ev = leader.get('tech_score_ev', 0)
                if tech_ev >= 3:
                    tech_ev_bonus = 3
                    tech_reasons.append(f"技术评分强({tech_ev:+.1f})")
                elif tech_ev >= 1.5:
                    tech_ev_bonus = 1.5
                    tech_reasons.append(f"技术评分偏多({tech_ev:+.1f})")

                gate_ok, reds, yellows, greens = self._tier_gate_pass(
                    row, tech_score, fund_score, formula_names, leader, market_mode
                )
                if not gate_ok:
                    continue

                total_score = tech_score + fund_score + sector_bonus + formula_bonus + leader_bonus + len(greens) + uzi_bonus + tech_ev_bonus
                threshold = cfg['buy_score_threshold_defense'] if market_mode == 'defense' else cfg['buy_score_threshold']

                if total_score >= threshold:
                    reasons = tech_reasons + fund_reasons
                    reasons.extend([f"红色: {x}" for x in reds])
                    reasons.extend([f"黄色: {x}" for x in yellows])
                    reasons.extend([f"绿色: {x}" for x in greens])
                    reasons.append(f"市场模式: {market_mode} / 情绪周期: {sentiment_cycle} / 模式分:{market_score}")
                    if uzi_bonus != 0:
                        reasons.append(f"UZI加分: {uzi_bonus:+.1f} (游资:{uzi_signal})")
                    if sector_bonus > 0:
                        reasons.append("属于当日热点板块")

                    ratio = cfg['min_position_ratio'] if total_score < 65 else cfg['single_position_ratio']

                    signals.append(Signal(
                        code=code, name=name, action='BUY',
                        score=total_score, reasons=reasons,
                        current_price=current_price, suggested_ratio=ratio,
                        formulas=[s['type'] for s in formula_sigs],
                        leader_grade=leader['grade'],
                        leader_score=leader['score']
                    ))
            except Exception as e:
                print(f"[策略] {code} 评分异常: {e}")
                continue

        signals.sort(key=lambda x: x.score, reverse=True)

        # 打印公式/龙头统计
        if signals:
            has_formula = sum(1 for s in signals if s.formulas)
            has_leader = sum(1 for s in signals if s.leader_score >= 3)
            print(f"[V3.0] 公式触发: {has_formula}/{len(signals)} 只 | 龙头过关: {has_leader}/{len(signals)} 只")

        return signals[:max_candidates]

    def check_sell_signals(self, positions: List[Dict], current_prices: Dict[str, float]) -> List[Signal]:
        """检查持仓股票的卖出信号"""
        signals = []
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        self.reload_config()
        cfg = self.cfg

        for pos in positions:
            code = pos['code']
            name = pos['name']
            buy_price = pos['buy_price']
            current_price = current_prices.get(code, pos['current_price'])
            highest_price = pos['highest_price']
            half_sold = pos['half_sold']
            buy_date = pos['buy_date']

            if current_price <= 0:
                continue

            pnl_pct = (current_price - buy_price) / buy_price
            reasons = []
            action = None

            # 1. 止损
            if pnl_pct <= cfg['stop_loss']:
                action = 'SELL'
                reasons.append(f"触发止损 {pnl_pct:.2%}")

            # 2. 止盈一半
            elif pnl_pct >= cfg['take_profit_half'] and not half_sold:
                action = 'SELL_HALF'
                reasons.append(f"涨幅{pnl_pct:.2%}，止盈一半")

            # 3. 移动止盈剩余
            elif half_sold and highest_price > buy_price * (1 + cfg['take_profit_half']):
                pullback_pct = (highest_price - current_price) / highest_price
                if pullback_pct >= cfg['take_profit_trail']:
                    action = 'SELL'
                    reasons.append(f"从最高点回落{pullback_pct:.2%}，清仓")

            # 4. 时间止损
            if action is None:
                try:
                    hold_days = (datetime.strptime(today_str, '%Y-%m-%d') -
                                datetime.strptime(buy_date, '%Y-%m-%d')).days
                    if hold_days >= cfg['max_hold_days'] and pnl_pct < 0:
                        action = 'SELL'
                        reasons.append(f"持股{hold_days}天未盈利，时间止损")
                except:
                    pass

            if action:
                signals.append(Signal(
                    code=code, name=name, action=action, score=100,
                    reasons=reasons, current_price=current_price, suggested_ratio=0
                ))

        return signals
