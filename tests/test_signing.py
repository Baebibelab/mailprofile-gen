import datetime
import io
import plistlib
import shutil
import subprocess

import pytest
import yaml

pytest.importorskip("cryptography")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from mailprofile_gen.cli import main  # noqa: E402
from mailprofile_gen.signing import SigningError, sign_profile  # noqa: E402

PLIST = plistlib.dumps({"PayloadType": "Configuration", "Clé": "valeur"})


def make_cert(key, cn="Test mailprofile-gen"):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )


@pytest.fixture
def rsa_material(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = make_cert(key)
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key, cert, cert_path, key_path


def extract_content(signed: bytes, tmp_path):
    """Vérifie la signature avec openssl et renvoie le contenu signé."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl indisponible")
    signed_path = tmp_path / "signed.der"
    signed_path.write_bytes(signed)
    result = subprocess.run(
        [openssl, "smime", "-verify", "-noverify", "-binary", "-inform", "DER", "-in", str(signed_path)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout in signed  # contenu embarqué tel quel, sans conversion CRLF
    return result.stdout


def test_sign_with_pem_cert_and_key(rsa_material, tmp_path):
    _, _, cert_path, key_path = rsa_material
    signed = sign_profile(PLIST, cert_path, key_path)
    assert signed[:1] == b"\x30"  # DER SEQUENCE
    assert extract_content(signed, tmp_path) == PLIST


def test_sign_with_combined_pem(rsa_material, tmp_path):
    _, _, cert_path, key_path = rsa_material
    combined = tmp_path / "combined.pem"
    combined.write_bytes(cert_path.read_bytes() + key_path.read_bytes())
    assert extract_content(sign_profile(PLIST, combined), tmp_path) == PLIST


def test_sign_with_encrypted_p12(rsa_material, tmp_path):
    key, cert, _, _ = rsa_material
    p12 = tmp_path / "id.p12"
    p12.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"id", key, cert, None, serialization.BestAvailableEncryption(b"motdepasse")
        )
    )
    with pytest.raises(SigningError, match="mot de passe"):
        sign_profile(PLIST, p12)
    with pytest.raises(SigningError, match="incorrect"):
        sign_profile(PLIST, p12, password_cb=lambda _: b"faux")
    signed = sign_profile(PLIST, p12, password_cb=lambda _: b"motdepasse")
    assert extract_content(signed, tmp_path) == PLIST


def test_sign_with_ec_key(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = make_cert(key)
    combined = tmp_path / "ec.pem"
    combined.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    assert extract_content(sign_profile(PLIST, combined), tmp_path) == PLIST


def test_errors(rsa_material, tmp_path):
    _, _, cert_path, _ = rsa_material
    with pytest.raises(SigningError, match="--sign-key"):
        sign_profile(PLIST, cert_path)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_key_path = tmp_path / "other.pem"
    other_key_path.write_bytes(
        other_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    with pytest.raises(SigningError, match="ne correspond pas"):
        sign_profile(PLIST, cert_path, other_key_path)
    with pytest.raises(SigningError, match="impossible de lire"):
        sign_profile(PLIST, tmp_path / "absent.pem", other_key_path)


def test_cli_signs_profile(rsa_material, tmp_path, base_config):
    _, _, cert_path, key_path = rsa_material
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(base_config), encoding="utf-8")
    cfg.chmod(0o600)
    output = tmp_path / "signed.mobileconfig"
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["-c", str(cfg), "-o", str(output), "--sign-cert", str(cert_path), "--sign-key", str(key_path)],
        out=out,
        err=err,
    )
    assert code == 0, err.getvalue()
    assert "signé" in out.getvalue() and "non signé" not in out.getvalue()
    content = extract_content(output.read_bytes(), tmp_path)
    assert len(plistlib.loads(content)["PayloadContent"]) == 2
