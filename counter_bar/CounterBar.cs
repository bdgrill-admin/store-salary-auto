using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace CounterBar
{
    static class Program
    {
        private const string MutexName = "Global\\StoreSalaryAuto_CounterBar_SingleInstance";

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        static void Main()
        {
            try { SetProcessDPIAware(); } catch { }

            bool createdNew;
            using (var mutex = new Mutex(true, MutexName, out createdNew))
            {
                if (!createdNew)
                {
                    MessageBox.Show(
                        "카운터 툴바(CounterBar)가 이미 실행 중입니다.\n화면 상단 또는 우측 하단 트레이 아이콘을 확인해 주세요.",
                        "CounterBar",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information
                    );
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new ToolbarForm());
            }
        }
    }

    // =========================================================================
    // 설정 저장/로드 (%APPDATA%\CounterBar\config.ini) & 시작프로그램 등록
    // =========================================================================
    class AppConfig
    {
        public string AttendanceUrl = "https://store-salary-auto-5xqyisbltbombukh3zltva.streamlit.app/";
        public string OkPosPath = "";
        public string OkPosTitleHint = "OKPOS";
        public string YtMusicUrl = "https://music.youtube.com";
        public string BrowserChoice = "auto"; // auto | chrome | edge
        public bool AlwaysOnTop = true;
        public int PosX = -1;
        public int PosY = -1;

        private const string RunRegPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string RunRegName = "CounterBar";

        public static string ConfigDir
        {
            get
            {
                string dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "CounterBar"
                );
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                return dir;
            }
        }

        public static string ConfigPath
        {
            get { return Path.Combine(ConfigDir, "config.ini"); }
        }

        public static AppConfig Load()
        {
            var cfg = new AppConfig();
            if (File.Exists(ConfigPath))
            {
                try
                {
                    foreach (string raw in File.ReadAllLines(ConfigPath, Encoding.UTF8))
                    {
                        string line = raw.Trim();
                        if (string.IsNullOrEmpty(line) || line.StartsWith("#")) continue;
                        int idx = line.IndexOf('=');
                        if (idx <= 0) continue;
                        string key = line.Substring(0, idx).Trim();
                        string val = line.Substring(idx + 1).Trim();
                        switch (key)
                        {
                            case "AttendanceUrl": if (!string.IsNullOrEmpty(val)) cfg.AttendanceUrl = val; break;
                            case "OkPosPath": cfg.OkPosPath = val; break;
                            case "OkPosTitleHint": if (!string.IsNullOrEmpty(val)) cfg.OkPosTitleHint = val; break;
                            case "YtMusicUrl": if (!string.IsNullOrEmpty(val)) cfg.YtMusicUrl = val; break;
                            case "BrowserChoice": if (!string.IsNullOrEmpty(val)) cfg.BrowserChoice = val; break;
                            case "AlwaysOnTop": cfg.AlwaysOnTop = !val.Equals("false", StringComparison.OrdinalIgnoreCase); break;
                            case "PosX": int x; if (int.TryParse(val, out x)) cfg.PosX = x; break;
                            case "PosY": int y; if (int.TryParse(val, out y)) cfg.PosY = y; break;
                        }
                    }
                }
                catch { }
            }

            if (string.IsNullOrWhiteSpace(cfg.OkPosPath))
            {
                cfg.OkPosPath = AutoDetectOkPos();
            }
            return cfg;
        }

        public void Save()
        {
            try
            {
                var lines = new List<string>
                {
                    "# CounterBar Configuration",
                    "AttendanceUrl=" + AttendanceUrl,
                    "OkPosPath=" + OkPosPath,
                    "OkPosTitleHint=" + OkPosTitleHint,
                    "YtMusicUrl=" + YtMusicUrl,
                    "BrowserChoice=" + BrowserChoice,
                    "AlwaysOnTop=" + (AlwaysOnTop ? "true" : "false"),
                    "PosX=" + PosX,
                    "PosY=" + PosY
                };
                File.WriteAllLines(ConfigPath, lines, Encoding.UTF8);
            }
            catch { }
        }

        public static string AutoDetectOkPos()
        {
            string[] candidates = new[]
            {
                @"C:\OKPOS\OKPOS.exe",
                @"C:\OKPOS\bin\OKPOS.exe",
                @"C:\okpos\okpos.exe",
                @"C:\Program Files (x86)\OKPOS\OKPOS.exe",
                @"C:\Program Files\OKPOS\OKPOS.exe"
            };
            foreach (string c in candidates)
            {
                if (File.Exists(c)) return c;
            }

            // 바탕화면 바로가기(.lnk) 자동 탐색
            try
            {
                string[] desktops = new[]
                {
                    Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory)
                };
                foreach (string d in desktops)
                {
                    if (string.IsNullOrEmpty(d) || !Directory.Exists(d)) continue;
                    foreach (string f in Directory.GetFiles(d, "*.lnk"))
                    {
                        string name = Path.GetFileNameWithoutExtension(f);
                        if (name.IndexOf("OKPOS", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            name.IndexOf("OK포스", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            name.IndexOf("오케이포스", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            return f;
                        }
                    }
                }
            }
            catch { }
            return "";
        }

        public static bool IsStartupEnabled()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(RunRegPath, false))
                {
                    if (key == null) return false;
                    object val = key.GetValue(RunRegName);
                    return val != null && !string.IsNullOrWhiteSpace(val.ToString());
                }
            }
            catch { return false; }
        }

        public static void SetStartupEnabled(bool enabled)
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(RunRegPath, true))
                {
                    if (key == null) return;
                    if (enabled)
                    {
                        key.SetValue(RunRegName, "\"" + Application.ExecutablePath + "\"");
                    }
                    else
                    {
                        if (key.GetValue(RunRegName) != null)
                            key.DeleteValue(RunRegName, false);
                    }
                }
            }
            catch { }
        }
    }

    // =========================================================================
    // Win32 창 검색 / 활성화 / 최소화 / 복원 유틸리티
    // =========================================================================
    static class Win32Helper
    {
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        public const int SW_MINIMIZE = 6;
        public const int SW_RESTORE = 9;
        public const int SW_SHOW = 5;
        public const int GWL_EXSTYLE = -20;
        public const int WS_EX_TOOLWINDOW = 0x00000080;

        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
        [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
        [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
        [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
        [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);

        public class WindowInfo
        {
            public IntPtr Handle;
            public string Title;
            public string ClassName;
            public string ProcessName;
            public uint ProcessId;
        }

        public static List<WindowInfo> GetVisibleWindows(IntPtr excludeHandle)
        {
            var list = new List<WindowInfo>();
            var procCache = new Dictionary<uint, string>();

            EnumWindows((hWnd, lParam) =>
            {
                if (hWnd == excludeHandle) return true;
                if (!IsWindowVisible(hWnd)) return true;
                int ex = GetWindowLong(hWnd, GWL_EXSTYLE);
                if ((ex & WS_EX_TOOLWINDOW) != 0) return true;

                int len = GetWindowTextLength(hWnd);
                if (len <= 0) return true;

                var sbTitle = new StringBuilder(len + 1);
                GetWindowText(hWnd, sbTitle, sbTitle.Capacity);
                string title = sbTitle.ToString().Trim();
                if (string.IsNullOrEmpty(title)) return true;

                var sbCls = new StringBuilder(128);
                GetClassName(hWnd, sbCls, sbCls.Capacity);

                uint pid;
                GetWindowThreadProcessId(hWnd, out pid);
                string procName;
                if (!procCache.TryGetValue(pid, out procName))
                {
                    try { procName = Process.GetProcessById((int)pid).ProcessName; }
                    catch { procName = ""; }
                    procCache[pid] = procName;
                }

                list.Add(new WindowInfo
                {
                    Handle = hWnd,
                    Title = title,
                    ClassName = sbCls.ToString(),
                    ProcessName = procName,
                    ProcessId = pid
                });
                return true;
            }, IntPtr.Zero);

            return list;
        }

        public static bool IsAliveVisible(IntPtr hWnd)
        {
            return hWnd != IntPtr.Zero && IsWindow(hWnd) && IsWindowVisible(hWnd);
        }

        public static void ActivateOrToggle(IntPtr hWnd)
        {
            if (!IsAliveVisible(hWnd)) return;

            IntPtr fg = GetForegroundWindow();
            if (fg == hWnd && !IsIconic(hWnd))
            {
                ShowWindow(hWnd, SW_MINIMIZE);
                return;
            }

            if (IsIconic(hWnd))
            {
                ShowWindow(hWnd, SW_RESTORE);
            }
            else
            {
                ShowWindow(hWnd, SW_SHOW);
            }

            uint dummy;
            uint fgThread = fg != IntPtr.Zero ? GetWindowThreadProcessId(fg, out dummy) : 0;
            uint targetThread = GetWindowThreadProcessId(hWnd, out dummy);
            uint curThread = GetCurrentThreadId();

            bool attachedCur = false;
            bool attachedFg = false;
            try
            {
                if (curThread != targetThread && targetThread != 0)
                    attachedCur = AttachThreadInput(curThread, targetThread, true);
                if (fgThread != 0 && fgThread != targetThread && fgThread != curThread)
                    attachedFg = AttachThreadInput(fgThread, targetThread, true);

                BringWindowToTop(hWnd);
                SetForegroundWindow(hWnd);
            }
            finally
            {
                if (attachedFg) AttachThreadInput(fgThread, targetThread, false);
                if (attachedCur) AttachThreadInput(curThread, targetThread, false);
            }
        }

        public static string FindBrowserExecutable(string choice)
        {
            string[] chromePaths = new[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Google\Chrome\Application\chrome.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Google\Chrome\Application\chrome.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Google\Chrome\Application\chrome.exe")
            };
            string[] edgePaths = new[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Microsoft\Edge\Application\msedge.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Microsoft\Edge\Application\msedge.exe")
            };

            var order = new List<string>();
            if (string.Equals(choice, "edge", StringComparison.OrdinalIgnoreCase))
            {
                order.AddRange(edgePaths);
                order.AddRange(chromePaths);
            }
            else if (string.Equals(choice, "chrome", StringComparison.OrdinalIgnoreCase))
            {
                order.AddRange(chromePaths);
                order.AddRange(edgePaths);
            }
            else
            {
                order.AddRange(chromePaths);
                order.AddRange(edgePaths);
            }

            foreach (string p in order)
            {
                if (!string.IsNullOrEmpty(p) && File.Exists(p)) return p;
            }
            return null;
        }
    }

    // =========================================================================
    // 메인 플로팅 3버튼 툴바 (포커스를 뺏지 않는 WS_EX_NOACTIVATE 적용)
    // =========================================================================
    class ToolbarForm : Form
    {
        private const int WM_MOUSEACTIVATE = 0x0021;
        private const int MA_NOACTIVATE = 3;
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_NOACTIVATE = 0x08000000;

        private AppConfig _cfg;
        private NotifyIcon _trayIcon;
        private System.Windows.Forms.Timer _statusTimer;

        private IntPtr _attHwnd = IntPtr.Zero;
        private IntPtr _posHwnd = IntPtr.Zero;
        private IntPtr _ytmHwnd = IntPtr.Zero;

        private bool _attRunning;
        private bool _posRunning;
        private bool _ytmRunning;

        // 인터랙션 영역
        private Rectangle _rectGrip;
        private Rectangle _rectAtt;
        private Rectangle _rectPos;
        private Rectangle _rectYtm;
        private Rectangle _rectCfg;

        private string _hoverId = "";
        private string _pressId = "";
        private bool _dragging;
        private Point _dragStartMouse;
        private Point _dragStartForm;

        private float _scale = 1.0f;

        public ToolbarForm()
        {
            _cfg = AppConfig.Load();

            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            TopMost = _cfg.AlwaysOnTop;
            StartPosition = FormStartPosition.Manual;
            DoubleBuffered = true;
            BackColor = Color.FromArgb(15, 23, 42);

            using (Graphics g = CreateGraphics())
            {
                _scale = Math.Max(1.0f, g.DpiX / 96.0f);
            }

            InitLayoutMetrics();
            RestoreOrCenterPosition();
            InitTray();

            _statusTimer = new System.Windows.Forms.Timer();
            _statusTimer.Interval = 1200;
            _statusTimer.Tick += (s, e) => RefreshRunningStates();
            _statusTimer.Start();
            RefreshRunningStates();
        }

        private int S(int px) { return (int)Math.Round(px * _scale); }

        private void InitLayoutMetrics()
        {
            int h = S(48);
            int padY = S(7);
            int btnH = h - padY * 2;
            int gap = S(7);

            int x = S(10);
            _rectGrip = new Rectangle(x, padY, S(18), btnH); x += _rectGrip.Width + S(6);
            _rectAtt = new Rectangle(x, padY, S(102), btnH); x += _rectAtt.Width + gap;
            _rectPos = new Rectangle(x, padY, S(102), btnH); x += _rectPos.Width + gap;
            _rectYtm = new Rectangle(x, padY, S(116), btnH); x += _rectYtm.Width + gap;
            _rectCfg = new Rectangle(x, padY, S(36), btnH); x += _rectCfg.Width + S(10);

            Size = new Size(x, h);
            UpdateRoundedRegion();
        }

        private void UpdateRoundedRegion()
        {
            int r = S(14);
            using (var path = CreateRoundRect(new Rectangle(0, 0, Width, Height), r))
            {
                Region = new Region(path);
            }
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                cp.ExStyle |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
                return cp;
            }
        }

        protected override bool ShowWithoutActivation
        {
            get { return true; }
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_MOUSEACTIVATE)
            {
                m.Result = (IntPtr)MA_NOACTIVATE;
                return;
            }
            base.WndProc(ref m);
        }

        private void RestoreOrCenterPosition()
        {
            Rectangle wa = Screen.PrimaryScreen.WorkingArea;
            if (_cfg.PosX >= 0 && _cfg.PosY >= 0)
            {
                // 연결된 모니터 범위 안에 있는지 검증
                bool inside = Screen.AllScreens.Any(sc =>
                    sc.WorkingArea.IntersectsWith(new Rectangle(_cfg.PosX, _cfg.PosY, Width, Height)));
                if (inside)
                {
                    Location = new Point(_cfg.PosX, _cfg.PosY);
                    return;
                }
            }
            CenterTop();
        }

        public void CenterTop()
        {
            Rectangle wa = Screen.PrimaryScreen.WorkingArea;
            Location = new Point(wa.Left + (wa.Width - Width) / 2, wa.Top + S(8));
            _cfg.PosX = Left;
            _cfg.PosY = Top;
            _cfg.Save();
        }

        private void InitTray()
        {
            var menu = new ContextMenuStrip();
            menu.Items.Add("툴바 앞으로 가져오기", null, (s, e) => { Show(); TopMost = _cfg.AlwaysOnTop; });
            menu.Items.Add("상단 중앙으로 이동", null, (s, e) => CenterTop());
            menu.Items.Add("설정 (경로 · 자동실행)", null, (s, e) => OpenSettings());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("툴바 종료", null, (s, e) => ExitApp());

            _trayIcon = new NotifyIcon
            {
                Icon = CreateTrayIcon(),
                Text = "CounterBar — 출퇴근 · OK포스 · 유튜브뮤직",
                ContextMenuStrip = menu,
                Visible = true
            };
            _trayIcon.DoubleClick += (s, e) => CenterTop();
        }

        private static Icon CreateTrayIcon()
        {
            using (var bmp = new Bitmap(32, 32))
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                using (var b = new SolidBrush(Color.FromArgb(30, 41, 59)))
                    g.FillEllipse(b, 1, 1, 30, 30);
                using (var b1 = new SolidBrush(Color.FromArgb(59, 130, 246)))
                    g.FillEllipse(b1, 5, 11, 7, 7);
                using (var b2 = new SolidBrush(Color.FromArgb(16, 185, 129)))
                    g.FillEllipse(b2, 13, 11, 7, 7);
                using (var b3 = new SolidBrush(Color.FromArgb(244, 63, 94)))
                    g.FillEllipse(b3, 21, 11, 7, 7);
                IntPtr hIcon = bmp.GetHicon();
                return Icon.FromHandle(hIcon);
            }
        }

        private void ExitApp()
        {
            if (_statusTimer != null) _statusTimer.Stop();
            if (_trayIcon != null)
            {
                _trayIcon.Visible = false;
                _trayIcon.Dispose();
            }
            Application.Exit();
        }

        // ---------------------------------------------------------------------
        // 창 찾기 & 스마트 토글 로직
        // ---------------------------------------------------------------------
        private IntPtr FindAttendanceWindow(List<Win32Helper.WindowInfo> wins)
        {
            if (Win32Helper.IsAliveVisible(_attHwnd)) return _attHwnd;
            string[] keys = { "출퇴근", "주간스케줄", "직원관리", "급여정산", "매니저매뉴얼", "환경설정", "분당그릴", "store-salary-auto", "Streamlit" };
            var hit = wins.FirstOrDefault(w =>
                w.ClassName.StartsWith("Chrome_WidgetWin", StringComparison.OrdinalIgnoreCase) &&
                keys.Any(k => w.Title.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0));
            if (hit != null)
            {
                _attHwnd = hit.Handle;
                return hit.Handle;
            }
            return IntPtr.Zero;
        }

        private IntPtr FindYtMusicWindow(List<Win32Helper.WindowInfo> wins)
        {
            if (Win32Helper.IsAliveVisible(_ytmHwnd)) return _ytmHwnd;
            string[] keys = { "YouTube Music", "유튜브 뮤직" };
            var hit = wins.FirstOrDefault(w =>
                w.ClassName.StartsWith("Chrome_WidgetWin", StringComparison.OrdinalIgnoreCase) &&
                keys.Any(k => w.Title.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0));
            if (hit != null)
            {
                _ytmHwnd = hit.Handle;
                return hit.Handle;
            }
            return IntPtr.Zero;
        }

        private IntPtr FindOkPosWindow(List<Win32Helper.WindowInfo> wins)
        {
            if (Win32Helper.IsAliveVisible(_posHwnd)) return _posHwnd;

            string targetProc = "";
            if (!string.IsNullOrWhiteSpace(_cfg.OkPosPath) &&
                _cfg.OkPosPath.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            {
                targetProc = Path.GetFileNameWithoutExtension(_cfg.OkPosPath);
            }

            if (!string.IsNullOrEmpty(targetProc))
            {
                var byProc = wins.FirstOrDefault(w =>
                    string.Equals(w.ProcessName, targetProc, StringComparison.OrdinalIgnoreCase));
                if (byProc != null)
                {
                    _posHwnd = byProc.Handle;
                    return byProc.Handle;
                }
            }

            string hint = string.IsNullOrWhiteSpace(_cfg.OkPosTitleHint) ? "OKPOS" : _cfg.OkPosTitleHint.Trim();
            var byTitle = wins.FirstOrDefault(w =>
                w.Title.IndexOf(hint, StringComparison.OrdinalIgnoreCase) >= 0 ||
                w.ProcessName.IndexOf("OKPOS", StringComparison.OrdinalIgnoreCase) >= 0);
            if (byTitle != null)
            {
                _posHwnd = byTitle.Handle;
                return byTitle.Handle;
            }
            return IntPtr.Zero;
        }

        private void RefreshRunningStates()
        {
            try
            {
                var wins = Win32Helper.GetVisibleWindows(Handle);
                bool a = FindAttendanceWindow(wins) != IntPtr.Zero;
                bool p = FindOkPosWindow(wins) != IntPtr.Zero;
                bool y = FindYtMusicWindow(wins) != IntPtr.Zero;
                if (a != _attRunning || p != _posRunning || y != _ytmRunning)
                {
                    _attRunning = a;
                    _posRunning = p;
                    _ytmRunning = y;
                    Invalidate();
                }
            }
            catch { }
        }

        private void ToggleWebApp(string appKind, string url, string profileSubDir)
        {
            var wins = Win32Helper.GetVisibleWindows(Handle);
            IntPtr existing = appKind == "att" ? FindAttendanceWindow(wins) : FindYtMusicWindow(wins);
            if (existing != IntPtr.Zero)
            {
                Win32Helper.ActivateOrToggle(existing);
                return;
            }

            string browser = Win32Helper.FindBrowserExecutable(_cfg.BrowserChoice);
            if (string.IsNullOrEmpty(browser))
            {
                try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
                catch (Exception ex) { MessageBox.Show("브라우저 실행 실패: " + ex.Message, "CounterBar"); }
                return;
            }

            string profileDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "CounterBar", "profiles", profileSubDir
            );
            Directory.CreateDirectory(profileDir);

            var beforeHandles = new HashSet<IntPtr>(
                wins.Where(w => w.ClassName.StartsWith("Chrome_WidgetWin", StringComparison.OrdinalIgnoreCase))
                    .Select(w => w.Handle)
            );

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = browser,
                    Arguments = string.Format("--app=\"{0}\" --user-data-dir=\"{1}\" --start-maximized --new-window", url, profileDir),
                    UseShellExecute = false
                };
                Process.Start(psi);

                // 새로 뜬 앱 창의 HWND를 백그라운드에서 캡처
                ThreadPool.QueueUserWorkItem(_ =>
                {
                    for (int i = 0; i < 20; i++)
                    {
                        Thread.Sleep(300);
                        var nowWins = Win32Helper.GetVisibleWindows(Handle);
                        var created = nowWins.FirstOrDefault(w =>
                            w.ClassName.StartsWith("Chrome_WidgetWin", StringComparison.OrdinalIgnoreCase) &&
                            !beforeHandles.Contains(w.Handle));
                        if (created != null)
                        {
                            if (appKind == "att") _attHwnd = created.Handle;
                            else _ytmHwnd = created.Handle;
                            try { BeginInvoke(new Action(RefreshRunningStates)); } catch { }
                            break;
                        }
                    }
                });
            }
            catch (Exception ex)
            {
                MessageBox.Show("앱 창 실행에 실패했습니다.\n" + ex.Message, "CounterBar", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private void ToggleOkPos()
        {
            var wins = Win32Helper.GetVisibleWindows(Handle);
            IntPtr existing = FindOkPosWindow(wins);
            if (existing != IntPtr.Zero)
            {
                Win32Helper.ActivateOrToggle(existing);
                return;
            }

            if (string.IsNullOrWhiteSpace(_cfg.OkPosPath) || !File.Exists(_cfg.OkPosPath))
            {
                var res = MessageBox.Show(
                    "OK포스 실행 파일 경로가 아직 설정되지 않았습니다.\n지금 OK포스 프로그램(.exe 또는 바탕화면 바로가기)을 선택하시겠습니까?",
                    "OK포스 경로 설정",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question
                );
                if (res == DialogResult.Yes)
                {
                    using (var ofd = new OpenFileDialog())
                    {
                        ofd.Title = "OK포스 실행 파일 또는 바로가기 선택";
                        ofd.Filter = "실행 파일 및 바로가기 (*.exe;*.lnk)|*.exe;*.lnk|모든 파일 (*.*)|*.*";
                        ofd.DereferenceLinks = false;
                        if (ofd.ShowDialog() == DialogResult.OK)
                        {
                            _cfg.OkPosPath = ofd.FileName;
                            _cfg.Save();
                        }
                        else return;
                    }
                }
                else return;
            }

            try
            {
                string workDir = Path.GetDirectoryName(_cfg.OkPosPath);
                var psi = new ProcessStartInfo
                {
                    FileName = _cfg.OkPosPath,
                    WorkingDirectory = string.IsNullOrEmpty(workDir) ? "" : workDir,
                    UseShellExecute = true
                };
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show("OK포스 실행 실패:\n" + ex.Message, "CounterBar", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private void OpenSettings()
        {
            using (var dlg = new SettingsForm(_cfg, CenterTop, ExitApp))
            {
                if (dlg.ShowDialog() == DialogResult.OK)
                {
                    _cfg.Save();
                    TopMost = _cfg.AlwaysOnTop;
                }
            }
        }

        // ---------------------------------------------------------------------
        // 마우스 이벤트 (드래그 이동 & 버튼 클릭)
        // ---------------------------------------------------------------------
        private string HitTest(Point pt)
        {
            if (_rectAtt.Contains(pt)) return "att";
            if (_rectPos.Contains(pt)) return "pos";
            if (_rectYtm.Contains(pt)) return "ytm";
            if (_rectCfg.Contains(pt)) return "cfg";
            return "grip";
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (_dragging)
            {
                Point cur = Cursor.Position;
                Location = new Point(
                    _dragStartForm.X + (cur.X - _dragStartMouse.X),
                    _dragStartForm.Y + (cur.Y - _dragStartMouse.Y)
                );
                return;
            }

            string hit = HitTest(e.Location);
            Cursor = hit == "grip" ? Cursors.SizeAll : Cursors.Hand;
            if (hit != _hoverId)
            {
                _hoverId = hit;
                Invalidate();
            }
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            base.OnMouseLeave(e);
            if (!_dragging)
            {
                _hoverId = "";
                _pressId = "";
                Invalidate();
            }
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;

            string hit = HitTest(e.Location);
            if (hit == "grip")
            {
                _dragging = true;
                _dragStartMouse = Cursor.Position;
                _dragStartForm = Location;
                Capture = true;
            }
            else
            {
                _pressId = hit;
                Invalidate();
            }
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (_dragging)
            {
                _dragging = false;
                Capture = false;
                _cfg.PosX = Left;
                _cfg.PosY = Top;
                _cfg.Save();
                return;
            }

            if (e.Button == MouseButtons.Left && !string.IsNullOrEmpty(_pressId))
            {
                string clicked = _pressId;
                _pressId = "";
                Invalidate();

                if (HitTest(e.Location) == clicked)
                {
                    if (clicked == "att") ToggleWebApp("att", _cfg.AttendanceUrl, "attendance");
                    else if (clicked == "pos") ToggleOkPos();
                    else if (clicked == "ytm") ToggleWebApp("ytm", _cfg.YtMusicUrl, "ytmusic");
                    else if (clicked == "cfg") OpenSettings();
                }
            }
        }

        // ---------------------------------------------------------------------
        // 고해상도 커스텀 렌더링
        // ---------------------------------------------------------------------
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;

            // 외곽 배경 + 테두리
            using (var bgPath = CreateRoundRect(new Rectangle(0, 0, Width - 1, Height - 1), S(14)))
            {
                using (var bgBrush = new LinearGradientBrush(ClientRectangle, Color.FromArgb(15, 23, 42), Color.FromArgb(30, 41, 59), 90f))
                    g.FillPath(bgBrush, bgPath);
                using (var bdPen = new Pen(Color.FromArgb(71, 85, 105), 1.5f))
                    g.DrawPath(bdPen, bgPath);
            }

            // 드래그 그립 (6개 점)
            using (var gripBrush = new SolidBrush(_hoverId == "grip" ? Color.FromArgb(148, 163, 184) : Color.FromArgb(100, 116, 139)))
            {
                int dot = S(3);
                int gx1 = _rectGrip.Left + S(4);
                int gx2 = _rectGrip.Left + S(11);
                int gyStart = _rectGrip.Top + (_rectGrip.Height - S(15)) / 2;
                for (int i = 0; i < 3; i++)
                {
                    int gy = gyStart + i * S(6);
                    g.FillEllipse(gripBrush, gx1, gy, dot, dot);
                    g.FillEllipse(gripBrush, gx2, gy, dot, dot);
                }
            }

            // 3개 메인 버튼
            DrawPillButton(g, _rectAtt, "출퇴근", "att", Color.FromArgb(37, 99, 235), Color.FromArgb(59, 130, 246), _attRunning);
            DrawPillButton(g, _rectPos, "OK포스", "pos", Color.FromArgb(5, 150, 105), Color.FromArgb(16, 185, 129), _posRunning);
            DrawPillButton(g, _rectYtm, "유튜브뮤직", "ytm", Color.FromArgb(225, 29, 72), Color.FromArgb(244, 63, 94), _ytmRunning);

            // 설정 버튼 (커스텀 톱니바퀴)
            DrawGearButton(g, _rectCfg, _hoverId == "cfg", _pressId == "cfg");
        }

        private void DrawPillButton(Graphics g, Rectangle rect, string text, string id, Color baseCol, Color hoverCol, bool isRunning)
        {
            bool isHover = _hoverId == id;
            bool isPress = _pressId == id;
            Color fillCol = isPress ? ControlPaint.Dark(baseCol, 0.1f) : (isHover ? hoverCol : baseCol);

            using (var path = CreateRoundRect(rect, S(9)))
            using (var brush = new SolidBrush(fillCol))
            {
                g.FillPath(brush, path);
            }

            using (var font = new Font("맑은 고딕", 9.5f, FontStyle.Bold))
            using (var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
            using (var txtBrush = new SolidBrush(Color.White))
            {
                Rectangle txtRect = rect;
                if (isPress) txtRect.Offset(0, 1);
                g.DrawString(text, font, txtBrush, txtRect, sf);
            }

            // 실행 중 표시 점 (우측 상단 연두색 점)
            if (isRunning)
            {
                int d = S(6);
                int dx = rect.Right - d - S(5);
                int dy = rect.Top + S(5);
                using (var ring = new SolidBrush(Color.FromArgb(15, 23, 42)))
                    g.FillEllipse(ring, dx - 1, dy - 1, d + 2, d + 2);
                using (var dot = new SolidBrush(Color.FromArgb(74, 222, 128)))
                    g.FillEllipse(dot, dx, dy, d, d);
            }
        }

        private void DrawGearButton(Graphics g, Rectangle rect, bool isHover, bool isPress)
        {
            Color bg = isPress ? Color.FromArgb(51, 65, 85) : (isHover ? Color.FromArgb(71, 85, 105) : Color.FromArgb(51, 65, 85));
            using (var path = CreateRoundRect(rect, S(9)))
            using (var b = new SolidBrush(bg))
                g.FillPath(b, path);

            // 벡터 톱니바퀴 아이콘 (폰트 깨짐 없음)
            float cx = rect.Left + rect.Width / 2f;
            float cy = rect.Top + rect.Height / 2f + (isPress ? 1 : 0);
            float rOuter = S(7);
            float rInner = S(4);
            using (var pen = new Pen(Color.FromArgb(226, 232, 240), S(2)))
            {
                for (int i = 0; i < 8; i++)
                {
                    double ang = i * Math.PI / 4.0;
                    float x1 = cx + (float)(Math.Cos(ang) * (rOuter - S(2)));
                    float y1 = cy + (float)(Math.Sin(ang) * (rOuter - S(2)));
                    float x2 = cx + (float)(Math.Cos(ang) * (rOuter + S(1)));
                    float y2 = cy + (float)(Math.Sin(ang) * (rOuter + S(1)));
                    g.DrawLine(pen, x1, y1, x2, y2);
                }
                g.DrawEllipse(pen, cx - rInner, cy - rInner, rInner * 2, rInner * 2);
            }
        }

        private static GraphicsPath CreateRoundRect(Rectangle r, int radius)
        {
            int d = radius * 2;
            var path = new GraphicsPath();
            path.AddArc(r.Left, r.Top, d, d, 180, 90);
            path.AddArc(r.Right - d, r.Top, d, d, 270, 90);
            path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            path.AddArc(r.Left, r.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    // =========================================================================
    // 설정 창 (URL, OK포스 경로, 브라우저, 항상 위, Windows 자동 실행)
    // =========================================================================
    class SettingsForm : Form
    {
        private readonly AppConfig _cfg;
        private TextBox _txtAttUrl;
        private TextBox _txtPosPath;
        private TextBox _txtPosHint;
        private TextBox _txtYtmUrl;
        private ComboBox _cboBrowser;
        private CheckBox _chkTopMost;
        private CheckBox _chkStartup;

        public SettingsForm(AppConfig cfg, Action onResetPos, Action onExitApp)
        {
            _cfg = cfg;

            Text = "CounterBar 설정";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            TopMost = true;
            Font = new Font("맑은 고딕", 9.5f);
            ClientSize = new Size(520, 415);
            BackColor = Color.White;

            int y = 18;
            AddLabel("출퇴근 웹 주소 (URL)", 20, y); y += 22;
            _txtAttUrl = AddTextBox(_cfg.AttendanceUrl, 20, y, 480); y += 36;

            AddLabel("OK포스 실행 파일 또는 바로가기 경로 (.exe / .lnk)", 20, y); y += 22;
            _txtPosPath = AddTextBox(_cfg.OkPosPath, 20, y, 386);
            var btnBrowse = new Button
            {
                Text = "찾아보기...",
                Location = new Point(414, y - 1),
                Size = new Size(86, 27),
                FlatStyle = FlatStyle.System
            };
            btnBrowse.Click += (s, e) =>
            {
                using (var ofd = new OpenFileDialog())
                {
                    ofd.Title = "OK포스 실행 파일 선택";
                    ofd.Filter = "실행 파일 및 바로가기 (*.exe;*.lnk)|*.exe;*.lnk|모든 파일 (*.*)|*.*";
                    ofd.DereferenceLinks = false;
                    if (ofd.ShowDialog(this) == DialogResult.OK)
                        _txtPosPath.Text = ofd.FileName;
                }
            };
            Controls.Add(btnBrowse);
            y += 36;

            AddLabel("OK포스 창 제목 검색어 (창 전환 매칭용, 기본: OKPOS)", 20, y); y += 22;
            _txtPosHint = AddTextBox(_cfg.OkPosTitleHint, 20, y, 220);

            AddLabel("웹앱 실행 브라우저", 260, y - 22);
            _cboBrowser = new ComboBox
            {
                Location = new Point(260, y),
                Size = new Size(240, 26),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            _cboBrowser.Items.AddRange(new object[] { "자동 (Chrome 우선 → Edge)", "Google Chrome", "Microsoft Edge" });
            if (_cfg.BrowserChoice == "chrome") _cboBrowser.SelectedIndex = 1;
            else if (_cfg.BrowserChoice == "edge") _cboBrowser.SelectedIndex = 2;
            else _cboBrowser.SelectedIndex = 0;
            Controls.Add(_cboBrowser);
            y += 36;

            AddLabel("유튜브뮤직 주소 (URL)", 20, y); y += 22;
            _txtYtmUrl = AddTextBox(_cfg.YtMusicUrl, 20, y, 480); y += 38;

            _chkTopMost = new CheckBox
            {
                Text = "항상 다른 창 위에 표시 (TopMost)",
                Location = new Point(22, y),
                AutoSize = true,
                Checked = _cfg.AlwaysOnTop
            };
            Controls.Add(_chkTopMost);
            y += 28;

            _chkStartup = new CheckBox
            {
                Text = "Windows 시작 시 자동 실행 (시작프로그램 등록)",
                Location = new Point(22, y),
                AutoSize = true,
                Checked = AppConfig.IsStartupEnabled()
            };
            Controls.Add(_chkStartup);
            y += 42;

            // 하단 버튼 영역
            var btnResetPos = new Button
            {
                Text = "상단 중앙 이동",
                Location = new Point(20, y),
                Size = new Size(112, 34)
            };
            btnResetPos.Click += (s, e) => { if (onResetPos != null) onResetPos(); };
            Controls.Add(btnResetPos);

            var btnExit = new Button
            {
                Text = "툴바 종료",
                Location = new Point(140, y),
                Size = new Size(88, 34),
                ForeColor = Color.FromArgb(185, 28, 28)
            };
            btnExit.Click += (s, e) =>
            {
                if (MessageBox.Show("카운터 툴바를 종료하시겠습니까?", "CounterBar", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
                {
                    DialogResult = DialogResult.Cancel;
                    Close();
                    if (onExitApp != null) onExitApp();
                }
            };
            Controls.Add(btnExit);

            var btnCancel = new Button
            {
                Text = "취소",
                Location = new Point(328, y),
                Size = new Size(80, 34),
                DialogResult = DialogResult.Cancel
            };
            Controls.Add(btnCancel);

            var btnSave = new Button
            {
                Text = "저장",
                Location = new Point(416, y),
                Size = new Size(84, 34),
                BackColor = Color.FromArgb(37, 99, 235),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            btnSave.FlatAppearance.BorderSize = 0;
            btnSave.Click += (s, e) =>
            {
                if (!string.IsNullOrWhiteSpace(_txtAttUrl.Text)) _cfg.AttendanceUrl = _txtAttUrl.Text.Trim();
                _cfg.OkPosPath = _txtPosPath.Text.Trim();
                if (!string.IsNullOrWhiteSpace(_txtPosHint.Text)) _cfg.OkPosTitleHint = _txtPosHint.Text.Trim();
                if (!string.IsNullOrWhiteSpace(_txtYtmUrl.Text)) _cfg.YtMusicUrl = _txtYtmUrl.Text.Trim();
                _cfg.BrowserChoice = _cboBrowser.SelectedIndex == 1 ? "chrome" : (_cboBrowser.SelectedIndex == 2 ? "edge" : "auto");
                _cfg.AlwaysOnTop = _chkTopMost.Checked;
                AppConfig.SetStartupEnabled(_chkStartup.Checked);
                DialogResult = DialogResult.OK;
                Close();
            };
            Controls.Add(btnSave);

            AcceptButton = btnSave;
            CancelButton = btnCancel;
        }

        private void AddLabel(string text, int x, int y)
        {
            Controls.Add(new Label
            {
                Text = text,
                Location = new Point(x, y),
                AutoSize = true,
                ForeColor = Color.FromArgb(51, 65, 85),
                Font = new Font("맑은 고딕", 9f, FontStyle.Bold)
            });
        }

        private TextBox AddTextBox(string value, int x, int y, int width)
        {
            var tb = new TextBox
            {
                Text = value ?? "",
                Location = new Point(x, y),
                Size = new Size(width, 26)
            };
            Controls.Add(tb);
            return tb;
        }
    }
}
