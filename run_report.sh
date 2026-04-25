#!/bin/bash
source /home/agentuser/.venv/astock/bin/activate
cd /home/agentuser/.hermes/astock-trader
python main.py report 2>&1 | tee -a logs/report.log
