#!/bin/bash
# 交易扫描脚本 - 盘中执行（卖出监控为主）
# 09:00/14:30 选股时间点会执行完整扫描并保存候选池
source /home/agentuser/.venv/astock/bin/activate
cd /home/agentuser/.hermes/astock-trader
python main.py scan 2>&1 | tee -a logs/scan.log
