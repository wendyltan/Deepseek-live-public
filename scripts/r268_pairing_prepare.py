"""Prepare a private, idempotent R268 Mac LAN WSS identity (no network listener).

This tool does not touch ESP32, Wi-Fi passwords, official DSH, USB, or SD.
Only use with the verified Mac-mini and on a trusted user-owned LAN.
"""
from __future__ import annotations
import ipaddress,json,os,secrets,stat,subprocess,shutil
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Deepseek-live/lan-pairing"
DEVICE="dafeiyu-esp32-s3"
OPENSSL=os.environ.get("DAFEIYU_OPENSSL_BIN") or shutil.which("openssl") or "/usr/bin/openssl"
PORT=8877
def addr(iface):
    p=subprocess.run(["ipconfig","getifaddr",iface],capture_output=True,text=True,timeout=4)
    if p.returncode:return None
    try:return str(ipaddress.IPv4Address(p.stdout.strip()))
    except ipaddress.AddressValueError:return None

def check_private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid!=os.getuid():
        raise RuntimeError("private_identity_path_unsafe")
    if stat.S_IMODE(path.stat().st_mode)&0o077:
        raise RuntimeError("private_identity_file_permissions")

def main():
    addresses=[x for x in (addr("en0"),addr("en1")) if x]
    if not addresses:raise RuntimeError("no_lan_ipv4_on_mac")
    if ROOT.is_symlink():raise RuntimeError("pair_dir_symlink")
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(ROOT,0o700)
    json_path=ROOT/"authorized-devices.json"
    crt=ROOT/"gateway.crt.pem";key=ROOT/"gateway.key.pem";der=ROOT/"gateway.ca.der"
    if any(p.exists() for p in (json_path,crt,key,der)):
        for p in (json_path,crt,key,der):check_private(p)
        data=json.loads(json_path.read_text())
        if not data.get("devices",{}).get(DEVICE):
            raise RuntimeError("paired_identity_incomplete")
        print("R268_TLS_IDENTITY_ALREADY_EXISTS keep_existing=true")
        return
    config=ROOT/"tls-openssl.conf"
    sans=",".join(f"IP:{a}" for a in dict.fromkeys(addresses))
    config.write_text("[req]\ndistinguished_name=req_distinguished_name\nx509_extensions=v3_req\nprompt=no\n"
      "[req_distinguished_name]\nCN=Deepseek-live R268 Mac Voice\n"
      "[v3_req]\nbasicConstraints=critical,CA:TRUE\n"
      "keyUsage=critical,digitalSignature,keyCertSign\n"
      "extendedKeyUsage=serverAuth\n"
      f"subjectAltName={sans},DNS:Mac-mini.local\n")
    os.chmod(config,0o600)
    try:
        subprocess.run([OPENSSL,"req","-x509","-newkey","ec",
            "-pkeyopt","ec_paramgen_curve:prime256v1",
            "-nodes","-days","730","-sha256",
            "-keyout",str(key),"-out",str(crt),
            "-config",str(config),"-extensions","v3_req"],
            capture_output=True,text=True,check=True,timeout=20)
        subprocess.run([OPENSSL,"x509","-in",str(crt),
                        "-outform","DER","-out",str(der)],
                        capture_output=True,text=True,check=True,timeout=12)
        token=secrets.token_hex(32)
        json_path.write_text(json.dumps({"schema":1,"devices":{DEVICE:token}},
                                         separators=(",",":"))+"\n")
        for p in (crt,key,der,json_path):os.chmod(p,0o600)
        print("R268_TLS_PRIVATE_IDENTITY_CREATED mac_ipv4_count="+str(len(addresses))+
          " cert_der_bytes="+str(der.stat().st_size)+
          " bearer_bits=256 private_mode=0600 model_calls=0")
    finally:
        if config.exists():config.unlink()

if __name__=="__main__":main()
