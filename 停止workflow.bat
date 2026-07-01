@echo off
echo 正在查詢 GitHub Actions 執行中的 workflow...
echo.

gh run list --repo Jack20773/stock-signal --status in_progress --limit 5 2>nul
echo.

for /f "tokens=1" %%R in ('gh run list --repo Jack20773/stock-signal --status in_progress --limit 1 --json databaseId --jq ".[0].databaseId" 2^>nul') do (
    set RUN_ID=%%R
)

if not defined RUN_ID (
    echo 目前沒有正在執行的 workflow。
    pause
    exit /b 0
)

echo 即將取消 Run ID: %RUN_ID%
set /p CONFIRM=確定要取消嗎？(y/N)：
if /i "%CONFIRM%" neq "y" (
    echo 已取消操作。
    pause
    exit /b 0
)

gh run cancel %RUN_ID% --repo Jack20773/stock-signal
echo.
echo 已送出取消指令，等幾秒後狀態會更新為 cancelled。
pause
