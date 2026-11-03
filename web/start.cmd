@echo off
cd /d "%~dp0"
python -X utf8 -B host\ai_workbench.py --data data --port 8765 --enable-benchmarks
pause
