import datetime as dt
import ipaddress

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from host import certs


def verify(ca, leaf, ip):
    verifier = PolicyBuilder().store(Store([ca])).build_server_verifier(
        x509.IPAddress(ipaddress.ip_address(ip)))
    verifier.verify(leaf, [])


def load(path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_server_cert_verifies_for_its_ips(tmp_path):
    cert_path, _ = certs.ensure_server_cert(tmp_path, ["192.168.1.20", "10.0.0.5"])
    ca, leaf = load(tmp_path / "ca.crt"), load(cert_path)
    for ip in ("192.168.1.20", "10.0.0.5", "127.0.0.1"):
        verify(ca, leaf, ip)
    with pytest.raises(VerificationError):
        verify(ca, leaf, "192.168.1.21")
    assert leaf.not_valid_after_utc - leaf.not_valid_before_utc <= dt.timedelta(days=398)


def test_reuses_cert_until_ips_change(tmp_path):
    first, _ = certs.ensure_server_cert(tmp_path, ["192.168.1.20"])
    serial = load(first).serial_number
    certs.ensure_server_cert(tmp_path, ["192.168.1.20"])
    assert load(first).serial_number == serial
    certs.ensure_server_cert(tmp_path, ["192.168.1.20", "192.168.43.10"])
    assert load(first).serial_number != serial


def test_ca_is_stable(tmp_path):
    a, _ = certs.ensure_ca(tmp_path)
    b, _ = certs.ensure_ca(tmp_path)
    assert a == b


def _forge(ca_cert, ca_key, san):
    """A leaf the CA's name constraints must reject."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "forged")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )


def test_ca_cannot_sign_public_names(tmp_path):
    ca, key = certs.ensure_ca(tmp_path)
    with pytest.raises(VerificationError):
        verify(ca, _forge(ca, key, x509.IPAddress(ipaddress.ip_address("8.8.8.8"))), "8.8.8.8")
    leaf = _forge(ca, key, x509.DNSName("example.com"))
    verifier = PolicyBuilder().store(Store([ca])).build_server_verifier(x509.DNSName("example.com"))
    with pytest.raises(VerificationError):
        verifier.verify(leaf, [])
