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
        """执行一次扫描 - 09:00轻量确认(隔夜验证)/14:30尾盘选股/其他时间仅卖出监控"""
        now = datetime.now()
        time_str = now.strftime('%H:%M')
        
        # 判断当前时段
        is_premarket = (time_str == '09:00')
        is_closing_pick = (time_str == '14:30')
        
        print(f"\n{'='*60}")
        print(f"[执行器] {now.strftime('%Y-%m-%d %H:%M:%S')} 开始扫描")
        print(f"[执行器] 当前策略版本: v{self.evolver.config.get('version', 1)}")
        
        if is_premarket:
            print(f"[执行器] 🌅 盘前轻量确认：验证昨日盘后候选池有效性")
        elif is_closing_pick:
            print(f"[执行器] ⭐ 尾盘选股时间点：执行轻量化扫描")
        else:
            print(f"[执行器] 非选股时间，仅执行卖出监控")
        print(f"{'='*60}")

        # 1. 更新持仓价格
        self._update_positions()

        # 2. 检查卖出信号（所有时间都执行）
        sell_signals = self._check_sells()
        for sig in sell_signals:
            self._execute_sell(sig)

        # 3. 处理买入候选
        if is_premarket:
            # 09:00：轻量确认（读取昨日盘后候选池，验证隔夜有效性）
            self._run_premarket_confirm()
        elif is_closing_pick:
            # 14:30：尾盘选股（轻量化扫描）
            buy_signals = self._check_buys()
            for sig in buy_signals:
                sig.signal_source = '尾盘票'
            self._save_candidates(buy_signals, '尾盘选股')
            print(f"[执行器] 尾盘选股仅保存候选池，不执行盘中买入；唯一买点为14:45尾盘确认")
        else:
            print(f"[执行器] 非选股时间，跳过买入扫描")

        # 4. 保存状态
        self.account.save()
        print(f"[执行器] 扫描完成，总资产: ¥{self.account.total_asset:,.2f}")

    def _run_premarket_confirm(self):
        """09:00盘前轻量确认：读取昨日盘后候选池，验证隔夜有效性"""
        import json, os
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 读取昨日盘后候选池
        candidates_file = f'/tmp/candidates_{today_str}.json'
        if not os.path.exists(candidates_file):
            print(f"[盘前确认] ⚠️ 昨日盘后候选池不存在: {candidates_file}")
            print(f"[盘前确认] 跳过确认，等待14:30尾盘选股")
            return
        
        try:
            with open(candidates_file, 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[盘前确认] ⚠️ 读取候选池失败: {e}")
            return
        
        # 获取盘后候选股
        postmarket = data.get('盘后选股(带UZI)', [])
        if not postmarket:
            print(f"[盘前确认] ⚠️ 盘后候选池为空")
            return
        
        print(f"[盘前确认] 读取到昨日盘后候选池: {len(postmarket)}只")
        
        # 轻量验证：检查隔夜是否有重大利空/公告/异动
        # 1. 获取今日开盘价对比昨日收盘价
        spot_df = self.strategy.feed.get_stock_spot()
        if spot_df.empty:
            print(f"[盘前确认] ⚠️ 无法获取实时行情，跳过验证")
            return
        
        confirmed = []
        rejected = []
        
        for candidate in postmarket:
            code = candidate.get('code', '')
            name = candidate.get('name', '')
            
            # 查找今日行情
            match = spot_df[spot_df['代码'] == code]
            if match.empty:
                print(f"[盘前确认] ⚠️ {name}({code}) 无行情数据，保留候选")
                confirmed.append(candidate)
                continue
            
            row = match.iloc[0]
            current_price = float(row.get('最新价', 0))
            yesterday_close = float(row.get('昨收', 0))
            
            if yesterday_close <= 0:
                confirmed.append(candidate)
                continue
            
            # 计算隔夜涨跌幅
            overnight_change = (current_price - yesterday_close) / yesterday_close * 100
            
            # 轻量过滤条件
            if overnight_change < -5:
                # 隔夜大跌>5%，可能有利空，剔除
                rejected.append({**candidate, 'reject_reason': f'隔夜大跌{overnight_change:.1f}%'})
                print(f"[盘前确认] ❌ {name}({code}) 隔夜大跌{overnight_change:.1f}%，剔除")
            elif overnight_change > 9:
                # 隔夜涨停（一字板），无法买入，剔除
                rejected.append({**candidate, 'reject_reason': f'隔夜涨停{overnight_change:.1f}%'})
                print(f"[盘前确认] ❌ {name}({code}) 隔夜涨停{overnight_change:.1f}%，无法买入，剔除")
            else:
                confirmed.append(candidate)
                print(f"[盘前确认] ✅ {name}({code}) 隔夜变化{overnight_change:+.1f}%，保留")
        
        print(f"[盘前确认] 验证完成: 保留{len(confirmed)}只 / 剔除{len(rejected)}只")
        
        # 保存确认后的候选池
        confirmed_data = {
            '盘后选股(带UZI)': confirmed,
            '盘前确认剔除': rejected,
            'confirmed_at': today_str
        }
        with open(candidates_file, 'w') as f:
            json.dump(confirmed_data, f, ensure_ascii=False, indent=2)
        
        # 生成盘前确认报告
        self._send_premarket_confirm_report(confirmed, rejected, today_str)

    def _send_premarket_confirm_report(self, confirmed, rejected, today_str):
        """发送盘前确认报告"""
        lines = [
            f"🌅 **{today_str} 盘前轻量确认报告**",
            f"",
            f"📊 隔夜验证结果:",
            f"  • 盘后候选: {len(confirmed) + len(rejected)}只",
            f"  • 验证保留: {len(confirmed)}只",
            f"  • 验证剔除: {len(rejected)}只",
            f"",
        ]
        
        if confirmed:
            lines.append("✅ **保留候选（等待14:45二次确认）:**")
            for i, c in enumerate(confirmed[:5], 1):
                uzi_v = c.get('uzi_verdict', 'N/A')
                formula_str = " | ".join(c.get('formulas', [])) or "无"
                lines.append(f"{i}. **{c.get('name')}**({c.get('code')}) 原评分:{c.get('score', 0):.0f} UZI:{uzi_v}")
                lines.append(f"   📝 公式: {formula_str}")
            if len(confirmed) > 5:
                lines.append(f"… 其余 {len(confirmed)-5} 只")
        else:
            lines.append("⚠️ 无保留候选，等待14:30尾盘选股")
        
        if rejected:
            lines.append("")
            lines.append("❌ **剔除原因:**")
            for r in rejected[:3]:
                lines.append(f"  • {r.get('name')}({r.get('code')}): {r.get('reject_reason', '')}")
        
        # 写入微信推送文件
        wechat_file = f'/tmp/wechat_premarket_{today_str}.md'
        with open(wechat_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"[盘前确认] 报告已生成: {wechat_file}")
        
        # 直接推送
        self.notifier._send('\n'.join(lines), "text")

    def run_postmarket_pick(self):
        """盘后选股：17:00执行，完整扫描 + UZI-Skill深度分析 + 保存次日候选池"""
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        next_date = (now + timedelta(days=1)).strftime('%Y-%m-%d')

        print(f"\n{'='*60}")
        print(f"[盘后选股] {now.strftime('%Y-%m-%d %H:%M:%S')} 开始盘后选股")
        print(f"[盘后选股] 当前策略版本: v{self.evolver.config.get('version', 1)}")
        print(f"[盘后选股] 目标：为 {next_date} 生成候选池（带UZI深度分析）")
        print(f"{'='*60}")

        # 1. 完整选股扫描（同09:00盘前选股逻辑）
        buy_signals = self._check_buys()
        print(f"[盘后选股] 初选候选股: {len(buy_signals)}只")

        if not buy_signals:
            print(f"[盘后选股] 无候选股，跳过UZI分析")
            self._save_postmarket_candidates([], today_str, next_date)
            return

        # 2. UZI-Skill 深度分析（全量pipeline）
        print(f"[盘后选股] 开始对 {len(buy_signals)} 只候选股执行UZI深度分析...")
        uzi_passed = []
        uzi_rejected = []

        for sig in buy_signals:
            try:
                from uzi_integration import full_uzi_analysis
                uzi_result = full_uzi_analysis(
                    code=sig.code,
                    name=sig.name,
                    kline=self.strategy._df_to_kline(self.strategy.feed.get_stock_hist(sig.code, days=60)),
                    spot_data={
                        '换手': sig.current_price,  # 需要实际换手率，这里用价格占位
                        '总市值': 0,
                    },
                    market_sentiment=self.strategy.feed.get_market_sentiment()
                )

                # UZI结果解析
                uzi_score = uzi_result.get('score', 0)
                uzi_verdict = uzi_result.get('verdict', 'UNKNOWN')
                uzi_details = uzi_result.get('details', {})

                # 记录UZI分析结果（用于进化归因）
                sig.uzi_score = uzi_score
                sig.uzi_verdict = uzi_verdict
                sig.uzi_details = uzi_details

                if uzi_verdict in ['STRONG_BUY', 'BUY']:
                    uzi_passed.append(sig)
                    print(f"[UZI] ✅ {sig.name}({sig.code}) 通过: {uzi_verdict} 评分:{uzi_score:.1f}")
                else:
                    uzi_rejected.append(sig)
                    print(f"[UZI] ❌ {sig.name}({sig.code}) 否决: {uzi_verdict} 评分:{uzi_score:.1f}")

            except Exception as e:
                print(f"[UZI] ⚠️ {sig.name}({sig.code}) 分析异常: {e}")
                # 异常时保守处理：不否决，保留候选
                uzi_passed.append(sig)
                sig.uzi_score = 0
                sig.uzi_verdict = 'ERROR_PASS'
                sig.uzi_details = {'error': str(e)}

        print(f"[盘后选股] UZI分析完成: 通过{len(uzi_passed)}只 / 否决{len(uzi_rejected)}只")

        # 3. 保存盘后候选池（含UZI结果，供次日使用）
        self._save_postmarket_candidates(uzi_passed, today_str, next_date, uzi_rejected)

        # 4. 生成盘后选股报告
        self._send_postmarket_report(uzi_passed, uzi_rejected, today_str, next_date)

        print(f"[盘后选股] 完成，次日候选池已保存")

    def _save_postmarket_candidates(self, passed, today_str, next_date, rejected=None):
        """保存盘后选股候选池到文件，供次日09:00/14:45使用"""
        import json, os

        # 主候选池文件
        filepath = f'/tmp/postmarket_candidates_{today_str}.json'
        data = {
            'generated_at': today_str,
            'for_date': next_date,
            'passed': [
                {
                    'code': s.code, 'name': s.name, 'score': s.score,
                    'price': s.current_price, 'reasons': s.reasons,
                    'formulas': s.formulas, 'leader_grade': s.leader_grade,
                    'leader_score': s.leader_score,
                    'uzi_score': getattr(s, 'uzi_score', 0),
                    'uzi_verdict': getattr(s, 'uzi_verdict', ''),
                    'uzi_details': getattr(s, 'uzi_details', {}),
                }
                for s in passed[:10]
            ],
            'rejected': [
                {
                    'code': s.code, 'name': s.name, 'score': s.score,
                    'uzi_score': getattr(s, 'uzi_score', 0),
                    'uzi_verdict': getattr(s, 'uzi_verdict', ''),
                }
                for s in (rejected or [])
            ],
            'stats': {
                'total_scanned': len(passed) + len(rejected or []),
                'uzi_passed': len(passed),
                'uzi_rejected': len(rejected or []),
            }
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[盘后选股] 候选池已保存: {filepath}")

        # 同时写入次日通用候选池（供09:00轻量确认和14:45使用）
        next_day_file = f'/tmp/candidates_{next_date}.json'
        next_day_data = {'盘后选股(带UZI)': data['passed']}
        with open(next_day_file, 'w') as f:
            json.dump(next_day_data, f, ensure_ascii=False, indent=2)
        print(f"[盘后选股] 次日候选池已写入: {next_day_file}")

    def _send_postmarket_report(self, passed, rejected, today_str, next_date):
        """发送盘后选股报告"""
        lines = [
            f"📋 **{today_str} 盘后选股报告**",
            f"",
            f"🎯 为 **{next_date}** 生成候选池",
            f"",
            f"📊 UZI深度分析结果:",
            f"  • 初选候选: {len(passed) + len(rejected)}只",
            f"  • UZI通过: {len(passed)}只",
            f"  • UZI否决: {len(rejected)}只",
            f"",
        ]

        if passed:
            lines.append("✅ **UZI通过候选（次日关注）:**")
            for i, s in enumerate(passed[:5], 1):
                uzi_v = getattr(s, 'uzi_verdict', 'N/A')
                uzi_s = getattr(s, 'uzi_score', 0)
                formula_str = " | ".join(s.formulas) if s.formulas else "无"
                lines.append(f"{i}. **{s.name}**({s.code}) 评分:{s.score:.0f} UZI:{uzi_v}({uzi_s:.1f})")
                lines.append(f"   📝 公式: {formula_str} | 👑 {s.leader_grade}")
            if len(passed) > 5:
                lines.append(f"… 其余 {len(passed)-5} 只详见候选池文件")
        else:
            lines.append("⚠️ 无UZI通过候选，次日建议观望")

        # 写入微信推送文件
        wechat_file = f'/tmp/wechat_postmarket_{today_str}.md'
        with open(wechat_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"[盘后选股] 报告已生成: {wechat_file}")

        # 直接推送
        self.notifier._send('\n'.join(lines), "text")

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
