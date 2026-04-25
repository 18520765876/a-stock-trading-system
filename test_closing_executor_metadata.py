import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch as mock_patch

from account import Account
import closing_executor


def make_account_path():
    tmpdir = tempfile.TemporaryDirectory()
    return tmpdir, os.path.join(tmpdir.name, 'account.json')


class TestClosingExecutorMetadata(unittest.TestCase):
    def test_closing_buy_persists_candidate_metadata(self):
        tmpdir, account_path = make_account_path()
        fake_now = datetime(2026, 4, 27, 14, 45)
        with tmpdir:
            account = Account(account_file=account_path)
            with mock_patch.object(closing_executor, 'Account', return_value=account), \
                 mock_patch.object(closing_executor, 'get_index_data', return_value={'sh000001': {'change': 0.2}}), \
                 mock_patch.object(closing_executor, 'get_stock_spot', return_value=[{
                     'code': '000001', 'name': '平安银行', 'change': 3.5, 'turnover': 3.2,
                     'price': 10.0, 'open': 9.8, 'high': 10.05, 'low': 9.7,
                 }]), \
                 mock_patch.object(closing_executor, '_print_notification'), \
                 mock_patch.object(closing_executor, 'datetime') as mock_datetime, \
                 mock_patch('closing_executor.os.path.exists', return_value=True), \
                 mock_patch('closing_executor.open', create=True) as mocked_open, \
                 mock_patch('closing_executor.json.load', return_value={
                     '盘前选股': [{
                         'code': '000001', 'name': '平安银行', 'score': 88,
                         'price': 9.9, 'reasons': ['箱体突破', '放量'],
                         'formulas': ['XG1箱体突破V2'],
                         'signal_source': '盘前票',
                         'leader_grade': '🏆 真龙级',
                         'leader_score': 5,
                     }]
                 }):
                mock_datetime.now.return_value = fake_now
                mocked_open.return_value.__enter__.return_value.read.return_value = '{}'
                closing_executor.execute_closing()

            summary = account.get_position_summary()
            self.assertEqual(len(summary), 1)
            self.assertEqual(summary[0]['formulas'], ['XG1箱体突破V2'])
            self.assertEqual(summary[0]['signal_source'], '盘前票')
            self.assertEqual(summary[0]['leader_grade'], '🏆 真龙级')
            self.assertEqual(summary[0]['leader_score'], 5)
            self.assertEqual(summary[0]['entry_reasons'], ['箱体突破', '放量'])


if __name__ == '__main__':
    unittest.main()
