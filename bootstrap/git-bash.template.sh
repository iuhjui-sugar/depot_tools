#!/usr/bin/env bash
export EDITOR=${EDITOR:=notepad}
WIN_BASE=`dirname $0`
UNIX_BASE=`cygpath "$WIN_BASE"`
UNIX_GIT_BIN_ABSDIR=`cygpath "${GIT_BIN_ABSDIR}"`
export PATH="$PATH:$UNIX_BASE/${PYTHON3_BIN_RELDIR_UNIX}:$UNIX_BASE/${PYTHON3_BIN_RELDIR_UNIX}/Scripts"
export PYTHON_DIRECT=1
export PYTHONUNBUFFERED=1
if [[ $# > 0 ]]; then
  $UNIX_GIT_BIN_ABSDIR/bin/bash.exe "$@"
else
  $UNIX_GIT_BIN_ABSDIR/git-bash.exe &
fi
