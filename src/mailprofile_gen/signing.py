"""Signature facultative du profil (CMS/PKCS#7, signature attachée, DER).

Nécessite le paquet ``cryptography`` : ``pip install 'mailprofile-gen[sign]'``.

Formats acceptés :
- un fichier PKCS#12 (.p12 / .pfx) contenant certificat + clé (+ chaîne) ;
- un certificat PEM/DER et une clé privée PEM/DER (la clé peut être dans le
  même fichier PEM que le certificat), plus d'éventuels certificats
  intermédiaires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

PasswordCallback = Callable[[str], "bytes | None"]


class SigningError(Exception):
    pass


def _import_crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
    except ImportError:  # pragma: no cover - dépend de l'environnement
        raise SigningError(
            "la signature nécessite le paquet « cryptography » : "
            "pip install 'mailprofile-gen[sign]' (ou pip install cryptography)"
        ) from None
    return x509, hashes, serialization, pkcs7, pkcs12


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SigningError(f"impossible de lire {path} : {exc.strerror}") from None


def _load_certificates(data: bytes, path: Path) -> list:
    x509 = _import_crypto()[0]
    if b"-----BEGIN CERTIFICATE-----" in data:
        try:
            return list(x509.load_pem_x509_certificates(data))
        except ValueError as exc:
            raise SigningError(f"{path} : certificat PEM illisible ({exc})") from None
    try:
        return [x509.load_der_x509_certificate(data)]
    except ValueError:
        raise SigningError(f"{path} : aucun certificat PEM ou DER trouvé") from None


def _load_private_key(data: bytes, path: Path, password_cb: PasswordCallback | None):
    serialization = _import_crypto()[2]
    loader = serialization.load_pem_private_key if b"-----BEGIN" in data else serialization.load_der_private_key
    try:
        return loader(data, password=None)
    except TypeError:
        # Clé chiffrée : il faut un mot de passe.
        password = password_cb(f"Mot de passe de la clé privée {path.name} : ") if password_cb else None
        if not password:
            raise SigningError(
                f"{path} : la clé privée est protégée par un mot de passe "
                "(définissez MAILPROFILE_SIGN_PASSWORD ou lancez la commande dans un terminal)"
            ) from None
        try:
            return loader(data, password=password)
        except (ValueError, TypeError):
            raise SigningError(f"{path} : mot de passe incorrect ou clé illisible") from None
    except ValueError as exc:
        raise SigningError(f"{path} : clé privée illisible ({exc})") from None


def _load_pkcs12(path: Path, password_cb: PasswordCallback | None):
    pkcs12 = _import_crypto()[4]
    data = _read(path)
    attempts: list[bytes | None] = [None, b""]
    for password in attempts:
        try:
            return pkcs12.load_key_and_certificates(data, password)
        except ValueError:
            continue
    password = password_cb(f"Mot de passe du fichier {path.name} : ") if password_cb else None
    if not password:
        raise SigningError(
            f"{path} : fichier PKCS#12 protégé par un mot de passe "
            "(définissez MAILPROFILE_SIGN_PASSWORD ou lancez la commande dans un terminal)"
        )
    try:
        return pkcs12.load_key_and_certificates(data, password)
    except ValueError:
        raise SigningError(f"{path} : mot de passe incorrect ou fichier PKCS#12 invalide") from None


def sign_profile(
    data: bytes,
    cert_path: str | Path,
    key_path: str | Path | None = None,
    chain_paths: Sequence[str | Path] = (),
    password_cb: PasswordCallback | None = None,
) -> bytes:
    """Signe ``data`` et renvoie la structure CMS au format DER."""
    _, hashes, serialization, pkcs7, _ = _import_crypto()
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    cert_path = Path(cert_path)
    extra: list = []
    if cert_path.suffix.lower() in {".p12", ".pfx"}:
        if key_path is not None:
            raise SigningError("--sign-key est inutile avec un fichier .p12/.pfx (la clé y est incluse)")
        key, cert, additional = _load_pkcs12(cert_path, password_cb)
        if key is None or cert is None:
            raise SigningError(f"{cert_path} : le fichier doit contenir un certificat et sa clé privée")
        extra.extend(additional or [])
    else:
        cert_data = _read(cert_path)
        certs = _load_certificates(cert_data, cert_path)
        cert, extra = certs[0], certs[1:]
        if key_path is None:
            if b"PRIVATE KEY-----" not in cert_data:
                raise SigningError(
                    f"{cert_path} ne contient pas de clé privée : indiquez-la avec --sign-key"
                )
            key = _load_private_key(cert_data, cert_path, password_cb)
        else:
            key_path = Path(key_path)
            key = _load_private_key(_read(key_path), key_path, password_cb)

    if not isinstance(key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
        raise SigningError("type de clé non pris en charge (RSA ou ECDSA attendu)")
    pub = serialization.PublicFormat.SubjectPublicKeyInfo
    enc = serialization.Encoding.DER
    if key.public_key().public_bytes(enc, pub) != cert.public_key().public_bytes(enc, pub):
        raise SigningError("la clé privée ne correspond pas au certificat")

    for chain_path in chain_paths:
        chain_path = Path(chain_path)
        extra.extend(_load_certificates(_read(chain_path), chain_path))

    builder = pkcs7.PKCS7SignatureBuilder().set_data(data).add_signer(cert, key, hashes.SHA256())
    seen = {cert.fingerprint(hashes.SHA256())}
    for c in extra:
        fp = c.fingerprint(hashes.SHA256())
        if fp not in seen:
            seen.add(fp)
            builder = builder.add_certificate(c)
    try:
        # Signature attachée (le plist est inclus dans la structure CMS).
        # Binary : signer les octets tels quels, sans conversion LF -> CRLF.
        return builder.sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    except (ValueError, TypeError) as exc:
        raise SigningError(f"échec de la signature : {exc}") from None
