@echo off
rem  Order Tracker - update the copy you actually use.
rem
rem  Double-click this. It fetches the newest version into the folder that
rem  has the download history in it, then copies the program across to the
rem  copy you run from.
rem
rem  It never touches your orders. The data folder, the documents, your
rem  settings and the portable marker are all left exactly as they are on
rem  both sides, and nothing is ever deleted - files are only added or
rem  replaced.
rem
rem  Works in either direction: run it from the downloaded folder and it
rem  asks where your working copy is; run it from the working copy and it
rem  asks where the download is. It remembers the answer.

chcp 65001 >nul
setlocal EnableExtensions
title Order Tracker - update

rem  Run from a copy of ourselves, so that fetching a newer version of this
rem  very file partway through cannot confuse the command interpreter.
if /i "%~1"=="--child" goto :RUN
set "SELFCOPY=%TEMP%\ordertracker-update.bat"
copy /y "%~f0" "%SELFCOPY%" >nul 2>&1
if exist "%SELFCOPY%" (
  call "%SELFCOPY%" --child "%~dp0"
) else (
  call "%~f0" --child "%~dp0"
)
exit /b

:RUN
set "HERE=%~2"
if "%HERE%"=="" set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

echo.
echo   ORDER TRACKER - UPDATE
echo.
echo   this folder   %HERE%

if not exist "%HERE%\run.py" (
  echo.
  echo   This is not an Order Tracker folder - run.py is not in it.
  echo   Put update.bat in one of the two folders and run it there.
  goto :STOP
)

rem  The folder holding the download history is the one we fetch into.
set "ROLE=copy"
if exist "%HERE%\.git" set "ROLE=download"

set "REMEMBER=%HERE%\update-partner.txt"
set "OTHER="
if exist "%REMEMBER%" set /p OTHER=<"%REMEMBER%"

if not "%OTHER%"=="" goto :HAVEOTHER
echo.
if "%ROLE%"=="download" (
  echo   Which folder do you run Order Tracker from?
  echo   For example:  G:\your folder\Order Tracker
) else (
  echo   Which folder did you download Order Tracker into?
  echo   For example:  C:\Users\%USERNAME%\Order-tracker
)
echo.
set /p OTHER="   Paste the full path and press Enter: "
if "%OTHER%"=="" goto :NOPATH
rem  Paths pasted from Explorer often arrive wrapped in quotes.
set OTHER=%OTHER:"=%
if "%OTHER:~-1%"=="\" set "OTHER=%OTHER:~0,-1%"
>"%REMEMBER%" echo %OTHER%
if exist "%REMEMBER%" (
  echo   Remembered - you will not be asked again.
) else (
  echo   That folder could not be remembered here, so it will be asked
  echo   for each time. Nothing else is affected.
)

:HAVEOTHER
if "%ROLE%"=="download" (
  set "SRC=%HERE%"
  set "DST=%OTHER%"
) else (
  set "SRC=%OTHER%"
  set "DST=%HERE%"
)

echo   from          %SRC%
echo   to            %DST%
echo.

if not exist "%SRC%\run.py" (
  echo   %SRC%
  echo   is not an Order Tracker folder - run.py is not in it.
  echo   Delete %REMEMBER% and run this again to change it.
  goto :STOP
)
if not exist "%DST%" (
  echo   %DST%
  echo   does not exist. Check the drive is connected.
  goto :STOP
)
if not exist "%DST%\run.py" (
  echo   %DST%
  echo   does not look like an Order Tracker folder - run.py is not in it.
  echo   Refusing to write into it.
  goto :STOP
)

echo   [1 of 2] fetching the newest version
where git >nul 2>&1
if errorlevel 1 (
  echo          git is not installed, so nothing was fetched.
  echo          The copy below is still done.
) else (
  if exist "%SRC%\.git" (
    git -C "%SRC%" pull --ff-only
    if errorlevel 1 (
      echo.
      echo          Nothing was fetched. You may have no connection, or
      echo          local changes. The copy below is still done.
    )
  ) else (
    echo          %SRC% has no download history, so nothing was fetched.
  )
)

echo.
echo   [2 of 2] copying the program across
echo.

rem  /E keeps the folder structure. Nothing is deleted: without /MIR or
rem  /PURGE robocopy only adds and replaces. Everything that is yours is
rem  excluded by name.
robocopy "%SRC%" "%DST%" /E ^
  /XD "%SRC%\data" "%SRC%\demo-data" "%SRC%\.git" __pycache__ .scratch ^
  /XF settings.json portable.txt update-partner.txt *.db *.db-wal *.db-shm *.pyc ^
  /NFL /NDL /NJH /NP /R:1 /W:1
set "COPIED=%ERRORLEVEL%"

echo.
if %COPIED% GEQ 8 (
  echo   The copy did not finish. Nothing in your data folder was touched.
  echo   If Order Tracker is open on the other machine, close it and try
  echo   again; robocopy cannot replace a file that is in use.
  goto :STOP
)
if %COPIED% EQU 0 (
  echo   Already up to date - nothing needed copying.
) else (
  echo   Done. The program in %DST% is now the newest one.
)
echo   Your orders, documents and settings were left alone.
echo.
echo   Start it with the Order Tracker icon, or with:
echo       cd /d "%DST%"
echo       py run.py
goto :STOP

:NOPATH
echo.
echo   No folder given, so nothing was done.

:STOP
echo.
pause
endlocal
exit /b
