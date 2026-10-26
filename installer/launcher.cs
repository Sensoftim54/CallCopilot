// Call Copilot Setup.exe: unpacks the embedded installer into a temp folder and runs Setup.cmd in this console.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

[assembly: AssemblyTitle("Call Copilot Setup")]
[assembly: AssemblyProduct("Call Copilot")]
[assembly: AssemblyVersion("1.0.0.0")]

class Launcher
{
    static int Main(string[] args)
    {
        string dir = Path.Combine(Path.GetTempPath(), "CallCopilotSetup-" + Guid.NewGuid().ToString("N").Substring(0, 8));
        Directory.CreateDirectory(dir);
        Assembly asm = Assembly.GetExecutingAssembly();
        foreach (string name in new[] { "Setup.cmd", "setup.ps1", "app.zip" })
        {
            using (Stream src = asm.GetManifestResourceStream(name))
            using (FileStream dst = File.Create(Path.Combine(dir, name)))
                src.CopyTo(dst);
        }
        var psi = new ProcessStartInfo("cmd.exe", "/c \"\"" + Path.Combine(dir, "Setup.cmd") + "\" " + string.Join(" ", args) + "\"")
        {
            UseShellExecute = false,
            WorkingDirectory = dir
        };
        Process p = Process.Start(psi);
        p.WaitForExit();
        try { Directory.Delete(dir, true); } catch { }
        return p.ExitCode;
    }
}
