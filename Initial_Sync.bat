@echo off
echo ============================================================
echo INITIAL SYNC TOOL - BATCH VERSION  
echo ============================================================
echo.

cd /d "%~dp0"
python initial_sync.py

echo.
echo ============================================================
echo COMPLETED! You can now run CDC_Replicator.exe
echo ============================================================
pause
