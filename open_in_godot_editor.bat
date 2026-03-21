@echo off
REM Opens this folder as a Godot 4.x project in the editor (not the game window).
REM Edit GODOT_EXE if your editor is installed elsewhere.
set "GODOT_EXE=C:\Godot_v4.3-stable_win64.exe\Godot_v4.3-stable_win64.exe"
set "PROJECT_DIR=%~dp0"
REM Drop trailing backslash for cleaner quoting
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

if not exist "%GODOT_EXE%" (
  echo Godot not found: %GODOT_EXE%
  pause
  exit /b 1
)

start "" "%GODOT_EXE%" --editor --path "%PROJECT_DIR%"
