@echo off
chcp 65001 >nul
cd /d "%~dp0"
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe

echo [CounterBar] 빌드 시작...
"%CSC%" /nologo /target:winexe /optimize+ /utf8output /win32icon:CounterBar.ico /out:CounterBar.exe /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll CounterBar.cs
if %errorlevel% neq 0 (
    echo [실패] 컴파일 오류가 발생했습니다.
    pause
    exit /b 1
)
echo [성공] CounterBar.exe 빌드 완료!
pause
