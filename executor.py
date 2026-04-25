"""
交易执行器 (自进化版)
负责将策略信号转化为实际交易，并推送通知
集成交易分析和策略进化
"""
import sys
sys.path.insert(0, '/home/agentuser/.venv/astock/lib/python3.11/site-packages')
sys.path.insert(0, '/home/agentuser/.hermes/astock-trader')

from datetime import datetime, timedelta
from typing import List, Dict
from account import Account
from strategy import Strategy
from notifier import Notifier
from trade_analyzer import TradeAnalyzer
from strategy_evolver import StrategyEvolver
from config import MAX_POSITIONS, SINGLE_POSITION_RATIO, MIN_POSITION_RATIO, INITIAL_CAPITAL, FIXED_TRADE_AMOUNT

class Executor:
    def __init__(self):
        self.account = Account()
        self.strategy = Strategy()
        self.notifier = Notifier()
        self.analyzer = TradeAnalyzer()
        self.evolver = StrategyEvolver()
        self.today_str = datetime.now().strftime('%Y-%m-%d')

    def run_scan(self):
        """执行一次扫描 - 选股时间点(09:00/14:30)做完整扫描+保存候选池，其他时间只做卖出监控"""
        now = datetime.now()
        time_str = now.strftime('%H:%M')
        is_picker_time = (time_str == '09:00' or time_str == '14:30')

        print(f"\n{'='*60}")
        print(f"[执行器] {now.strftime('%Y-%m-%d %H:%M:%S')} 开始扫描")
        print(f"[执行器] 当前策略版本: v{self.evolver.config.get('version', 1)}")
        if is_picker_time:
            source = '盘前选股' if time_str == '09:00' else '尾盘选股'
            print(f"[执行器] ⭐ 选股时间点: {source}，执行完整扫描并保存候选池")
        else:
            print(f"[执行器] 非选股时间，仅执行卖出监控")
        print(f"{'='*60}")

        # 1. 更新持仓价格
        self._update_positions()

        # 2. 检查卖出信号（所有时间都执行）
        sell_signals = self._check_sells()
        for sig in sell_signals:
            self._execute_sell(sig)

        # 3. 检查买入信号（仅在 09:00 和 14:30 执行选股）
        if is_picker_time:
            buy_signals = self._check_buys()
            for sig in buy_signals:
                sig.signal_source = source.replace('选股', '票')
            # 保存候选池到文件（供14:45二次确认使用）
            self._save_candidates(buy_signals, source)
            print(f"[执行器] {source}仅保存候选池，不执行盘中买入；唯一买点为14:45尾盘确认")
        else:
            print(f"[执行器] 非选股时间，跳过买入扫描")

        # 4. 保存状态
        self.account.save()
        print(f"[执行器] 扫描完成，总资产: ¥{self.account.total_asset:,.2f}")

    def _save_candidates(self, signals, source):
        """保存候选池到文件，供14:45二次确认使用；同时生成微信推送文件"""
        import json, os
        today_str = datetime.now().strftime('%Y-%m-%d')
        filepath = f'/tmp/candidates_{today_str}.json'

        # 读取已有数据
        data = {}
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
            except:
                pass

        # 保存当前候选池
        data[source] = [
            {
                'code': s.code,
                'name': s.name,
                'score': s.score,
                'price': s.current_price,
                'reasons': s.reasons,
                'formulas': s.formulas,
                'leader_grade': s.leader_grade,
                'leader_score': s.leader_score,
            }
            for s in signals[:10]  # 最多保存10只
        ]

        with open(filepath, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[执行器] 已保存 {source} 候选池: {len(signals)} 只 → {filepath}")

        # === V3.0 新增：生成微信推送文件 ===
        # 盘前选股和尾盘选股分别写入不同文件，避免覆盖
        if source == '盘前选股':
            wechat_file = f'/tmp/wechat_premarket_{today_str}.md'
            lines = [f"🚀 **{today_str} 盘前选股报告**", ""]
        else:
            wechat_file = f'/tmp/wechat_closepick_{today_str}.md'
            lines = [f"🚀 **{today_str} 尾盘选股报告**", ""]
        
        if signals:
            formula_hit = sum(1 for s in signals if s.formulas)
            leader_hit = sum(1 for s in signals if s.leader_score >= 3)
            top_formulas = {}
            for s in signals:
                for f in (s.formulas or []):
                    top_formulas[f] = top_formulas.get(f, 0) + 1
            formula_summary = ' | '.join(
                f"{k}({v})" for k, v in sorted(top_formulas.items(), key=lambda x: -x[1])[:3]
            ) or '无明显集中公式'

            lines.append(f"🎯 筛选结果: 通过{len(signals)}只 | 公式触发{formula_hit}只 | 龙头过关{leader_hit}只")
            lines.append(f"🧠 公式分布: {formula_summary}")
            lines.append("")
            for i, s in enumerate(signals[:3], 1):
                formula_str = " | ".join(s.formulas) if s.formulas else "无"
                lines.append(f"{i}. **{s.name}**({s.code}) @ ¥{s.current_price:.2f} 评分:{s.score:.0f}")
                lines.append(f"   👑 {s.leader_grade} | 📝 公式: {formula_str}")
                lines.append(f"   📊 {'; '.join(s.reasons[:2])}")
                lines.append("")
            if len(signals) > 3:
                lines.append(f"…其余{len(signals)-3}只已写入候选池，等待14:45统一二次确认，不在消息中展开。")
        else:
            lines.append("⚠️ 暂无符合条件的个股，建议观望。")
        
        with open(wechat_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"[执行器] 已生成微信推送文件: {wechat_file}")

    def _update_positions(self):
        """更新持仓股票实时价格"""
        if not self.account.positions:
            return

        spot_df = self.strategy.feed.get_stock_spot()
        if spot_df.empty:
            return

        price_map = {}
        for code in self.account.positions:
            match = spot_df[spot_df['代码'] == code]
            if not match.empty:
                price_map[code] = float(match.iloc[0]['最新价'])

        self.account.update_prices(price_map)
        print(f"[执行器] 已更新 {len(price_map)}/{len(self.account.positions)} 只持仓股价")

    def _check_sells(self) -> List:
        """检查卖出信号"""
        if not self.account.positions:
            return []

        positions = self.account.get_position_summary()
        current_prices = {code: pos.current_price for code, pos in self.account.positions.items()}

        signals = self.strategy.check_sell_signals(positions, current_prices)
        print(f"[执行器] 检测到 {len(signals)} 个卖出信号")
        return signals

    def _check_buys(self) -> List:
        """检查买入信号"""
        signals = self.strategy.scan_buy_candidates(max_candidates=10)
        # 过滤已持有的股票
        existing = set(self.account.positions.keys())
        signals = [s for s in signals if s.code not in existing]
        print(f"[执行器] 检测到 {len(signals)} 个买入信号")
        return signals

    def _execute_buy(self, signal):
        """执行买入"""
        ratio = self.evolver.get_current_config().get('single_position_ratio', SINGLE_POSITION_RATIO)
        pre_injected = self.account.injected_capital
        trade = self.account.buy(
            code=signal.code,
            name=signal.name,
            price=signal.current_price,
            ratio=ratio,
            date_str=self.today_str,
            metadata={
                'entry_reasons': signal.reasons,
                'formulas': signal.formulas,
                'signal_source': getattr(signal, 'signal_source', ''),
                'leader_grade': signal.leader_grade,
                'leader_score': signal.leader_score,
            }
        )
        if trade:
            injected_now = self.account.injected_capital - pre_injected
            print(f"[执行器] ✅ 买入 {signal.name}({signal.code}) "
                  f"¥{trade.price:.2f}x{trade.shares} 成功")
            if injected_now > 0:
                print(f"[执行器] ↗ 现金不足，已自动扩充股本/注资 ¥{injected_now:,.2f}")
            self.notifier.send_trade(
                trade={
                    'code': trade.code, 'name': trade.name, 'action': trade.action,
                    'price': trade.price, 'shares': trade.shares, 'amount': trade.amount,
                    'commission': trade.commission, 'stamp_tax': trade.stamp_tax,
                    'transfer_fee': trade.transfer_fee, 'total_cost': trade.total_cost,
                    'trade_time': trade.trade_time
                },
                account_pnl=self.account.total_pnl,
                account_pnl_pct=self.account.total_pnl_pct,
                extra={
                    'capital_base': self.account.total_capital_base,
                    'injected_capital': self.account.injected_capital,
                    'fixed_trade_amount': FIXED_TRADE_AMOUNT,
                }
            )
        else:
            print(f"[执行器] ❌ 买入 {signal.name}({signal.code}) 失败（资金不足或数量不足）")

    def _execute_sell(self, signal):
        """执行卖出"""
        # 获取交易前的持仓信息用于分析
        pos = self.account.positions.get(signal.code)
        buy_price = pos.buy_price if pos else 0
        hold_days = 1
        if pos:
            try:
                hold_days = (datetime.strptime(self.today_str, '%Y-%m-%d') -
                            datetime.strptime(pos.buy_date, '%Y-%m-%d')).days
            except:
                pass

        trade = self.account.sell(
            code=signal.code,
            price=signal.current_price,
            date_str=self.today_str,
            half=(signal.action == 'SELL_HALF')
        )
        if trade:
            print(f"[执行器] ✅ 卖出 {signal.name}({signal.code}) "
                  f"¥{trade.price:.2f}x{trade.shares} 成功")
            
            # 计算盈亏率
            pnl_pct = (trade.price - buy_price) / buy_price if buy_price > 0 else 0
            
            # 分析交易
            self.analyzer.analyze_trade(
                trade={
                    'trade_id': trade.trade_id,
                    'code': trade.code,
                    'name': trade.name,
                    'action': trade.action,
                    'price': trade.price,
                    'pnl': trade.pnl,
                    'pnl_pct': pnl_pct,
                    'hold_days': hold_days,
                    'reasons': signal.reasons
                },
                position={
                    'buy_price': buy_price,
                    'entry_reasons': getattr(pos, 'entry_reasons', []) if pos else [],
                    'formulas': getattr(pos, 'formulas', []) if pos else [],
                    'signal_source': getattr(pos, 'signal_source', '') if pos else '',
                    'leader_grade': getattr(pos, 'leader_grade', '') if pos else '',
                    'leader_score': getattr(pos, 'leader_score', 0) if pos else 0,
                    'sector': ''
                },
                market_sentiment=self.strategy.feed.get_market_sentiment()
            )
            
            self.notifier.send_trade(
                trade={
                    'code': trade.code, 'name': trade.name, 'action': trade.action,
                    'price': trade.price, 'shares': trade.shares, 'amount': trade.amount,
                    'commission': trade.commission, 'stamp_tax': trade.stamp_tax,
                    'transfer_fee': trade.transfer_fee, 'total_cost': trade.total_cost,
                    'trade_time': trade.trade_time
                },
                account_pnl=self.account.total_pnl,
                account_pnl_pct=self.account.total_pnl_pct,
                extra={
                    'capital_base': self.account.total_capital_base,
                    'injected_capital': self.account.injected_capital,
                    'fixed_trade_amount': FIXED_TRADE_AMOUNT,
                }
            )
        else:
            print(f"[执行器] ❌ 卖出 {signal.name}({signal.code}) 失败")

    def generate_daily_report(self):
        """生成每日报告 (含自进化)"""
        self._update_positions()

        today_trades = [
            t for t in self.account.trades
            if t.trade_time.startswith(self.today_str)
        ]

        # 计算今日盈亏
        yesterday_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_asset = self.account.daily_pnls.get(yesterday_date, INITIAL_CAPITAL)
        today_pnl = self.account.total_asset - yesterday_asset
        self.account.daily_pnls[self.today_str] = self.account.total_asset
        self.account.save()

        # 自进化: 更新模式并尝试进化策略
        self.analyzer.update_patterns()
        evolve_result = self.evolver.evolve(self.analyzer.analyses)
        
        if evolve_result.get('evolved'):
            print(f"[自进化] 策略已进化到 v{evolve_result['version']}")
            print(f"[自进化] 原因: {evolve_result['reason']}")

        # 获取绩效摘要
        perf = self.analyzer.get_performance_summary()
        
        self.notifier.send_daily_report(
            date_str=self.today_str,
            account_data={
                'positions': self.account.get_position_summary(),
                'today_trades': [
                    {
                        'code': t.code, 'name': t.name, 'action': t.action,
                        'price': t.price, 'shares': t.shares
                    }
                    for t in today_trades
                ],
                'cash': self.account.cash,
                'capital_base': self.account.total_capital_base,
                'injected_capital': self.account.injected_capital,
                'fixed_trade_amount': FIXED_TRADE_AMOUNT,
                'total_asset': self.account.total_asset,
                'total_pnl': self.account.total_pnl,
                'total_pnl_pct': self.account.total_pnl_pct,
                'today_pnl': today_pnl
            }
        )
        
        print(f"[执行器] 每日报告已发送，今日盈亏: ¥{today_pnl:+.2f}")
        print(f"[自进化] 当前胜率: {perf.get('win_rate', 0):.1%}")
        
        return evolve_result

    def run_evolution_only(self):
        """只运行自进化分析（非交易时段调用）"""
        print(f"\n{'='*60}")
        print(f"[自进化] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 运行分析")
        print(f"{'='*60}")
        
        self.analyzer.update_patterns()
        evolve_result = self.evolver.evolve(self.analyzer.analyses)
        perf = self.analyzer.get_performance_summary()
        
        print(f"[自进化] 总交易: {perf['total_trades']}, 胜率: {perf['win_rate']:.1%}")
        print(f"[自进化] 盈亏比: {perf.get('profit_factor', 0):.2f}")
        
        if evolve_result.get('evolved'):
            print(f"[自进化] ✓ 策略已进化到 v{evolve_result['version']}")
            print(f"[自进化] 原因: {evolve_result['reason']}")
            self.notifier._send(
                f"⚙️ **策略自进化提醒**\n\n"
                f"策略已升级到 v{evolve_result['version']}\n"
                f"原因: {evolve_result['reason']}\n"
                f"当前胜率: {perf['win_rate']:.1%}",
                "text"
            )
        else:
            print(f"[自进化] ○ {evolve_result['reason']}")

        return evolve_result
