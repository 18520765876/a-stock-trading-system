import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch as mock_patch

from account import Account
from executor import Executor


class TestExecutorNoIntradayBuy(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.account_path = os.path.join(self.tmpdir.name, 'account.json')
        self.account = Account(account_file=self.account_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_signal(self):
        return SimpleNamespace(
            code='000001',
            name='平安银行',
            current_price=10.0,
            score=88,
            reasons=['箱体突破', '放量'],
            formulas=['XG1箱体突破V2'],
            leader_grade='🏆 真龙级',
            leader_score=5,
        )

    def test_run_scan_at_picker_time_saves_candidates_but_does_not_buy(self):
        fake_now = datetime(2026, 4, 27, 9, 0)
        with mock_patch('executor.Account', return_value=self.account), \
             mock_patch('executor.datetime') as mock_datetime:
            mock_datetime.now.return_value = fake_now
            executor = Executor()
            executor._update_positions = MagicMock()
            executor._check_sells = MagicMock(return_value=[])
            executor._check_buys = MagicMock(return_value=[self._make_signal()])
            executor._save_candidates = MagicMock()
            executor._execute_buy = MagicMock()
            executor.account.save = MagicMock()

            executor.run_scan()

            executor._check_buys.assert_called_once()
            executor._save_candidates.assert_called_once()
            executor._execute_buy.assert_not_called()
            self.assertEqual(len(executor.account.positions), 0)


if __name__ == '__main__':
    unittest.main()
