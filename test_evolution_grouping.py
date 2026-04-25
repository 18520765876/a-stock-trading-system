import os
import tempfile
import unittest
from unittest.mock import MagicMock

from account import Account
from executor import Executor
from strategy import Signal
from trade_analyzer import TradeAnalyzer


def make_account_path():
    tmpdir = tempfile.TemporaryDirectory()
    return tmpdir, os.path.join(tmpdir.name, 'account.json')


class TestBuyMetadataPersistence(unittest.TestCase):
    def test_account_buy_persists_entry_metadata_into_position_summary(self):
        tmpdir, account_path = make_account_path()
        with tmpdir:
            account = Account(account_file=account_path)
            trade = account.buy(
                code='000001',
                name='平安银行',
                price=10.0,
                ratio=0.1,
                date_str='2026-04-25',
                metadata={
                    'entry_reasons': ['箱体突破', '放量'],
                    'formulas': ['XG1箱体突破V2'],
                    'signal_source': '盘前票',
                    'leader_grade': '🏆 真龙级',
                    'leader_score': 5,
                },
            )
            self.assertIsNotNone(trade)

            summary = account.get_position_summary()
            self.assertEqual(summary[0]['entry_reasons'], ['箱体突破', '放量'])
            self.assertEqual(summary[0]['formulas'], ['XG1箱体突破V2'])
            self.assertEqual(summary[0]['signal_source'], '盘前票')
            self.assertEqual(summary[0]['leader_grade'], '🏆 真龙级')
            self.assertEqual(summary[0]['leader_score'], 5)

    def test_executor_sell_analysis_passes_buy_metadata(self):
        tmpdir, account_path = make_account_path()
        with tmpdir:
            executor = Executor()
            executor.account = Account(account_file=account_path)
            executor.account.buy(
                code='000001',
                name='平安银行',
                price=10.0,
                ratio=0.1,
                date_str='2026-04-25',
                metadata={
                    'entry_reasons': ['箱体突破'],
                    'formulas': ['XG1箱体突破V2'],
                    'signal_source': '盘前票',
                    'leader_grade': '🏆 真龙级',
                    'leader_score': 5,
                },
            )
            executor.today_str = '2026-04-26'
            executor.analyzer = MagicMock()
            executor.notifier = MagicMock()
            executor.strategy = MagicMock()
            executor.strategy.feed.get_market_sentiment.return_value = {'up_ratio': 0.6}

            sell_signal = Signal(
                code='000001', name='平安银行', action='SELL', score=100,
                reasons=['跌破MA20'], current_price=11.0, suggested_ratio=0,
            )
            executor._execute_sell(sell_signal)

            _, kwargs = executor.analyzer.analyze_trade.call_args
            position = kwargs['position']
            self.assertEqual(position['entry_reasons'], ['箱体突破'])
            self.assertEqual(position['formulas'], ['XG1箱体突破V2'])
            self.assertEqual(position['signal_source'], '盘前票')
            self.assertEqual(position['leader_grade'], '🏆 真龙级')
            self.assertEqual(position['leader_score'], 5)


class TestTradeAnalyzerGrouping(unittest.TestCase):
    def test_performance_summary_includes_grouped_breakdowns(self):
        analyzer = TradeAnalyzer()
        analyzer.analyses = [
            {
                'trade_id': '1', 'code': '000001', 'name': 'A', 'action': 'SELL_ALL',
                'pnl': 1000, 'pnl_pct': 0.10, 'hold_days': 2, 'market_condition': 'bull',
                'diagnosis': 'good', 'lessons': ['大赢交易，记录入场时的市场条件作为成功模式'],
                'formulas': ['XG1箱体突破V2'], 'signal_source': '盘前票', 'leader_grade': '🏆 真龙级'
            },
            {
                'trade_id': '2', 'code': '000002', 'name': 'B', 'action': 'SELL_ALL',
                'pnl': -500, 'pnl_pct': -0.05, 'hold_days': 3, 'market_condition': 'bear',
                'diagnosis': 'bad', 'lessons': ['勿在弱市中主动买入，等待大盘企稳'],
                'formulas': ['XG2回踩共振V2'], 'signal_source': '尾盘票', 'leader_grade': '⭐ 强势龙头'
            },
            {
                'trade_id': '3', 'code': '000003', 'name': 'C', 'action': 'SELL_ALL',
                'pnl': 300, 'pnl_pct': 0.03, 'hold_days': 1, 'market_condition': 'neutral',
                'diagnosis': 'ok', 'lessons': ['无特殊教训'],
                'formulas': ['XG1箱体突破V2'], 'signal_source': '盘前票', 'leader_grade': '🏆 真龙级'
            },
        ]

        summary = analyzer.get_performance_summary()

        self.assertIn('group_breakdowns', summary)
        self.assertEqual(summary['group_breakdowns']['signal_source']['盘前票']['count'], 2)
        self.assertAlmostEqual(summary['group_breakdowns']['signal_source']['盘前票']['win_rate'], 1.0)
        self.assertEqual(summary['group_breakdowns']['formula']['XG1箱体突破V2']['count'], 2)
        self.assertEqual(summary['group_breakdowns']['leader_grade']['🏆 真龙级']['count'], 2)


if __name__ == '__main__':
    unittest.main()
