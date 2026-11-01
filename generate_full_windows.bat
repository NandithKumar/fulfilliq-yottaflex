@echo off
cd /d %~dp0
python -m fulfilliq.cli generate --orders 50000 --nodes 20 --carriers 10 --skus 500 --events 100000 --seed 20261022 --output data/generated
python -m fulfilliq.cli validate --db data/generated/fulfilliq.db --orders 50000 --events 100000
pause
