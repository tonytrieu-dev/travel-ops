"""Issue one local demo device certificate; retain the CA offline after issuance."""
import argparse
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess


def run(*arguments: str) -> None:
    subprocess.run(["openssl", *arguments], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _validate_device_id(parser: argparse.ArgumentParser, device_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", device_id):
        parser.error("device ID must contain 1–64 letters, digits or hyphens")
    if device_id in {"ca", "server"}:
        parser.error("ca and server are reserved names")


def _ensure_authority(parser: argparse.ArgumentParser, directory: Path, authority: Path) -> None:
    """Create the offline CA once; refuse to silently replace an existing authority."""
    if (directory / "ca.key").exists():
        parser.error("Move ca.key, ca.crt and ca.srl from .device-certificates to the private .device-authority directory before issuing certificates")
    authority.mkdir(mode=0o700, exist_ok=True)
    authority.chmod(0o700)
    directory.mkdir(mode=0o700, exist_ok=True)
    if (authority / "ca.key").exists():
        return
    if (directory / "ca.crt").exists():
        parser.error("Existing certificates require their original authority in .device-authority; refusing to replace it")
    run("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "365",
        "-subj", "/CN=TravelOps device authority", "-keyout", str(authority / "ca.key"), "-out", str(authority / "ca.crt"))


def _issue_certificate(
    parser: argparse.ArgumentParser, directory: Path, authority: Path,
    name: str, subject: str, usage: str,
) -> None:
    key = directory / f"{name}.key"
    if key.exists():
        if name == "server":
            certificate = directory / "server.crt"
            if not certificate.exists():
                parser.error("server.key exists but server.crt is missing; refusing incomplete server credentials")
            try:
                run("verify", "-CAfile", str(directory / "ca.crt"), str(certificate))
            except subprocess.CalledProcessError:
                parser.error("existing server.key/server.crt do not validate; refusing incomplete server credentials")
            return
        parser.error("device already issued; refusing to overwrite")
    extension = directory / f"{name}.extensions"
    extension.write_text(f"extendedKeyUsage={usage}\n" + ("subjectAltName=DNS:localhost\n" if name == "server" else ""))
    run("req", "-new", "-newkey", "rsa:3072", "-nodes", "-subj", f"/CN={subject}", "-keyout", str(key), "-out", str(directory / f"{name}.csr"))
    run("x509", "-req", "-in", str(directory / f"{name}.csr"), "-CA", str(authority / "ca.crt"), "-CAkey", str(authority / "ca.key"), "-CAcreateserial", "-days", "7", "-extfile", str(extension), "-out", str(directory / f"{name}.crt"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device_id")
    arguments = parser.parse_args()
    _validate_device_id(parser, arguments.device_id)
    os.umask(0o077)
    directory = Path(".device-certificates")
    authority = Path(".device-authority")
    _ensure_authority(parser, directory, authority)
    shutil.copyfile(authority / "ca.crt", directory / "ca.crt")
    for name, subject, usage in (("server", "localhost", "serverAuth"), (arguments.device_id, arguments.device_id, "clientAuth")):
        _issue_certificate(parser, directory, authority, name, subject, usage)
    password = directory / f"{arguments.device_id}.password"
    password.write_text(secrets.token_urlsafe(24))
    run("pkcs12", "-export", "-inkey", str(directory / f"{arguments.device_id}.key"), "-in", str(directory / f"{arguments.device_id}.crt"), "-certfile", str(directory / "ca.crt"), "-out", str(directory / f"{arguments.device_id}.p12"), "-passout", f"file:{password}")
    print("Certificate issued. Import the device .p12 using its private .password file.")


if __name__ == "__main__":
    main()
