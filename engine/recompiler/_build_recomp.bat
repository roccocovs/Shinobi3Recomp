@echo off
setlocal
where cmake >nul 2>nul
if errorlevel 1 (
  echo CMake was not found on PATH. Install CMake and configure this build first.
  exit /b 1
)
cmake --build "%~dp0build" --config Release --target GenesisRecomp
exit /b %errorlevel%
