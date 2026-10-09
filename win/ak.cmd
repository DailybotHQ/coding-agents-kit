@echo off
rem ak - coding-agents-kit on Windows: runs the python core (lib\ak.py).
rem Same commands as on macOS/Linux; the env file is read as KEY=value lines.
setlocal
set "AGENTKIT_ROOT=%~dp0.."
set "AK_PY=python"
where py >nul 2>nul && set "AK_PY=py -3"
if defined AGENTKIT_PYTHON set "AK_PY=%AGENTKIT_PYTHON%"
%AK_PY% "%AGENTKIT_ROOT%\lib\ak.py" %*
exit /b
