@echo off
if not defined ZIG_EXE set "ZIG_EXE=zig"
"%ZIG_EXE%" ar %*
exit /b %errorlevel%
