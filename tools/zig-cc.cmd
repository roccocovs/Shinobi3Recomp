@echo off
if not defined ZIG_EXE set "ZIG_EXE=zig"
"%ZIG_EXE%" cc -target x86_64-windows-gnu %*
exit /b %errorlevel%
