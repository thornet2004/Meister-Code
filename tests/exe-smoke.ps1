$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class StudioWindows {
    public delegate bool EnumCallback(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumCallback callback, IntPtr param);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    public static string[] Titles(int[] owned) {
        var titles = new List<string>();
        EnumWindows((hwnd, param) => {
            uint pid; GetWindowThreadProcessId(hwnd, out pid);
            if (Array.IndexOf(owned, (int)pid) >= 0) {
                var text = new StringBuilder(1024); GetWindowText(hwnd, text, 1024);
                if (text.Length > 0) titles.Add(text.ToString());
            }
            return true;
        }, IntPtr.Zero);
        return titles.ToArray();
    }
}
'@
$workspacePath = Split-Path $PSScriptRoot -Parent
$testDataPath = Join-Path $PSScriptRoot ('exe-data-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDataPath | Out-Null
$testConfigPath = Join-Path $testDataPath 'gerador-imagens'
New-Item -ItemType Directory -Path $testConfigPath | Out-Null
@{storage_layout=2; storage_root=$workspacePath; active_project_id='smoke'; projects=@(@{id='smoke'; name='Teste isolado'; path=$testDataPath})} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $testConfigPath 'config.json') -Encoding utf8
$previousAppData = $env:APPDATA
$launchedProcess = $null
try {
    $env:APPDATA = $testDataPath
    $launchedProcess = Start-Process -FilePath (Join-Path $workspacePath 'dist\Studio de Media.exe') -WorkingDirectory $workspacePath -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    $mainWindow = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        $ownedIds = @($launchedProcess.Id) + @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($launchedProcess.Id)" | Select-Object -ExpandProperty ProcessId)
        $windowTitles = [StudioWindows]::Titles([int[]]$ownedIds)
        $mainWindow = $windowTitles | Where-Object { $_ -like 'Studio de M*' } | Select-Object -First 1
        if ($mainWindow) { break }
        if ($launchedProcess.HasExited) { throw 'O executável terminou antes de abrir a janela.' }
        Start-Sleep -Milliseconds 300
    }
    if (-not $mainWindow) { throw "A janela do executável não apareceu no limite de tempo. Janelas: $windowTitles" }
    Write-Output 'PASS: executável arranca e cria a janela Studio de Média.'
} finally {
    $env:APPDATA = $previousAppData
    if ($launchedProcess -and -not $launchedProcess.HasExited) {
        & taskkill /PID $launchedProcess.Id /T /F | Out-Null
        $launchedProcess.WaitForExit(5000) | Out-Null
    }
    # A pasta de dados do teste é preservada para inspeção; não contém dados pessoais.
}
