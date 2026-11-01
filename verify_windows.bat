@echo off
cd /d %~dp0
python -m fulfilliq.cli validate --orders 250 --events 500
python -m pytest -q
pause
