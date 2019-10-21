@echo off
:: Copyright (c) 2013 The Chromium Authors. All rights reserved.
:: Use of this source code is governed by a BSD-style license that can be
:: found in the LICENSE file.
setlocal

:: Synchronize the root directory before deferring control back to gclient.py.
call "%~dp0\update_depot_tools.bat"

:: Ensure that "depot_tools" is somewhere in PATH so this tool can be used
:: standalone, but allow other PATH manipulations to take priority.
set PATH=%PATH%;%~dp0

:: Defer control.
IF "%GCLIENT_PY3%" == "1" (
  :: TODO(1003139): Use vpython3 once vpython3 works on Windows.
  vpython3 "%~dp0\fetch.py" %*y
) ELSE (
  vpython "%~dp0\fetch.py" %*
)
