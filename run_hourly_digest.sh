#!/bin/bash
source /home/agentuser/.venv/astock/bin/activate
cd /home/agentuser/.hermes/astock-trader
python hourly_digest.py 2>&1 | tee -a logs/hourly_digest.log
