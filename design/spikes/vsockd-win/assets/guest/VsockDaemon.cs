// vsockd for Windows: parity port of the Linux spike daemon
// (design/spikes/e2e-provider/guest/vsockd2.py). Same wire protocol:
// newline-terminated JSON header, sized raw streams, ops ping/exec/stat/
// write/read, errno-name tagged errors, 16 MiB per-stream output cap,
// in-daemon timeout with process-TREE kill (Job Object), connections
// accepted only from CID 2 (the hypervisor host).
//
// Target: .NET Framework 4.8, C# 5 syntax (compiled in-guest with the
// in-box csc.exe on Server 2022; no modern language features).
// The wire format lives entirely in JsonLineCodec (the protocol-v3 seam).

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace VsockD
{
    // ---------------------------------------------------------------- vsock

    sealed class VSockEndPoint : EndPoint
    {
        public const int AF_VSOCK = 40;
        public const uint VMADDR_CID_ANY = 0xFFFFFFFF;
        public uint Cid;
        public uint Port;

        public VSockEndPoint(uint cid, uint port) { Cid = cid; Port = port; }

        public override AddressFamily AddressFamily
        {
            get { return (AddressFamily)AF_VSOCK; }
        }

        public override SocketAddress Serialize()
        {
            SocketAddress sa = new SocketAddress((AddressFamily)AF_VSOCK, 16);
            byte[] port = BitConverter.GetBytes(Port);
            byte[] cid = BitConverter.GetBytes(Cid);
            for (int i = 0; i < 4; i++) { sa[4 + i] = port[i]; sa[8 + i] = cid[i]; }
            return sa;
        }

        public override EndPoint Create(SocketAddress sa)
        {
            byte[] port = new byte[4];
            byte[] cid = new byte[4];
            for (int i = 0; i < 4; i++) { port[i] = sa[4 + i]; cid[i] = sa[8 + i]; }
            return new VSockEndPoint(BitConverter.ToUInt32(cid, 0), BitConverter.ToUInt32(port, 0));
        }
    }

    // The viosock Winsock provider does not implement blocking waits: recv on
    // an empty queue (and send into full buffers) fails with WSAEWOULDBLOCK
    // regardless of the socket's blocking mode. These helpers turn that into
    // poll-and-retry semantics; peer close still surfaces as recv 0 / reset.
    static class Io
    {
        // STATUS_BUFFER_TOO_SMALL: the provider's report both for oversized
        // single sends and for a full TX buffer (its EAGAIN analog)
        private const int STATUS_BUFFER_TOO_SMALL = unchecked((int)0xC0000023);

        private static bool Retryable(SocketException se)
        {
            return se.SocketErrorCode == SocketError.WouldBlock
                || se.NativeErrorCode == STATUS_BUFFER_TOO_SMALL;
        }

        public static int Recv(Socket s, byte[] buf, int off, int len)
        {
            while (true)
            {
                try { return s.Receive(buf, off, len, SocketFlags.None); }
                catch (SocketException se)
                {
                    if (!Retryable(se)) throw;
                }
                WaitReadable(s);
            }
        }

        // the provider also rejects large single sends with
        // STATUS_BUFFER_TOO_SMALL rather than sending partially: chunk small
        public const int SEND_CHUNK = 32 * 1024;

        public static void SendAll(Socket s, byte[] buf, int off, int len)
        {
            // the provider's select is unreliable, so a full TX buffer is
            // waited out by yielding; back off to 1 ms sleeps only after
            // sustained stalls (peer not draining)
            int sent = 0;
            int stall = 0;
            while (sent < len)
            {
                try
                {
                    sent += s.Send(buf, off + sent, Math.Min(SEND_CHUNK, len - sent), SocketFlags.None);
                    stall = 0;
                }
                catch (SocketException se)
                {
                    if (!Retryable(se)) throw;
                    stall++;
                    if (stall < 2000) Thread.Sleep(0); else Thread.Sleep(1);
                }
            }
        }

        private static void WaitReadable(Socket s)
        {
            try { s.Poll(1000000, SelectMode.SelectRead); }
            catch (Exception) { Thread.Sleep(1); }
        }

        private static void WaitWritable(Socket s)
        {
            try { s.Poll(1000000, SelectMode.SelectWrite); }
            catch (Exception) { Thread.Sleep(1); }
        }
    }

    // Buffered reads with remainder carry: never 1-byte recv (punch list 1).
    sealed class SockReader
    {
        private readonly Socket _s;
        private byte[] _buf = new byte[0];
        private int _pos;

        public SockReader(Socket s) { _s = s; }

        public string ReadLine(int maxLen)
        {
            MemoryStream line = new MemoryStream();
            while (true)
            {
                if (_pos >= _buf.Length)
                {
                    byte[] chunk = new byte[1 << 16];
                    int n = Io.Recv(_s, chunk, 0, chunk.Length);
                    if (n == 0) throw new IOException("eof before header line");
                    _buf = chunk; Array.Resize(ref _buf, n); _pos = 0;
                }
                while (_pos < _buf.Length)
                {
                    byte b = _buf[_pos++];
                    if (b == (byte)'\n')
                        return Encoding.UTF8.GetString(line.ToArray());
                    line.WriteByte(b);
                    if (line.Length > maxLen) throw new IOException("header too long");
                }
            }
        }

        public void ReadExact(byte[] dest, long count)
        {
            long got = 0;
            int avail = _buf.Length - _pos;
            if (avail > 0)
            {
                int take = (int)Math.Min(avail, count);
                Array.Copy(_buf, _pos, dest, 0, take);
                _pos += take; got = take;
            }
            while (got < count)
            {
                int want = (int)Math.Min(1 << 20, count - got);
                int n = Io.Recv(_s, dest, (int)got, want);
                if (n == 0) throw new IOException("short stream");
                got += n;
            }
        }
    }

    // ---------------------------------------------------------------- codec

    interface IRequestCodec
    {
        Dictionary<string, object> ReadHeader(SockReader r);
        void WriteReply(Socket s, Dictionary<string, object> reply);
    }

    sealed class JsonLineCodec : IRequestCodec
    {
        private readonly JavaScriptSerializer _json;

        public JsonLineCodec()
        {
            _json = new JavaScriptSerializer();
            _json.MaxJsonLength = int.MaxValue;
        }

        public Dictionary<string, object> ReadHeader(SockReader r)
        {
            // generous: self_check sends ~1 MiB argv in the header; strict
            // reader-side caps are protocol-v3 work
            string line = r.ReadLine(8 << 20);
            return _json.Deserialize<Dictionary<string, object>>(line);
        }

        public void WriteReply(Socket s, Dictionary<string, object> reply)
        {
            byte[] data = Encoding.UTF8.GetBytes(_json.Serialize(reply) + "\n");
            Io.SendAll(s, data, 0, data.Length);
        }
    }

    // ----------------------------------------------------------- native API

    static class Native
    {
        [StructLayout(LayoutKind.Sequential)]
        public struct SECURITY_ATTRIBUTES
        {
            public int nLength;
            public IntPtr lpSecurityDescriptor;
            public bool bInheritHandle;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct STARTUPINFO
        {
            public int cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public short wShowWindow, cbReserved2;
            public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct PROCESS_INFORMATION
        {
            public IntPtr hProcess, hThread;
            public int dwProcessId, dwThreadId;
        }

        public const uint CREATE_SUSPENDED = 0x4;
        public const uint CREATE_NO_WINDOW = 0x08000000;
        public const uint CREATE_UNICODE_ENVIRONMENT = 0x400;
        public const int STARTF_USESTDHANDLES = 0x100;
        public const uint INFINITE = 0xFFFFFFFF;
        public const uint WAIT_TIMEOUT = 0x102;
        public const int LOGON32_LOGON_INTERACTIVE = 2;
        public const int LOGON32_PROVIDER_DEFAULT = 0;
        public const uint HANDLE_FLAG_INHERIT = 1;

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref SECURITY_ATTRIBUTES sa, uint size);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool SetHandleInformation(IntPtr h, uint mask, uint flags);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool CreateProcessW(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit,
            uint flags, IntPtr env, string cwd, ref STARTUPINFO si, out PROCESS_INFORMATION pi);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool CreateProcessAsUserW(IntPtr token, string app, StringBuilder cmd, IntPtr pa, IntPtr ta,
            bool inherit, uint flags, IntPtr env, string cwd, ref STARTUPINFO si, out PROCESS_INFORMATION pi);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool LogonUserW(string user, string domain, string pass, int type, int provider, out IntPtr token);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr CreateJobObject(IntPtr attrs, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool TerminateJobObject(IntPtr job, uint exitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint ResumeThread(IntPtr thread);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint WaitForSingleObject(IntPtr h, uint ms);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool GetExitCodeProcess(IntPtr h, out uint code);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr h);

        [DllImport("winmm.dll")]
        public static extern uint timeBeginPeriod(uint ms);
    }

    // ------------------------------------------------------------ exec

    sealed class CappedPipeReader
    {
        public const int OUTPUT_CAP = 16 * 1024 * 1024;  // parity with vsockd2.py
        public MemoryStream Head = new MemoryStream();
        public long Total;
        private readonly FileStream _fs;
        public Thread Thread;

        public CappedPipeReader(IntPtr handle)
        {
            _fs = new FileStream(new Microsoft.Win32.SafeHandles.SafeFileHandle(handle, true), FileAccess.Read);
            Thread = new Thread(Run);
            Thread.IsBackground = true;
            Thread.Start();
        }

        private void Run()
        {
            byte[] buf = new byte[1 << 16];
            try
            {
                while (true)
                {
                    int n = _fs.Read(buf, 0, buf.Length);
                    if (n <= 0) break;
                    Total += n;
                    if (Head.Length < OUTPUT_CAP)
                        Head.Write(buf, 0, (int)Math.Min(n, OUTPUT_CAP - Head.Length));
                }
            }
            catch (Exception) { }
            finally { _fs.Close(); }
        }
    }

    static class ExecEngine
    {
        public static Dictionary<string, object> Run(List<string> argv, string cwd, Dictionary<string, string> envOverrides,
            string user, double? timeoutSeconds, byte[] stdin)
        {
            if (cwd != null)
            {
                if (File.Exists(cwd))
                    return Reply.Errno("not a directory: " + cwd, "ENOTDIR");
                if (!Directory.Exists(cwd))
                    return Reply.Errno("no such directory: " + cwd, "ENOENT");
            }

            IntPtr token = IntPtr.Zero;
            if (user != null)
            {
                string password = Config.PasswordFor(user);
                if (password == null)
                    return Reply.ExecFailure(1, "user " + user + " does not exist or has no configured credentials");
                if (!Native.LogonUserW(user, ".", password, Native.LOGON32_LOGON_INTERACTIVE,
                        Native.LOGON32_PROVIDER_DEFAULT, out token))
                    return Reply.ExecFailure(1, "logon failed for user " + user + " (error " +
                        Marshal.GetLastWin32Error() + ")");
            }

            try { return RunWithToken(argv, cwd, envOverrides, token, timeoutSeconds, stdin); }
            finally { if (token != IntPtr.Zero) Native.CloseHandle(token); }
        }

        private static Dictionary<string, object> RunWithToken(List<string> argv, string cwd,
            Dictionary<string, string> envOverrides, IntPtr token, double? timeoutSeconds, byte[] stdin)
        {
            Native.SECURITY_ATTRIBUTES sa = new Native.SECURITY_ATTRIBUTES();
            sa.nLength = Marshal.SizeOf(typeof(Native.SECURITY_ATTRIBUTES));
            sa.bInheritHandle = true;

            IntPtr stdinR, stdinW, stdoutR, stdoutW, stderrR, stderrW;
            if (!Native.CreatePipe(out stdinR, out stdinW, ref sa, 0) ||
                !Native.CreatePipe(out stdoutR, out stdoutW, ref sa, 0) ||
                !Native.CreatePipe(out stderrR, out stderrW, ref sa, 0))
                return Reply.Errno("pipe creation failed", "EIO");
            // only the child-facing ends may be inherited
            Native.SetHandleInformation(stdinW, Native.HANDLE_FLAG_INHERIT, 0);
            Native.SetHandleInformation(stdoutR, Native.HANDLE_FLAG_INHERIT, 0);
            Native.SetHandleInformation(stderrR, Native.HANDLE_FLAG_INHERIT, 0);

            Native.STARTUPINFO si = new Native.STARTUPINFO();
            si.cb = Marshal.SizeOf(typeof(Native.STARTUPINFO));
            si.dwFlags = Native.STARTF_USESTDHANDLES;
            si.hStdInput = stdinR;
            si.hStdOutput = stdoutW;
            si.hStdError = stderrW;
            si.lpDesktop = "";

            StringBuilder cmdline = new StringBuilder(BuildCommandLine(argv));
            if (cmdline.Length > 32766)  // hard Windows limit (UNICODE_STRING)
                return Reply.Errno("command line too long: " + cmdline.Length +
                    " chars (Windows limit 32767)", "E2BIG");
            IntPtr envBlock = BuildEnvBlock(envOverrides);
            uint flags = Native.CREATE_SUSPENDED | Native.CREATE_NO_WINDOW | Native.CREATE_UNICODE_ENVIRONMENT;

            Native.PROCESS_INFORMATION pi;
            bool ok;
            if (token == IntPtr.Zero)
                ok = Native.CreateProcessW(null, cmdline, IntPtr.Zero, IntPtr.Zero, true, flags, envBlock, cwd, ref si, out pi);
            else
                ok = Native.CreateProcessAsUserW(token, null, cmdline, IntPtr.Zero, IntPtr.Zero, true, flags, envBlock, cwd, ref si, out pi);

            Marshal.FreeHGlobal(envBlock);
            if (!ok)
            {
                int err = Marshal.GetLastWin32Error();
                Native.CloseHandle(stdinR); Native.CloseHandle(stdinW);
                Native.CloseHandle(stdoutR); Native.CloseHandle(stdoutW);
                Native.CloseHandle(stderrR); Native.CloseHandle(stderrW);
                if (err == 2 || err == 3)  // file / path not found
                    return Reply.ExecFailure(127, "command not found: " + argv[0]);
                if (err == 5 || err == 193)  // access denied / not a valid executable
                    return Reply.ExecFailure(126, "permission denied: " + argv[0]);
                return Reply.Errno("CreateProcess failed (error " + err + ")", "EIO");
            }

            IntPtr job = Native.CreateJobObject(IntPtr.Zero, null);
            Native.AssignProcessToJobObject(job, pi.hProcess);
            Native.ResumeThread(pi.hThread);
            Native.CloseHandle(pi.hThread);
            // close the child-facing ends in this process so pipe reads can EOF
            Native.CloseHandle(stdinR);
            Native.CloseHandle(stdoutW);
            Native.CloseHandle(stderrW);

            CappedPipeReader outReader = new CappedPipeReader(stdoutR);
            CappedPipeReader errReader = new CappedPipeReader(stderrR);

            Thread stdinWriter = new Thread(delegate ()
            {
                FileStream w = new FileStream(new Microsoft.Win32.SafeHandles.SafeFileHandle(stdinW, true), FileAccess.Write);
                try { if (stdin != null && stdin.Length > 0) w.Write(stdin, 0, stdin.Length); }
                catch (Exception) { }
                finally { w.Close(); }
            });
            stdinWriter.IsBackground = true;
            stdinWriter.Start();

            // deadline covers both process exit and pipe drain (parity with
            // communicate(timeout=...): a backgrounded child holding stdout
            // counts against the timeout and triggers the tree kill)
            long deadlineTicks = timeoutSeconds.HasValue
                ? DateTime.UtcNow.Ticks + (long)(timeoutSeconds.Value * TimeSpan.TicksPerSecond)
                : long.MaxValue;

            bool timedOut = false;
            uint waitMs = RemainingMs(deadlineTicks);
            if (Native.WaitForSingleObject(pi.hProcess, waitMs) == Native.WAIT_TIMEOUT)
                timedOut = true;

            if (!timedOut)
            {
                if (!outReader.Thread.Join(RemainingJoinMs(deadlineTicks)) ||
                    !errReader.Thread.Join(RemainingJoinMs(deadlineTicks)))
                    timedOut = true;
            }

            Dictionary<string, object> reply;
            if (timedOut)
            {
                Native.TerminateJobObject(job, 1);
                Native.WaitForSingleObject(pi.hProcess, 10000);
                outReader.Thread.Join(5000);
                errReader.Thread.Join(5000);
                reply = new Dictionary<string, object>();
                reply["timeout"] = true;
            }
            else
            {
                uint rc;
                Native.GetExitCodeProcess(pi.hProcess, out rc);
                reply = new Dictionary<string, object>();
                reply["rc"] = (long)rc;
                reply["stdout"] = Convert.ToBase64String(outReader.Head.ToArray());
                reply["stderr"] = Convert.ToBase64String(errReader.Head.ToArray());
                reply["stdout_truncated"] = outReader.Total > CappedPipeReader.OUTPUT_CAP;
                reply["stderr_truncated"] = errReader.Total > CappedPipeReader.OUTPUT_CAP;
            }
            stdinWriter.Join(1000);
            Native.CloseHandle(pi.hProcess);
            Native.CloseHandle(job);  // no KILL_ON_CLOSE: background children survive
            return reply;
        }

        private static uint RemainingMs(long deadlineTicks)
        {
            if (deadlineTicks == long.MaxValue) return Native.INFINITE;
            long ms = (deadlineTicks - DateTime.UtcNow.Ticks) / TimeSpan.TicksPerMillisecond;
            return ms <= 0 ? 0 : (uint)Math.Min(ms, uint.MaxValue - 1);
        }

        private static int RemainingJoinMs(long deadlineTicks)
        {
            if (deadlineTicks == long.MaxValue) return Timeout.Infinite;
            long ms = (deadlineTicks - DateTime.UtcNow.Ticks) / TimeSpan.TicksPerMillisecond;
            return ms <= 0 ? 0 : (int)Math.Min(ms, int.MaxValue);
        }

        // standard Windows argv quoting (everything CommandLineToArgvW will
        // reverse): quote when needed, double backslashes before quotes
        public static string BuildCommandLine(List<string> argv)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < argv.Count; i++)
            {
                if (i > 0) sb.Append(' ');
                string a = argv[i];
                bool needQuote = a.Length == 0 || a.IndexOfAny(new char[] { ' ', '\t', '"' }) >= 0;
                if (!needQuote) { sb.Append(a); continue; }
                sb.Append('"');
                int backslashes = 0;
                foreach (char c in a)
                {
                    if (c == '\\') { backslashes++; continue; }
                    if (c == '"')
                    {
                        sb.Append('\\', backslashes * 2 + 1);
                        sb.Append('"');
                        backslashes = 0;
                        continue;
                    }
                    sb.Append('\\', backslashes);
                    backslashes = 0;
                    sb.Append(c);
                }
                sb.Append('\\', backslashes * 2);
                sb.Append('"');
            }
            return sb.ToString();
        }

        private static IntPtr BuildEnvBlock(Dictionary<string, string> overrides)
        {
            SortedDictionary<string, string> env =
                new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (DictionaryEntry e in Environment.GetEnvironmentVariables())
                env[(string)e.Key] = (string)e.Value;
            if (overrides != null)
                foreach (KeyValuePair<string, string> kv in overrides)
                    env[kv.Key] = kv.Value;

            StringBuilder sb = new StringBuilder();
            foreach (KeyValuePair<string, string> kv in env)
            {
                sb.Append(kv.Key); sb.Append('='); sb.Append(kv.Value); sb.Append('\0');
            }
            sb.Append('\0');
            return Marshal.StringToHGlobalUni(sb.ToString());
        }
    }

    // ------------------------------------------------------------ handlers

    static class Reply
    {
        public static Dictionary<string, object> Errno(string message, string errnoName)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["error"] = message;
            d["errno"] = errnoName;
            return d;
        }

        public static Dictionary<string, object> ExecFailure(long rc, string stderr)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["rc"] = rc;
            d["stdout"] = "";
            d["stderr"] = Convert.ToBase64String(Encoding.UTF8.GetBytes(stderr));
            d["stdout_truncated"] = false;
            d["stderr_truncated"] = false;
            return d;
        }
    }

    static class Config
    {
        public static string BaseDir = "C:\\vsockd";

        public static string PasswordFor(string user)
        {
            try
            {
                string path = Path.Combine(BaseDir, "users.txt");
                if (!File.Exists(path)) return null;
                foreach (string line in File.ReadAllLines(path))
                {
                    int i = line.IndexOf(':');
                    if (i > 0 && line.Substring(0, i).Equals(user, StringComparison.OrdinalIgnoreCase))
                        return line.Substring(i + 1);
                }
            }
            catch (Exception) { }
            return null;
        }
    }

    static class Daemon
    {
        public const int PORT = 5000;
        private static readonly IRequestCodec Codec = new JsonLineCodec();

        public static void Log(string msg)
        {
            try
            {
                File.AppendAllText(Path.Combine(Config.BaseDir, "vsockd.log"),
                    DateTime.UtcNow.ToString("o") + " " + msg + "\r\n");
            }
            catch (Exception) { }
        }

        public static void ListenLoop()
        {
            string work = Path.Combine(Config.BaseDir, "work");
            Directory.CreateDirectory(work);
            Directory.SetCurrentDirectory(work);
            Native.timeBeginPeriod(1);  // 1 ms sleep granularity for the retry waits

            Socket listener = new Socket((AddressFamily)VSockEndPoint.AF_VSOCK, SocketType.Stream, ProtocolType.Unspecified);
            listener.Bind(new VSockEndPoint(VSockEndPoint.VMADDR_CID_ANY, PORT));
            listener.Listen(16);
            Log("listening on vsock port " + PORT);

            while (true)
            {
                Socket conn;
                try { conn = listener.Accept(); }
                catch (Exception e) { Log("accept: " + e.Message); continue; }

                try { conn.Blocking = true; } catch (Exception) { }
                // large buffers amortize the provider's full-TX stalls
                try { conn.SendBufferSize = 4 << 20; conn.ReceiveBufferSize = 4 << 20; } catch (Exception) { }
                VSockEndPoint peer = null;
                try { peer = conn.RemoteEndPoint as VSockEndPoint; }
                catch (Exception e) { Log("peer: " + e.Message); }
                if (peer == null || peer.Cid != 2)  // host-only control plane; fail closed
                {
                    conn.Close();
                    continue;
                }
                Thread t = new Thread(delegate () { HandleConn(conn); });
                t.IsBackground = true;
                t.Start();
            }
        }

        private static void HandleConn(Socket conn)
        {
            try
            {
                SockReader reader = new SockReader(conn);
                Dictionary<string, object> req = Codec.ReadHeader(reader);
                byte[] readBody = null;
                Dictionary<string, object> reply;
                try { reply = Handle(req, reader, out readBody); }
                catch (Exception e)
                {
                    Log("handle error: " + e.GetType().Name + ": " + e.Message);
                    reply = new Dictionary<string, object>();
                    reply["error"] = e.Message;
                }
                Codec.WriteReply(conn, reply);
                if (readBody != null)
                    Io.SendAll(conn, readBody, 0, readBody.Length);
            }
            catch (Exception e) { Log("conn: " + e.Message); }
            finally { try { conn.Close(); } catch (Exception) { } }
        }

        private static Dictionary<string, object> Handle(Dictionary<string, object> req, SockReader reader, out byte[] readBody)
        {
            readBody = null;
            string op = req.ContainsKey("op") ? (string)req["op"] : "";
            Dictionary<string, object> reply = new Dictionary<string, object>();

            if (op == "ping")
            {
                reply["ok"] = true;
                return reply;
            }

            if (op == "exec")
            {
                List<string> argv = new List<string>();
                foreach (object o in (ArrayList)req["cmd"]) argv.Add((string)o);
                string cwd = Get(req, "cwd") as string;
                string user = Get(req, "user") as string;
                double? timeout = null;
                object t = Get(req, "timeout");
                if (t != null) timeout = Convert.ToDouble(t);
                Dictionary<string, string> env = null;
                object envObj = Get(req, "env");
                if (envObj != null)
                {
                    env = new Dictionary<string, string>();
                    foreach (KeyValuePair<string, object> kv in (Dictionary<string, object>)envObj)
                        env[kv.Key] = Convert.ToString(kv.Value);
                }
                byte[] stdin = null;
                object inputSize = Get(req, "input_size");
                if (inputSize != null)
                {
                    long n = Convert.ToInt64(inputSize);
                    stdin = new byte[n];
                    reader.ReadExact(stdin, n);
                }
                return ExecEngine.Run(argv, cwd, env, user, timeout, stdin);
            }

            if (op == "stat")
            {
                string path = (string)req["path"];
                if (Directory.Exists(path))
                {
                    reply["size"] = 0L;
                    reply["isdir"] = true;
                    return reply;
                }
                if (!File.Exists(path))
                    return Reply.Errno("No such file or directory: " + path, "ENOENT");
                try
                {
                    reply["size"] = new FileInfo(path).Length;
                    reply["isdir"] = false;
                    return reply;
                }
                catch (Exception e) { return FileError(e, path); }
            }

            if (op == "write")
            {
                string path = (string)req["path"];
                long size = Convert.ToInt64(req["size"]);
                byte[] data = new byte[size];
                reader.ReadExact(data, size);
                try
                {
                    string dir = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                    if (Directory.Exists(path))
                        return Reply.Errno("Is a directory: " + path, "EISDIR");
                    File.WriteAllBytes(path, data);
                    reply["ok"] = true;
                    return reply;
                }
                catch (Exception e) { return FileError(e, path); }
            }

            if (op == "read")
            {
                string path = (string)req["path"];
                if (Directory.Exists(path))
                    return Reply.Errno("Is a directory: " + path, "EISDIR");
                if (!File.Exists(path))
                    return Reply.Errno("No such file or directory: " + path, "ENOENT");
                try
                {
                    readBody = File.ReadAllBytes(path);
                    reply["size"] = (long)readBody.Length;
                    return reply;
                }
                catch (Exception e) { readBody = null; return FileError(e, path); }
            }

            return Reply.Errno("unknown op " + op, "EINVAL");
        }

        private static object Get(Dictionary<string, object> req, string key)
        {
            object v;
            return req.TryGetValue(key, out v) ? v : null;
        }

        private static Dictionary<string, object> FileError(Exception e, string path)
        {
            string name = "EIO";
            if (e is FileNotFoundException || e is DirectoryNotFoundException) name = "ENOENT";
            else if (e is UnauthorizedAccessException) name = "EACCES";
            else if (e is PathTooLongException) name = "ENAMETOOLONG";
            return Reply.Errno(e.Message + ": " + path, name);
        }
    }

    sealed class DaemonService : ServiceBase
    {
        public DaemonService() { ServiceName = "vsockd"; }

        protected override void OnStart(string[] args)
        {
            Thread t = new Thread(Daemon.ListenLoop);
            t.IsBackground = true;
            t.Start();
        }

        protected override void OnStop() { }
    }

    static class Program
    {
        static int Main(string[] args)
        {
            if (args.Length > 0 && args[0] == "-console")
            {
                Daemon.Log("console mode start");
                Daemon.ListenLoop();
                return 0;
            }
            ServiceBase.Run(new DaemonService());
            return 0;
        }
    }
}
