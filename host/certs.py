"""Local CA and HTTPS certificate for the PC's IP addresses.

Phones only expose motion sensors to secure pages, so Wi-Fi and tethering
modes serve HTTPS. We create a private CA once (the user trusts it on the
phone) and issue a server certificate for the PC's current IPs from it.

The CA carries name constraints so it can only vouch for private IPs and
localhost: if its key ever leaked it could not be used to impersonate public
websites on the phone.
"""

import datetime as dt
import ipaddress
import logging
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

log = logging.getLogger(__name__)

CA_DAYS = 3650
CERT_DAYS = 397      # Apple rejects server certs valid for longer than 398 days
RENEW_DAYS = 30
PRIVATE_NETS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"]


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _write_key(key, path):
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _load(cert_path, key_path):
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), None)
        return cert, key
    except (OSError, ValueError):
        return None, None


def ensure_ca(directory):
    """Load the CA from `directory`, creating it on first run."""
    cert_path, key_path = directory / "ca.crt", directory / "ca.key"
    cert, key = _load(cert_path, key_path)
    if cert is not None and cert.not_valid_after_utc > _now() + dt.timedelta(days=RENEW_DAYS):
        return cert, key

    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenSteer"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"OpenSteer local CA ({socket.gethostname()[:32]})"),
    ])
    constraints = x509.NameConstraints(
        permitted_subtrees=[x509.IPAddress(ipaddress.ip_network(n)) for n in PRIVATE_NETS]
        + [x509.DNSName("localhost")],
        excluded_subtrees=None,
    )
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(constraints, critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key, key_path)
    log.info("Created local CA %s", cert_path)
    return cert, key


def _covers(cert, ca_cert, ips):
    if cert.issuer != ca_cert.subject:
        return False
    if cert.not_valid_after_utc < _now() + dt.timedelta(days=RENEW_DAYS):
        return False
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    have = set(san.get_values_for_type(x509.IPAddress))
    return all(ipaddress.ip_address(ip) in have for ip in ips)


def ensure_server_cert(directory, ips):
    """Return (cert_path, key_path) for a cert valid for `ips`, reissuing if needed."""
    ca_cert, ca_key = ensure_ca(directory)
    cert_path, key_path = directory / "server.crt", directory / "server.key"
    ips = sorted({*ips, "127.0.0.1"})
    cert, _ = _load(cert_path, key_path)
    if cert is not None and _covers(cert, ca_cert, ips):
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    now = _now()
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenSteer host")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=CERT_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_encipherment=False, key_cert_sign=False, crl_sign=False,
            content_commitment=False, data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key, key_path)
    log.info("Issued HTTPS certificate for %s", ", ".join(ips))
    return cert_path, key_path


def ssl_context(cert_path, key_path):
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx
