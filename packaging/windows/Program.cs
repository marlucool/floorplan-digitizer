using System.Diagnostics;
using System.Drawing;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using System.Windows.Forms;

namespace Planline.Setup;

internal static class Program
{
    internal const string ProductName = "Planline";
    internal const string InstallMarker = ".planline-installed.json";
    internal const string DataDirectoryName = "Planline";
    internal const string Version = "0.1.2";

    [STAThread]
    private static int Main(string[] args)
    {
        if (!OperatingSystem.IsWindows())
        {
            return 1;
        }

        ApplicationConfiguration.Initialize();

        string executable = Environment.ProcessPath ?? Application.ExecutablePath;
        string executableName = Path.GetFileName(executable);
        string executableDirectory = Path.GetDirectoryName(executable)!;

        if (executableName.Equals("Planline.Uninstall.exe", StringComparison.OrdinalIgnoreCase))
        {
            return InstallerMaintenance.Uninstall(executableDirectory);
        }

        if (args.Contains("--cleanup", StringComparer.OrdinalIgnoreCase))
        {
            return 0;
        }

        if (args.Contains("--update-install", StringComparer.OrdinalIgnoreCase))
        {
            string? installPath = ArgumentValue(args, "--install-path");
            if (string.IsNullOrWhiteSpace(installPath))
            {
                MessageBox.Show("The update installer requires an installation path.", "Planline Update",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }
            using var updateForm = new SetupForm(installPath, autoInstall: true);
            Application.Run(updateForm);
            return 0;
        }

        if (File.Exists(Path.Combine(executableDirectory, InstallMarker)))
        {
            return InstalledLauncher.Run(executableDirectory);
        }

        Application.Run(new SetupForm());
        return 0;
    }

    private static string? ArgumentValue(string[] args, string name)
    {
        for (int index = 0; index < args.Length - 1; index++)
        {
            if (args[index].Equals(name, StringComparison.OrdinalIgnoreCase))
                return args[index + 1];
        }
        return null;
    }
}

internal static class InstalledLauncher
{
    // A named, per-session mutex prevents two launcher processes from opening
    // the shared desktop.log or starting competing local API instances.
    private const string InstanceMutexName = @"Local\Planline.Desktop";

    public static int Run(string installDirectory)
    {
        using var instanceMutex = new Mutex(initiallyOwned: false, name: InstanceMutexName);
        bool ownsMutex = false;
        try
        {
            try
            {
                ownsMutex = instanceMutex.WaitOne(0);
            }
            catch (AbandonedMutexException)
            {
                // The previous launcher exited without releasing the mutex.
                // WaitOne has acquired ownership in this case.
                ownsMutex = true;
            }

            if (!ownsMutex)
            {
                MessageBox.Show(
                    "Planline is already starting or running. Switch to the existing Planline window instead of opening another copy.",
                    "Planline",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information
                );
                return 0;
            }

            return RunSingleInstance(installDirectory);
        }
        finally
        {
            if (ownsMutex)
            {
                instanceMutex.ReleaseMutex();
            }
        }
    }

    private static int RunSingleInstance(string installDirectory)
    {
        string python = Path.Combine(installDirectory, "python", "python.exe");
        string appDirectory = Path.Combine(installDirectory, "app");
        string dataDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            Program.DataDirectoryName
        );

