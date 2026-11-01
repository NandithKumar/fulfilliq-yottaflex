@echo off
cd /d %~dp0
python -m fulfilliq.cli serve
pause
