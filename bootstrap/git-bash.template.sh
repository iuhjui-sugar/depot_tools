#!/usr/bin/env bash
export EDITOR=${EDITOR:=notepad}
WIN_BASE=`dirname $0`
UNIX_BASE=`cygpath "$WIN_BASE"`
export PATH="$PATH:$UNIX_BASE/${PYTHON3_BIN_RELDIR_UNIX}:$UNIX_BASE/${PYTHON3_BIN_RELDIR_UNIX}/Scripts"
export PYTHON_DIRECT=1
export PYTHONUNBUFFERED=1
if [[ $# > 0 ]]; then
  "${GIT_BIN_ABSDIR_UNIX}/bin/bash.exe" "$@"
else
  "${GIT_BIN_ABSDIR_UNIX}/git-bash.exe" &
fi