        if (!File.Exists(python) || !File.Exists(Path.Combine(appDirectory, "planline", "desktop.py")))
        {
            MessageBox.Show(
                "Planline is not installed correctly. Run Planline-Setup.exe again to repair the installation.",
                "Planline",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }

        string logDirectory = Path.Combine(dataDirectory, "logs");
        Directory.CreateDirectory(logDirectory);
        string logPath = Path.Combine(logDirectory, "desktop.log");
        string actualLogPath = logPath;

        var startInfo = new ProcessStartInfo
        {
            FileName = python,
            WorkingDirectory = appDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        startInfo.ArgumentList.Add("-m");
        startInfo.ArgumentList.Add("planline.desktop");
        startInfo.Environment["PLANLINE_DATA_DIR"] = dataDirectory;
        startInfo.Environment["PLANLINE_INSTALL_DIR"] = installDirectory;
        startInfo.Environment["PLANLINE_LAUNCHER_PID"] = Environment.ProcessId.ToString();
        startInfo.Environment["PYTHONPATH"] = appDirectory;
        startInfo.Environment["PYTHONUTF8"] = "1";
        startInfo.Environment["PYTHONUNBUFFERED"] = "1";

        try
        {
            using var process = new Process { StartInfo = startInfo };
            object logLock = new();

            using var log = OpenLogWriter(logPath, out actualLogPath);
            if (!string.Equals(actualLogPath, logPath, StringComparison.OrdinalIgnoreCase))
            {
                log.WriteLine(
                    $"[launcher] The shared desktop.log was locked by another process. " +
                    $"This session is writing to {actualLogPath}."
                );
            }

            process.OutputDataReceived += (_, eventArgs) =>
            {
                if (eventArgs.Data is not null)
                {
                    lock (logLock) log.WriteLine(eventArgs.Data);
                }
            };
            process.ErrorDataReceived += (_, eventArgs) =>
            {
                if (eventArgs.Data is not null)
                {
                    lock (logLock) log.WriteLine("[stderr] " + eventArgs.Data);
                }
            };

            if (!process.Start())
            {
                throw new InvalidOperationException("Windows could not start the private Planline runtime.");
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.WaitForExit();
            process.WaitForExit();

            if (process.ExitCode != 0)
            {
                MessageBox.Show(
                    $"Planline closed with an error (exit code {process.ExitCode}).\n\n" +
                    $"The startup log is saved at:\n{actualLogPath}",
                    "Planline",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }

            return process.ExitCode;
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"Planline could not start.\n\n{exception.Message}\n\nLog: {actualLogPath}",
                "Planline",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }
    }

    private static StreamWriter OpenLogWriter(string logPath, out string actualLogPath)
    {
        actualLogPath = logPath;
        try
        {
            // Permit log viewers/readers while the single-instance mutex
            // protects against competing Planline writers.
            return new StreamWriter(
                new FileStream(logPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite)
            ) { AutoFlush = true };
        }
        catch (IOException)
        {
            // A stale process or an external tool may still hold the shared
            // log with exclusive access. Do not let that prevent the app opening.
            string directory = Path.GetDirectoryName(logPath)
                ?? throw new IOException("Could not determine the Planline log directory.");
            actualLogPath = Path.Combine(
                directory,
                $"desktop-{DateTime.Now:yyyyMMdd-HHmmss-fff}-{Environment.ProcessId}.log"
            );
            return new StreamWriter(
                new FileStream(actualLogPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read)
            ) { AutoFlush = true };
        }
    }
}

internal static class InstallerMaintenance
{
    public static int Uninstall(string installDirectory)
    {
        var answer = MessageBox.Show(
            "Remove Planline from this computer?\n\nYour OCR crops and datasets will be kept.",
            "Uninstall Planline",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question,
            MessageBoxDefaultButton.Button2
        );
        if (answer != DialogResult.Yes)
        {
            return 0;
        }

        bool removeData = MessageBox.Show(
            "Do you also want to delete your local Planline data, including saved OCR crops and labels?\n\n" +
            "Choose No to keep your datasets.",
            "Remove local data?",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2
        ) == DialogResult.Yes;

        string desktopShortcut = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            "Planline.lnk"
        );
        string startMenuFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            "Planline"
        );
        string dataDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            Program.DataDirectoryName
        );

        static string PsLiteral(string value) => "'" + value.Replace("'", "''") + "'";

        var commands = new List<string>
        {
            "Start-Sleep -Seconds 2",
            $"Remove-Item -LiteralPath {PsLiteral(desktopShortcut)} -Force -ErrorAction SilentlyContinue",
            $"Remove-Item -LiteralPath {PsLiteral(startMenuFolder)} -Recurse -Force -ErrorAction SilentlyContinue",
            "Remove-Item -Path 'Registry::HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Planline' -Recurse -Force -ErrorAction SilentlyContinue",
            $"Remove-Item -LiteralPath {PsLiteral(installDirectory)} -Recurse -Force -ErrorAction SilentlyContinue",
        };

        if (removeData)
        {
            commands.Insert(4,
                $"Remove-Item -LiteralPath {PsLiteral(dataDirectory)} -Recurse -Force -ErrorAction SilentlyContinue");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        startInfo.ArgumentList.Add("-NoProfile");
        startInfo.ArgumentList.Add("-NonInteractive");
        startInfo.ArgumentList.Add("-WindowStyle");
        startInfo.ArgumentList.Add("Hidden");
        startInfo.ArgumentList.Add("-Command");
        startInfo.ArgumentList.Add(string.Join("; ", commands));

        try
        {
            Process.Start(startInfo);
            return 0;
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"The uninstaller could not start the cleanup process.\n\n{exception.Message}",
                "Uninstall Planline",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }
    }
}

internal sealed class SetupForm : Form
{
    private const string PythonUrl =
        "https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe";
    private const string PythonSha256 =
        "92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965";
    private const string WebView2BootstrapperUrl =
        "https://go.microsoft.com/fwlink/p/?LinkId=2124703";
    private const string TorchCudaIndex = "https://download.pytorch.org/whl/cu126";
    private const string TorchCpuIndex = "https://download.pytorch.org/whl/cpu";

    private static readonly HttpClient Http = new(new HttpClientHandler
    {
        AllowAutoRedirect = true,
        AutomaticDecompression = System.Net.DecompressionMethods.All,
    })
    {
        Timeout = TimeSpan.FromMinutes(30),
    };

    private readonly TextBox _installPath = new();
    private readonly RadioButton _gpuOption = new();
    private readonly RadioButton _cpuOption = new();
    private readonly Label _gpuDetection = new();
    private readonly Label _status = new();
    private readonly Label _progressDetail = new();
    private readonly Label _phaseLabel = new();
    private readonly ListView _assetProgress = new();
    private readonly Panel _setupOptions = new();
    private readonly Panel _workPanel = new();
    private readonly ProgressBar _progressBar = new();
    private readonly Dictionary<string, ListViewItem> _assetRows = new(StringComparer.OrdinalIgnoreCase);
    private readonly Button _installButton = new();
    private readonly CheckBox _desktopShortcut = new();
    private readonly CheckBox _launchAfterInstall = new();
    private readonly bool _autoInstall;

    public SetupForm(string? initialInstallDirectory = null, bool autoInstall = false)
    {
        _autoInstall = autoInstall;
        Text = autoInstall ? "Planline Update" : "Planline Setup";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = true;
        ClientSize = new Size(820, 700);
        Font = new Font("Segoe UI", 9.5f);
        BackColor = Color.FromArgb(248, 249, 251);

        BuildInterface();
        DetectNvidia();

        if (!string.IsNullOrWhiteSpace(initialInstallDirectory))
        {
            _installPath.Text = Path.GetFullPath(initialInstallDirectory);
            RestoreInstalledRuntimeChoice(_installPath.Text);
        }

        if (_autoInstall)
        {
            _launchAfterInstall.Checked = true;
            Shown += async (_, _) =>
            {
                await Task.Delay(350);
                await InstallAsync();
            };
        }
    }

