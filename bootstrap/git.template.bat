@echo off
setlocal
if not defined EDITOR set EDITOR=notepad
:: Exclude the current directory and limit the search for executables
:: to PATH. This is required for the SSO helper to run.
set "NoDefaultCurrentDirectoryInExePath=1"
set "PATH=${GIT_BIN_ABSDIR}\cmd;%~dp0;%PATH%"
"${GIT_BIN_ABSDIR}\${GIT_PROGRAM}" %*
