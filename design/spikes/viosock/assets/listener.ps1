# Native Windows vsock listener via the viosock Winsock provider (AF 40).
# Binds VMADDR_CID_ANY:5000, accepts one connection, echoes what it receives.
try {
Add-Type -TypeDefinition @"
public class VSockEndPoint : System.Net.EndPoint {
    public uint Cid; public uint Port;
    public override System.Net.Sockets.AddressFamily AddressFamily { get { return (System.Net.Sockets.AddressFamily)40; } }
    public override System.Net.SocketAddress Serialize() {
        var sa = new System.Net.SocketAddress((System.Net.Sockets.AddressFamily)40, 16);
        byte[] port = System.BitConverter.GetBytes(Port);
        byte[] cid = System.BitConverter.GetBytes(Cid);
        for (int i=0;i<4;i++) { sa[4+i]=port[i]; sa[8+i]=cid[i]; }
        return sa;
    }
    public override System.Net.EndPoint Create(System.Net.SocketAddress sa) { return new VSockEndPoint(); }
}
"@
$sock = New-Object System.Net.Sockets.Socket ([System.Net.Sockets.AddressFamily]40, [System.Net.Sockets.SocketType]::Stream, [System.Net.Sockets.ProtocolType]::Unspecified)
$ep = New-Object VSockEndPoint
$ep.Cid = 4294967295; $ep.Port = 5000
$sock.Bind($ep)
$sock.Listen(1)
Set-Content C:\vsock-listen.txt 'listening'
$client = $sock.Accept()
$buf = New-Object byte[] 64
$n = $client.Receive($buf)
$msg = [System.Text.Encoding]::ASCII.GetString($buf,0,$n)
$client.Send([System.Text.Encoding]::ASCII.GetBytes("echo:$msg")) | Out-Null
Set-Content C:\vsock-result.txt "received:$msg"
$client.Close(); $sock.Close()
} catch { Set-Content C:\vsock-error.txt $_.Exception.ToString() }