    private void RestoreInstalledRuntimeChoice(string installDirectory)
    {
        try
        {
            string marker = Path.Combine(installDirectory, Program.InstallMarker);
            if (!File.Exists(marker)) return;
            using JsonDocument document = JsonDocument.Parse(File.ReadAllText(marker));
            if (!document.RootElement.TryGetProperty("accelerator", out JsonElement value)) return;
            string accelerator = value.GetString() ?? "";
            if (accelerator.StartsWith("cpu", StringComparison.OrdinalIgnoreCase))
                _cpuOption.Checked = true;
            else if (accelerator.StartsWith("cuda", StringComparison.OrdinalIgnoreCase) && _gpuOption.Enabled)
                _gpuOption.Checked = true;
        }
        catch
        {
            // Keep the detected default if an older install marker is unreadable.
        }
    }

    private void BuildInterface()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 5,
            Padding = new Padding(28, 22, 28, 22),
            BackColor = BackColor,
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 82));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 145));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 126));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 76));
        Controls.Add(root);

        var header = new Panel { Dock = DockStyle.Fill };
        var title = new Label
        {
            Text = "Install Planline",
            Font = new Font("Segoe UI Semibold", 22f, FontStyle.Bold),
            ForeColor = Color.FromArgb(28, 37, 49),
            AutoSize = true,
            Location = new Point(0, 0),
        };
        var subtitle = new Label
        {
            Text = "One installer. No terminal, Python setup or package commands.",
            ForeColor = Color.FromArgb(90, 101, 116),
            AutoSize = true,
            Location = new Point(2, 43),
        };
        header.Controls.Add(title);
        header.Controls.Add(subtitle);
        root.Controls.Add(header, 0, 0);

        var destination = CreateGroup("Installation location");
        _installPath.ReadOnly = false;
        _installPath.Dock = DockStyle.Fill;
        _installPath.Text = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            "Planline"
        );
        var browse = new Button
        {
            Text = "Browse…",
            AutoSize = true,
            Dock = DockStyle.Right,
            Margin = new Padding(8, 0, 0, 0),
        };
        browse.Click += (_, _) => BrowseForFolder();

        var locationRow = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            Height = 36,
            ColumnCount = 2,
            RowCount = 1,
        };
        locationRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        locationRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        locationRow.Controls.Add(_installPath, 0, 0);
        locationRow.Controls.Add(browse, 1, 0);
        var note = new Label
        {
            Text = "Planline keeps its Python runtime and libraries inside this folder. It will not change your system PATH or other Python installations.",
            ForeColor = Color.FromArgb(90, 101, 116),
            Dock = DockStyle.Top,
            Height = 42,
            Padding = new Padding(0, 9, 0, 0),
        };
        destination.Controls.Add(note);
        destination.Controls.Add(locationRow);
        root.Controls.Add(destination, 0, 1);

        var hardware = CreateGroup("Hardware acceleration");
        _gpuOption.Text = "NVIDIA GPU acceleration (CUDA 12.6)";
        _gpuOption.AutoSize = true;
        _gpuOption.Location = new Point(16, 27);
        _cpuOption.Text = "CPU only (works without an NVIDIA GPU)";
        _cpuOption.AutoSize = true;
        _cpuOption.Location = new Point(16, 57);
        _gpuDetection.Text = "Checking for an NVIDIA GPU…";
        _gpuDetection.ForeColor = Color.FromArgb(90, 101, 116);
        _gpuDetection.AutoSize = true;
        _gpuDetection.Location = new Point(16, 88);
        hardware.Controls.Add(_gpuOption);
        hardware.Controls.Add(_cpuOption);
        hardware.Controls.Add(_gpuDetection);
        root.Controls.Add(hardware, 0, 2);

        var options = _setupOptions;
        options.Dock = DockStyle.Fill;
        _desktopShortcut.Text = "Create a desktop shortcut";
        _desktopShortcut.Checked = true;
        _desktopShortcut.AutoSize = true;
        _desktopShortcut.Location = new Point(0, 5);
        _launchAfterInstall.Text = "Launch Planline when installation finishes";
        _launchAfterInstall.Checked = true;
        _launchAfterInstall.AutoSize = true;
        _launchAfterInstall.Location = new Point(0, 33);
        var info = new Label
        {
            Text = "The installer downloads a private Python runtime, Planline's dependencies, and WebView2 if Windows does not already have it. The NVIDIA option installs the CUDA-enabled PyTorch build; if CUDA cannot start, setup falls back to the CPU build.",
            ForeColor = Color.FromArgb(90, 101, 116),
            AutoSize = false,
            Width = 650,
            Height = 55,
            Location = new Point(0, 67),
        };
        options.Controls.Add(_desktopShortcut);
        options.Controls.Add(_launchAfterInstall);
        options.Controls.Add(info);
        root.Controls.Add(options, 0, 3);

        _workPanel.Dock = DockStyle.Fill;
        _workPanel.Visible = false;
        var workLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(0, 2, 0, 0),
        };
        workLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        workLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
        workLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _phaseLabel.Text = "Preparing installation…";
        _phaseLabel.Font = new Font("Segoe UI Semibold", 10.5f, FontStyle.Bold);
        _phaseLabel.ForeColor = Color.FromArgb(28, 37, 49);
        _phaseLabel.Dock = DockStyle.Fill;
        _progressDetail.Text = "Individual downloads and package assets will appear below.";
        _progressDetail.ForeColor = Color.FromArgb(90, 101, 116);
        _progressDetail.Dock = DockStyle.Fill;
        _assetProgress.Dock = DockStyle.Fill;
        _assetProgress.View = View.Details;
        _assetProgress.FullRowSelect = true;
        _assetProgress.GridLines = true;
        _assetProgress.HeaderStyle = ColumnHeaderStyle.Nonclickable;
        _assetProgress.Columns.Add("Component / asset", 360);
        _assetProgress.Columns.Add("Downloaded", 120);
        _assetProgress.Columns.Add("Progress", 100);
        _assetProgress.Columns.Add("Status", 150);
        workLayout.Controls.Add(_phaseLabel, 0, 0);
        workLayout.Controls.Add(_progressDetail, 0, 1);
        workLayout.Controls.Add(_assetProgress, 0, 2);
        _workPanel.Controls.Add(workLayout);
        root.Controls.Add(_workPanel, 0, 3);

        var footer = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 2,
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        footer.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));
        footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _status.Text = "Ready to install.";
        _status.ForeColor = Color.FromArgb(65, 75, 90);
        _status.Dock = DockStyle.Fill;
        _progressBar.Dock = DockStyle.Fill;
        _progressBar.Style = ProgressBarStyle.Continuous;
        _progressBar.Visible = false;
        _installButton.Text = "Install Planline";
        _installButton.Width = 150;
        _installButton.Height = 38;
        _installButton.Anchor = AnchorStyles.Right | AnchorStyles.Bottom;
        _installButton.Click += async (_, _) => await InstallAsync();

        footer.Controls.Add(_status, 0, 0);
        footer.Controls.Add(_progressBar, 0, 1);
        footer.Controls.Add(_installButton, 1, 0);
        footer.SetRowSpan(_installButton, 2);
        root.Controls.Add(footer, 0, 4);
    }

    private static GroupBox CreateGroup(string title)
    {
        return new GroupBox
        {
            Text = title,
            Dock = DockStyle.Fill,
            ForeColor = Color.FromArgb(45, 57, 72),
            Padding = new Padding(12, 10, 12, 8),
        };
    }

    private void BrowseForFolder()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose where Planline should be installed",
            UseDescriptionForTitle = true,
            SelectedPath = _installPath.Text,
            ShowNewFolderButton = true,
        };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _installPath.Text = Path.Combine(dialog.SelectedPath, "Planline");
        }
    }

    private void DetectNvidia()
    {
        string? nvidiaSmi = FindNvidiaSmi();
        if (nvidiaSmi is null)
        {
            _gpuOption.Enabled = false;
            _cpuOption.Checked = true;
            _gpuDetection.Text = "No NVIDIA driver utility was found. CPU mode is selected.";
            return;
        }

        string gpuName = QueryNvidiaName(nvidiaSmi);
        _gpuOption.Enabled = true;
        _gpuOption.Checked = true;
        _gpuDetection.Text = string.IsNullOrWhiteSpace(gpuName)
            ? "NVIDIA driver detected. CUDA will be tested during setup."
            : $"Detected: {gpuName}. CUDA will be tested during setup.";
    }

    private static string? FindNvidiaSmi()
    {
        string[] candidates =
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "nvidia-smi.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
        };
        return candidates.FirstOrDefault(File.Exists);
    }

    private static string QueryNvidiaName(string executable)
    {
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = executable,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            info.ArgumentList.Add("--query-gpu=name");
            info.ArgumentList.Add("--format=csv,noheader");
            using var process = Process.Start(info);
            if (process is null)
            {
                return "";
            }

            Task<string> outputTask = process.StandardOutput.ReadToEndAsync();
            Task<string> errorTask = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(5000))
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit();
                return "";
            }

            string output = outputTask.GetAwaiter().GetResult();
            _ = errorTask.GetAwaiter().GetResult();
            return process.ExitCode == 0 ? output.Trim() : "";
        }
        catch
        {
            return "";
        }
    }

    private async Task InstallAsync()
    {
        _installButton.Enabled = false;
        _installButton.Text = "Installing…";
        _gpuOption.Enabled = false;
        _cpuOption.Enabled = false;
        _installPath.Enabled = false;
        _progressBar.Visible = true;
        _progressBar.Style = ProgressBarStyle.Marquee;
        _progressBar.MarqueeAnimationSpeed = 24;
        _setupOptions.Visible = false;
        _workPanel.Visible = true;
        _assetProgress.Items.Clear();
        _assetRows.Clear();
        _progressDetail.Text = "Starting setup. Large machine-learning packages can take several minutes.";

        string installDirectory = "";
        bool useGpu = _gpuOption.Checked;
        bool cpuFallback = false;

        try
        {
            if (!Environment.Is64BitOperatingSystem)
            {
                throw new InvalidOperationException("Planline's Windows installer requires 64-bit Windows.");
            }

            installDirectory = Path.GetFullPath(_installPath.Text.Trim());
            if (string.IsNullOrWhiteSpace(installDirectory) ||
                Path.GetPathRoot(installDirectory)?.Equals(installDirectory, StringComparison.OrdinalIgnoreCase) == true)
            {
                throw new InvalidOperationException("Choose a folder below a drive, not the drive root.");
            }

            if (IsPlanlineRunning(installDirectory))
            {
                throw new InvalidOperationException("Close Planline before installing or updating it.");
            }

            string marker = Path.Combine(installDirectory, Program.InstallMarker);
            bool existingInstall = File.Exists(marker);
            if (Directory.Exists(installDirectory) && !existingInstall &&
                Directory.EnumerateFileSystemEntries(installDirectory).Any())
            {
                throw new InvalidOperationException(
                    "The selected folder is not empty and is not a Planline installation. Choose an empty folder."
                );
            }

            string? driveRoot = Path.GetPathRoot(installDirectory);
            long minimumFreeSpace = existingInstall ? 3L * 1024 * 1024 * 1024 : 12L * 1024 * 1024 * 1024;
            if (driveRoot is null || new DriveInfo(driveRoot).AvailableFreeSpace < minimumFreeSpace)
            {
                throw new InvalidOperationException(
                    existingInstall
                        ? "At least 3 GB of free space is required to update Planline safely."
                        : "At least 12 GB of free space is recommended for the application and its machine-learning runtime."
                );
            }

            Directory.CreateDirectory(installDirectory);
            string tempDirectory = Path.Combine(Path.GetTempPath(), "PlanlineSetup");
            Directory.CreateDirectory(tempDirectory);
            string pythonInstaller = Path.Combine(tempDirectory, "python-3.14.10-amd64.exe");
            string webViewInstaller = Path.Combine(tempDirectory, "MicrosoftEdgeWebView2Setup.exe");

            string pythonDirectory = Path.Combine(installDirectory, "python");
            string python = Path.Combine(pythonDirectory, "python.exe");
            bool reusePythonRuntime = existingInstall && File.Exists(python);
            if (!reusePythonRuntime)
            {
                await SetStatusAsync("Downloading the private Python runtime…");
                await DownloadFileAsync(PythonUrl, pythonInstaller);
                await VerifySha256Async(pythonInstaller, PythonSha256);

                if (Directory.Exists(pythonDirectory))
                    Directory.Delete(pythonDirectory, recursive: true);

                await SetStatusAsync("Installing Planline's private Python runtime…");
                Directory.CreateDirectory(pythonDirectory);
                await RunProcessAsync(
                    pythonInstaller,
                    new[]
                    {
                        "/quiet",
                        "InstallAllUsers=0",
                        "PrependPath=0",
                        "Include_pip=1",
                        "Include_launcher=0",
                        "InstallLauncherAllUsers=0",
                        "Include_test=0",
                        "Include_doc=0",
                        "Shortcuts=0",
                        $"TargetDir={pythonDirectory}",
                    },
                    installDirectory
                );
            }
            else
            {
                await SetStatusAsync("Keeping your existing private Python and ML runtime…");
            }

            if (!File.Exists(python))
                throw new InvalidOperationException("The private Python runtime is missing after setup.");

            if (!IsWebView2Installed())
            {
                await SetStatusAsync("Downloading Microsoft WebView2…");
                await DownloadFileAsync(WebView2BootstrapperUrl, webViewInstaller);
                await SetStatusAsync("Installing Microsoft WebView2…");
                await RunProcessAsync(webViewInstaller, new[] { "/silent", "/install" }, installDirectory);
                if (!IsWebView2Installed())
                {
                    throw new InvalidOperationException(
                        "WebView2 could not be installed. Windows needs the Microsoft WebView2 Runtime to open Planline's desktop window."
                    );
                }
            }

            string appDirectory = Path.Combine(installDirectory, "app");
            if (Directory.Exists(appDirectory))
            {
                Directory.Delete(appDirectory, recursive: true);
            }
            Directory.CreateDirectory(appDirectory);

            await SetStatusAsync("Unpacking Planline…");
            using (Stream? source = Assembly.GetExecutingAssembly().GetManifestResourceStream("Planline.Source.zip"))
            {
                if (source is null)
                {
                    throw new InvalidOperationException("The installer does not contain the Planline application files.");
                }
                using var archive = new ZipArchive(source, ZipArchiveMode.Read);
                archive.ExtractToDirectory(appDirectory, overwriteFiles: true);
            }

            if (!File.Exists(Path.Combine(appDirectory, "yolo_floorplan.pt")) ||
                !File.Exists(Path.Combine(appDirectory, "planline", "desktop.py")))
            {
                throw new InvalidOperationException("The application archive is incomplete (model or desktop launcher missing).");
            }

            if (reusePythonRuntime)
            {
                await SetStatusAsync("Keeping your existing CPU/CUDA PyTorch runtime…");
            }
            else
            {
                await SetStatusAsync(useGpu
                    ? "Installing NVIDIA-enabled PyTorch (CUDA 12.6)…"
                    : "Installing the CPU PyTorch runtime…");

                if (useGpu)
                {
                    try
                    {
                        await InstallTorchAsync(python, TorchCudaIndex);
                        string cudaStatus = await RunProcessAsync(
                            python,
                            new[] { "-c", "import torch; print('CUDA_AVAILABLE=' + str(torch.cuda.is_available()))" },
                            appDirectory
                        );
                        if (!cudaStatus.Contains("CUDA_AVAILABLE=True", StringComparison.Ordinal))
                            throw new InvalidOperationException("The installed CUDA runtime did not detect a usable NVIDIA GPU.");
                    }
                    catch (Exception)
                    {
                        cpuFallback = true;
                        await SetStatusAsync("CUDA was unavailable. Installing the CPU-compatible runtime instead…");
                        await RunProcessAsync(
                            python,
                            new[] { "-m", "pip", "uninstall", "-y", "torch", "torchvision" },
                            appDirectory
                        );
                        await InstallTorchAsync(python, TorchCpuIndex);
                    }
                }
                else
                {
                    await InstallTorchAsync(python, TorchCpuIndex);
                }
            }

            await SetStatusAsync("Installing Planline's application libraries…");
            await RunProcessAsync(
                python,
                new[]
                {
                    "-m", "pip", "install",
                    "--disable-pip-version-check",
                    "--no-warn-script-location",
                    "-r", Path.Combine(appDirectory, "requirements-desktop.txt"),
                },
                appDirectory
            );

            await SetStatusAsync("Checking the installed application…");
            await RunProcessAsync(
                python,
                new[]
                {
                    "-c",
                    "import cv2, fastapi, torch, webview, ultralytics; " +
                    "print('Planline dependencies ready; torch=' + torch.__version__)",
                },
                appDirectory
            );

            await SetStatusAsync("Creating shortcuts and registering Planline…");
            string setupExecutable = Environment.ProcessPath ?? Application.ExecutablePath;
            string appExecutable = Path.Combine(installDirectory, "Planline.exe");
            string uninstallerExecutable = Path.Combine(installDirectory, "Planline.Uninstall.exe");
            CopyExecutable(setupExecutable, appExecutable);
            CopyExecutable(setupExecutable, uninstallerExecutable);

            string dataDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                Program.DataDirectoryName
            );
            Directory.CreateDirectory(dataDirectory);
            var markerData = new
            {
                product = Program.ProductName,
                version = Program.Version,
                installed_at_utc = DateTimeOffset.UtcNow,
                data_directory = dataDirectory,
                python_version = "3.14.10",
                accelerator = cpuFallback ? "cpu-fallback" : (useGpu ? "cuda-12.6" : "cpu"),
            };
            File.WriteAllText(marker, JsonSerializer.Serialize(markerData, new JsonSerializerOptions { WriteIndented = true }));

            try
            {
                CreateStartMenuShortcuts(installDirectory, appExecutable, uninstallerExecutable);
                if (_desktopShortcut.Checked)
                {
                    CreateShortcut(
                        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Planline.lnk"),
                        appExecutable,
                        installDirectory,
                        "Planline floor-plan and OCR workspace"
                    );
                }
                RegisterUninstallEntry(installDirectory, uninstallerExecutable);
            }
            catch (Exception exception)
            {
                await SetStatusAsync("Installed; Windows shortcut registration needs attention.");
                MessageBox.Show(
                    $"Planline was installed, but Windows could not create every shortcut or uninstall entry.\n\n{exception.Message}",
                    "Planline Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
            }

            _progressBar.Style = ProgressBarStyle.Continuous;
            _progressBar.Value = 100;
            _status.Text = "Installation complete.";

            string result = cpuFallback
                ? "Planline is installed. CUDA could not be started on this system, so the CPU runtime was installed instead."
                : useGpu
                    ? "Planline is installed with NVIDIA CUDA acceleration."
                    : "Planline is installed with the CPU runtime.";

            if (_autoInstall)
            {
                _status.Text = "Update complete. Restarting Planline…";
            }
            else
            {
                MessageBox.Show(
                    result + "\n\nOpen Planline from the desktop or Start menu.",
                    "Planline Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information
                );
            }

            if (_launchAfterInstall.Checked)
            {
                Process.Start(new ProcessStartInfo(appExecutable) { UseShellExecute = true });
            }

            Close();
        }
        catch (Exception exception)
        {
            _status.Text = "Installation did not finish.";
            _progressBar.Style = ProgressBarStyle.Continuous;
            _progressBar.Value = 0;
            MessageBox.Show(
                $"Planline could not be installed.\n\n{exception.Message}\n\n" +
                "You can run this installer again after resolving the issue.",
                "Planline Setup",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            _installButton.Enabled = true;
            _installButton.Text = "Retry";
            _gpuOption.Enabled = true;
            _cpuOption.Enabled = true;
            _installPath.Enabled = true;
            _workPanel.Visible = false;
            _setupOptions.Visible = true;
        }
    }

    private async Task InstallTorchAsync(string python, string indexUrl)
    {
        await RunProcessAsync(
            python,
            new[]
            {
                "-m", "pip", "install",
                "--progress-bar", "on",
                "--disable-pip-version-check",
                "--index-url", indexUrl,
                "torch==2.10.0",
                "torchvision==0.25.0",
            },
            Path.GetDirectoryName(python)!
        );
    }

    private Task SetStatusAsync(string message)
    {
        void Update()
        {
            _status.Text = message;
            _phaseLabel.Text = message;
            _status.Refresh();
        }
        if (InvokeRequired) BeginInvoke((Action)Update);
        else Update();
        return Task.CompletedTask;
    }

    private void UpdateAsset(string name, long downloaded, long? total, string status)
    {
        void Update()
        {
            if (!_assetRows.TryGetValue(name, out ListViewItem? item))
            {
                item = new ListViewItem(name);
                item.SubItems.Add("—");
                item.SubItems.Add("—");
                item.SubItems.Add(status);
                _assetProgress.Items.Add(item);
                _assetRows[name] = item;
            }
            item.SubItems[1].Text = total is > 0
                ? $"{FormatBytes(downloaded)} / {FormatBytes(total.Value)}"
                : FormatBytes(downloaded);
            item.SubItems[2].Text = total is > 0
                ? $"{Math.Clamp(downloaded * 100 / total.Value, 0, 100)}%"
                : "—";
            item.SubItems[3].Text = status;
            item.EnsureVisible();
        }
        if (IsHandleCreated && !IsDisposed)
        {
            if (InvokeRequired) BeginInvoke((Action)Update);
            else Update();
        }
    }

    private async Task DownloadFileAsync(string url, string destination)
    {
        using var response = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead);
        response.EnsureSuccessStatusCode();

        long? totalBytes = response.Content.Headers.ContentLength;
        string assetName = Path.GetFileName(destination);
        UpdateAsset(assetName, 0, totalBytes, "Downloading");
        await using Stream input = await response.Content.ReadAsStreamAsync();
        await using var output = new FileStream(
            destination,
            FileMode.Create,
            FileAccess.Write,
            FileShare.None,
            bufferSize: 1024 * 64,
            useAsync: true
        );

        byte[] buffer = new byte[1024 * 128];
        long totalRead = 0;
        int read;
        while ((read = await input.ReadAsync(buffer)) > 0)
        {
            await output.WriteAsync(buffer.AsMemory(0, read));
            totalRead += read;

            if (totalBytes is > 0)
            {
                int percent = (int)Math.Clamp(totalRead * 100 / totalBytes.Value, 0, 100);
                if (InvokeRequired) BeginInvoke((Action)(() => { _progressBar.Style = ProgressBarStyle.Continuous; _progressBar.Value = percent; }));
                else { _progressBar.Style = ProgressBarStyle.Continuous; _progressBar.Value = percent; }
            }
            UpdateAsset(assetName, totalRead, totalBytes, "Downloading");
            _progressDetail.Text = totalBytes is > 0
                ? $"{assetName}: {FormatBytes(totalRead)} of {FormatBytes(totalBytes.Value)}"
                : $"{assetName}: {FormatBytes(totalRead)} downloaded";
        }
        UpdateAsset(assetName, totalRead, totalBytes, "Downloaded");
    }

    private static async Task VerifySha256Async(string path, string expected)
    {
        await using var stream = File.OpenRead(path);
        byte[] hash = await SHA256.HashDataAsync(stream);
        string actual = Convert.ToHexString(hash).ToLowerInvariant();
        if (!CryptographicOperations.FixedTimeEquals(
            Convert.FromHexString(actual),
            Convert.FromHexString(expected)
        ))
        {
            File.Delete(path);
            throw new InvalidOperationException(
                "The Python download did not match the official SHA-256 checksum. The file was deleted."
            );
        }
    }

    private async Task<string> RunProcessAsync(
        string executable,
        IEnumerable<string> arguments,
        string workingDirectory
    )
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (string argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        var output = new List<string>();
        object outputLock = new();
        string? activeDownload = null;
        long? activeDownloadSize = null;

        void Capture(string? line, bool isError)
        {
            if (string.IsNullOrWhiteSpace(line)) return;

            lock (outputLock)
            {
                output.Add((isError ? "!" : "") + line);
                if (output.Count > 40) output.RemoveAt(0);
            }

            // pip reports each wheel separately. Keep those assets visible instead
            // of replacing the whole installer status with opaque console output.
            string trimmed = line.Trim();
            int marker = trimmed.IndexOf("Downloading ", StringComparison.OrdinalIgnoreCase);
            if (marker < 0)
                marker = trimmed.IndexOf("Using cached ", StringComparison.OrdinalIgnoreCase);
            if (marker >= 0)
            {
                string asset = trimmed[(marker + (trimmed.IndexOf("Using cached ", StringComparison.OrdinalIgnoreCase) == marker
                    ? "Using cached ".Length : "Downloading ".Length))..];
                int sizeStart = asset.IndexOf(" (", StringComparison.Ordinal);
                string assetPath = sizeStart >= 0 ? asset[..sizeStart] : asset;
                string assetName = assetPath.Split('/').LastOrDefault() ?? assetPath;
                activeDownload = Uri.UnescapeDataString(assetName);
                activeDownloadSize = null;
                if (sizeStart >= 0)
                {
                    Match sizeMatch = Regex.Match(asset[sizeStart..], @"\((?<n>[\d.]+)\s*(?<u>KB|MB|GB|B)\)", RegexOptions.IgnoreCase);
                    if (sizeMatch.Success)
                        activeDownloadSize = ParseAssetBytes(sizeMatch.Groups["n"].Value, sizeMatch.Groups["u"].Value);
                }
                UpdateAsset(activeDownload, 0, activeDownloadSize, "Downloading");
                _progressDetail.Text = $"Downloading package: {activeDownload}";
            }

            if (activeDownload is not null)
            {
                Match progress = Regex.Match(trimmed,
                    @"(?<p>\d{1,3})%.*?\|\s*(?<d>[\d.]+)\s*(?<du>KB|MB|GB|B)\s*/\s*(?<t>[\d.]+)\s*(?<tu>KB|MB|GB|B)",
                    RegexOptions.IgnoreCase);
                if (progress.Success)
                {
                    long done = ParseAssetBytes(progress.Groups["d"].Value, progress.Groups["du"].Value);
                    long total = ParseAssetBytes(progress.Groups["t"].Value, progress.Groups["tu"].Value);
                    activeDownloadSize = total;
                    UpdateAsset(activeDownload, done, total, "Downloading");
                    _progressDetail.Text = $"{activeDownload}: {FormatBytes(done)} of {FormatBytes(total)} ({progress.Groups["p"].Value}%)";
                }
                if (trimmed.Contains("Installing collected packages", StringComparison.OrdinalIgnoreCase) ||
                    trimmed.Contains("Successfully installed", StringComparison.OrdinalIgnoreCase))
                {
                    UpdateAsset(activeDownload, activeDownloadSize ?? 0, activeDownloadSize, "Downloaded");
                    activeDownload = null;
                    activeDownloadSize = null;
                }
            }

            string compact = trimmed.Length > 105 ? trimmed[^105..] : trimmed;
            if (IsHandleCreated && !IsDisposed)
            {
                try { BeginInvoke((Action)(() => _status.Text = compact)); }
                catch (InvalidOperationException) { /* Window is closing. */ }
            }
        }

        process.OutputDataReceived += (_, eventArgs) => Capture(eventArgs.Data, false);
        process.ErrorDataReceived += (_, eventArgs) => Capture(eventArgs.Data, true);

        if (!process.Start())
        {
            throw new InvalidOperationException($"Could not start {Path.GetFileName(executable)}.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await process.WaitForExitAsync();
        process.WaitForExit();

        if (process.ExitCode != 0)
        {
            string details;
            lock (outputLock)
            {
                details = string.Join(Environment.NewLine, output.TakeLast(18));
            }
            throw new InvalidOperationException(
                $"{Path.GetFileName(executable)} exited with code {process.ExitCode}.\n\n{details}"
            );
        }

        lock (outputLock)
        {
            return string.Join(Environment.NewLine, output);
        }
    }

    private static bool IsWebView2Installed()
    {
        string[] roots =
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "EdgeWebView", "Application"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "EdgeWebView", "Application"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "EdgeWebView", "Application"),
        };

        return roots.Any(root =>
            Directory.Exists(root) &&
            Directory.EnumerateDirectories(root)
                .Any(version => File.Exists(Path.Combine(version, "msedgewebview2.exe")))
        );
    }

    private static bool IsPlanlineRunning(string installDirectory)
    {
        foreach (Process process in Process.GetProcessesByName("Planline"))
        {
            using (process)
            {
                try
                {
                    string? executable = process.MainModule?.FileName;
                    if (executable is not null &&
                        Path.GetFullPath(executable).StartsWith(
                            Path.GetFullPath(installDirectory).TrimEnd(Path.DirectorySeparatorChar) +
                            Path.DirectorySeparatorChar,
                            StringComparison.OrdinalIgnoreCase
                        ))
                    {
                        return true;
                    }
                }
                catch
                {
                    // Another user's process or a protected process is not inspectable.
                }
            }
        }
        return false;
    }

    private static void CopyExecutable(string source, string destination)
    {
        if (Path.GetFullPath(source).Equals(Path.GetFullPath(destination), StringComparison.OrdinalIgnoreCase))
        {
            return;
        }
        File.Copy(source, destination, overwrite: true);
    }

    private static void CreateStartMenuShortcuts(
        string installDirectory,
        string appExecutable,
        string uninstallerExecutable
    )
    {
        string startMenu = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            "Planline"
        );
        Directory.CreateDirectory(startMenu);

        CreateShortcut(
            Path.Combine(startMenu, "Planline.lnk"),
            appExecutable,
            installDirectory,
            "Planline floor-plan and OCR workspace"
        );
        CreateShortcut(
            Path.Combine(startMenu, "Uninstall Planline.lnk"),
            uninstallerExecutable,
            installDirectory,
            "Uninstall Planline"
        );
    }

    private static void CreateShortcut(string shortcutPath, string target, string workingDirectory, string description)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell")
            ?? throw new InvalidOperationException("Windows Script Host is unavailable for shortcut creation.");

        object shell = Activator.CreateInstance(shellType)
            ?? throw new InvalidOperationException("Could not create the Windows shortcut service.");

        object? shortcut = null;
        try
        {
            dynamic shellObject = shell;
            shortcut = shellObject.CreateShortcut(shortcutPath);
            dynamic shortcutObject = shortcut;
            shortcutObject.TargetPath = target;
            shortcutObject.WorkingDirectory = workingDirectory;
            shortcutObject.Description = description;
            shortcutObject.IconLocation = target + ",0";
            shortcutObject.Save();
        }
        finally
        {
            if (shortcut is not null && Marshal.IsComObject(shortcut))
            {
                Marshal.FinalReleaseComObject(shortcut);
            }
            if (Marshal.IsComObject(shell))
            {
                Marshal.FinalReleaseComObject(shell);
            }
        }
    }

    private static void RegisterUninstallEntry(string installDirectory, string uninstallerExecutable)
    {
        using RegistryKey key = Registry.CurrentUser.CreateSubKey(
            @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Planline"
        );
        key.SetValue("DisplayName", "Planline");
        key.SetValue("DisplayVersion", Program.Version);
        key.SetValue("Publisher", "Marlu");
        key.SetValue("InstallLocation", installDirectory);
        key.SetValue("DisplayIcon", Path.Combine(installDirectory, "Planline.exe"));
        key.SetValue("UninstallString", $"\"{uninstallerExecutable}\"");
        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
    }

    private static long ParseAssetBytes(string value, string unit)
    {
        if (!double.TryParse(value, System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out double amount)) return 0;
        double multiplier = unit.ToUpperInvariant() switch
        {
            "KB" => 1024d,
            "MB" => 1024d * 1024,
            "GB" => 1024d * 1024 * 1024,
            _ => 1d,
        };
        return (long)(amount * multiplier);
    }

    private static string FormatBytes(long bytes)
    {
        string[] units = { "B", "KB", "MB", "GB" };
        double amount = bytes;
        int unit = 0;
        while (amount >= 1024 && unit < units.Length - 1)
        {
            amount /= 1024;
            unit++;
        }
        return $"{amount:0.0} {units[unit]}";
    }
}
