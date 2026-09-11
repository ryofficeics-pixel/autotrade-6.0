# Windows Deployment

`scripts/setup_windows.bat` creates a Python 3.12 virtual environment, local API secrets, installs pinned dependencies, validates configuration, and runs tests. `start_autotrade.bat` refuses a duplicate dashboard port, starts the supervisor first, starts Freqtrade hidden, and opens the local dashboard. `stop_autotrade.bat` requests emergency stop and then supervisor shutdown.

For 24/7 use, add the start script to Windows Task Scheduler only after an interactive paper run succeeds. Configure restart on failure, AC power behavior, and sleep settings deliberately. Keep Windows time synchronization enabled. Do not enable automatic dependency upgrades in the trading task.
