@echo off
rem Copyright 2021 The Chromium Authors. All rights reserved.
rem Use of this source code is governed by a BSD-style license that can be
rem found in the LICENSE file.

setlocal

for %%d in (%~dp0..) do set PARENT_DIR=%%~fd
for /f %%i in (%PARENT_DIR%\python3_bin_reldir.txt) do set PYTHON_BIN_ABSDIR=%PARENT_DIR%\%%i
set PATH=%PYTHON_BIN_ABSDIR%;%PYTHON_BIN_ABSDIR%\Scripts;%PATH%
"%PYTHON_BIN_ABSDIR%\python3.exe" %*