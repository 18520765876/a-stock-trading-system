#!/bin/bash
# 盘后选股脚本 - 17:00执行
# 完整选股扫描 + UZI-Skill深度分析 + 保存次日候选池
source /home/agentuser/.venv/astock/bin/activate
cd /home/agentuser/.hermes/astock-trader
python main.py postmarket_pick 2>&1 | tee -a logs/postmarket_pick.log
