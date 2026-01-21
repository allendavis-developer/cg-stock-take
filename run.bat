@echo off
set ROOT=%~dp0

"%ROOT%python\python.exe" "%ROOT%app\stocktransfer.py" %*

pause
