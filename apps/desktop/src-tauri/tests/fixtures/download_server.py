"""Ephemeral loopback HTTPS server for the Rust transport tests; never connects to a service."""

import datetime
import http.server
import json
import ssl
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

folder = Path(sys.argv[1])
now = datetime.datetime.now(datetime.UTC)
root_key = ec.generate_private_key(ec.SECP256R1())
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jana ephemeral transport test")])
root = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)
    .public_key(root_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=1))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .sign(root_key, hashes.SHA256())
)
key = ec.generate_private_key(ec.SECP256R1())
leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
leaf = (
    x509.CertificateBuilder()
    .subject_name(leaf_name)
    .issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=1))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .sign(root_key, hashes.SHA256())
)
(folder / "root.der").write_bytes(root.public_bytes(serialization.Encoding.DER))
(folder / "root.spki").write_bytes(
    root_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
)
(folder / "key.pem").write_bytes(
    key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
)
(folder / "chain.pem").write_bytes(
    leaf.public_bytes(serialization.Encoding.PEM) + root.public_bytes(serialization.Encoding.PEM)
)
# A self-signed certificate for the same name that the pinned root never signed: appended in front of the pinned
# root it makes the chain a pin must not accept.
stray_key = ec.generate_private_key(ec.SECP256R1())
stray = (
    x509.CertificateBuilder()
    .subject_name(leaf_name)
    .issuer_name(leaf_name)
    .public_key(stray_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=1))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .sign(stray_key, hashes.SHA256())
)
(folder / "stray.der").write_bytes(stray.public_bytes(serialization.Encoding.DER))
(folder / "leaf.der").write_bytes(leaf.public_bytes(serialization.Encoding.DER))
hits: dict[str, int] = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        import time

        with (folder / "requests.jsonl").open("a") as log:
            log.write(json.dumps({"path": self.path, "headers": dict(self.headers)}) + "\n")
        hits[self.path] = hits.get(self.path, 0) + 1
        if self.path == "/slow":
            time.sleep(5)
        if self.path in ("/redirect", "/outside"):
            self.send_response(302)
            self.send_header("Location", "/file" if self.path == "/redirect" else "https://outside.invalid/file")
            self.end_headers()
            return
        start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
        body = b"abcdefgh"[start : end + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{'9' if self.path == '/bad-range' else '8'}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            if self.path == "/throttled":
                # A slow but live link: one byte every 100 ms, so the whole body takes longer than the idle limit.
                for byte in body:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.1)
            elif self.path in ("/stall-half", "/drop-half") and hits[self.path] == 1:
                # The first answer delivers half the range, then stalls past the idle limit or drops.
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                if self.path == "/stall-half":
                    time.sleep(3)
                self.close_connection = True
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain(folder / "chain.pem", folder / "key.pem")
server.socket = tls.wrap_socket(server.socket, server_side=True)
print(json.dumps({"port": server.server_port}), flush=True)
server.serve_forever()
