#define TRACE
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

// Windows 10 1809 的商店入口只负责启动随包 Python，运行状态与用户数据由 Python 管理。
internal static class StoreLauncher
{
    [STAThread]
    private static int Main()
    {
        return Run(AppDomain.CurrentDomain.BaseDirectory, delegate(string message)
        {
            MessageBox.Show(message, "玄司", MessageBoxButtons.OK, MessageBoxIcon.Error);
        });
    }

    internal static int Run(string applicationDirectory, Action<string> showError)
    {
        try
        {
            string root = Path.GetFullPath(applicationDirectory);
            string python = Path.Combine(root, "runtime", "python", "pythonw.exe");
            string bootstrap = Path.Combine(root, "scripts", "store_bootstrap.py");
            if (!File.Exists(python) || !File.Exists(bootstrap))
            {
                Trace.TraceError("商店启动文件不完整");
                showError("玄司的安装文件不完整，请在微软商店修复或重新安装。");
                return 1;
            }

            // 固定绝对路径与工作目录；不通过 shell，也不将外部参数拼入命令行。
            var start = new ProcessStartInfo
            {
                FileName = python,
                // ._pth 隔离模式会忽略 Python 环境变量，显式 -B 才能禁止写入包内字节码。
                Arguments = "-B -X utf8 \"" + bootstrap + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            using (Process child = Process.Start(start))
            {
                if (child == null)
                    throw new InvalidOperationException();
                // 只关闭本启动器持有的句柄，不等待或终止独立运行的桌宠进程。
                Trace.TraceInformation("商店 Python 进程已启动");
            }
            return 0;
        }
        catch (Exception error)
        {
            // 可执行文件边界只记录异常类别，路径、命令行和环境内容不进入诊断。
            Trace.TraceError("商店启动失败，类别={0}", error.GetType().Name);
            showError("玄司暂时无法启动，请稍后重试，或在微软商店修复安装。");
            return 1;
        }
    }
}
