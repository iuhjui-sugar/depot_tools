@echo off
setlocal
if not defined EDITOR set EDITOR=notepad
set PATH=${GIT_BIN_ABSDIR}\cmd;%~dp0;%PATH%
"${GIT_BIN_ABSDIR}\${GIT_PROGRAM}" %*
