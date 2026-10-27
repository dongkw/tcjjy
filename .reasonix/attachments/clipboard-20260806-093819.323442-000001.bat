@echo off
setlocal

set dn=Info

set dn2=ShellFolder

set rp=HKEY_CURRENT_USER\Software\Classes\CLSID

:: =====================================================================
:: skip-list cache: keys you confirm as "no need to delete" are saved
:: here and skipped on every later run (not scanned/deleted again).
:: Cache file: same folder as this script -> navicat_skip_cache.txt
:: You may edit that file manually, one full key path per line.
:: =====================================================================
set "cache=%~dp0navicat_skip_cache.txt"

:: reg delete HKEY_CURRENT_USER\Software\PremiumSoft\NavicatPremium\Registration14XCS /f  

reg delete HKEY_CURRENT_USER\Software\PremiumSoft\NavicatPremium\Registration16XCS /f

reg delete HKEY_CURRENT_USER\Software\PremiumSoft\NavicatPremium\Update /f

echo finding.....

for /f "tokens=*" %%a in ('reg query "%rp%"') do (

 echo %%a

for /f "tokens=*" %%l in ('reg query "%%a" /f "%dn%" /s /e ^|findstr /i "%dn%"') do (

  call :askdel "%%a"

)

for /f "tokens=*" %%l in ('reg query "%%a" /f "%dn2%" /s /e ^|findstr /i "%dn2%"') do (

  call :askdel "%%a"

)

)

echo re trial done!

  

pause

Exit

:: =====================================================================
:: :askdel - decide what to do with one matched CLSID key
::   D -> delete it (original behavior)
::   S -> skip it and save it to the cache (never asked/scanned again)
::   A -> skip it for this run only
:: =====================================================================
:askdel
set "key=%~1"

rem cached keys are skipped silently (and not scanned again)
if exist "%cache%" (
  for /f "usebackq delims=" %%x in ("%cache%") do (
    if /i "%%x"=="%key%" exit /b 0
  )
)

echo.
choice /c DSA /n /m "  [D]=delete  [S]=skip+cache  [A]=skip once:  %key% : "
if errorlevel 3 goto :skipOnce
if errorlevel 2 goto :skipCache

echo deleteing: %key%
reg delete "%key%" /f
exit /b 0

:skipCache
>>"%cache%" echo %key%
echo  cached, will be skipped next runs: %key%
exit /b 0

:skipOnce
echo  skipped this run: %key%
exit /b 0
