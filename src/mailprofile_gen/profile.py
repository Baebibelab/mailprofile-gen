"""Construction, validation et écriture du profil .mobileconfig."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .config import Account, Config, ProfileMeta

MAIL_PAYLOAD_TYPE = "com.apple.mail.managed"


class ProfileError(Exception):
    """Le profil généré est invalide (ne devrait pas arriver avec une config validée)."""


# --------------------------------------------------------------------------
# Identifiants stables
# --------------------------------------------------------------------------


def profile_namespace(identifier: str) -> uuid.UUID:
    """Espace de noms uuid5 propre à un identifiant de profil."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, identifier)


def profile_uuid(meta: ProfileMeta) -> str:
    return str(uuid.uuid5(profile_namespace(meta.identifier), "profile")).upper()


def account_uuid(meta: ProfileMeta, email: str) -> str:
    """UUID stable dérivé de l'adresse (insensible à la casse)."""
    return str(uuid.uuid5(profile_namespace(meta.identifier), "mail:" + email.strip().lower())).upper()


def account_identifier(meta: ProfileMeta, email: str) -> str:
    """PayloadIdentifier lisible et stable, ex. com.x.mailprofile.mail.contact.at.exemple.fr."""
    slug = email.strip().lower().replace("@", ".at.")
    slug = re.sub(r"[^a-z0-9.-]", "-", slug)
    slug = re.sub(r"\.{2,}", ".", slug).strip(".")
    return f"{meta.identifier}.mail.{slug}"


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def build_mail_payload(meta: ProfileMeta, account: Account) -> dict[str, Any]:
    imap, smtp = account.imap, account.smtp
    payload: dict[str, Any] = {
        "PayloadType": MAIL_PAYLOAD_TYPE,
        "PayloadVersion": 1,
        "PayloadIdentifier": account_identifier(meta, account.email),
        "PayloadUUID": account_uuid(meta, account.email),
        "PayloadDisplayName": f"Mail : {account.description}",
        "PayloadDescription": f"Compte IMAP {account.email}",
        # Libellé du compte dans Mail et Réglages
        "EmailAccountDescription": account.description,
        # Nom affiché comme expéditeur
        "EmailAccountName": account.name,
        "EmailAccountType": "EmailTypeIMAP",
        "EmailAddress": account.email,
        "IncomingMailServerAuthentication": imap.auth,
        "IncomingMailServerHostName": imap.host,
        "IncomingMailServerPortNumber": imap.port,
        "IncomingMailServerUseSSL": imap.ssl,
        "IncomingMailServerUsername": imap.username,
        "OutgoingMailServerAuthentication": smtp.auth,
        "OutgoingMailServerHostName": smtp.host,
        "OutgoingMailServerPortNumber": smtp.port,
        "OutgoingMailServerUseSSL": smtp.ssl,
        "OutgoingMailServerUsername": smtp.username,
        "OutgoingPasswordSameAsIncomingPassword": (
            imap.password is not None and smtp.password == imap.password
        ),
    }
    if imap.path_prefix:
        payload["IncomingMailServerIMAPPathPrefix"] = imap.path_prefix
    if imap.password is not None:
        payload["IncomingPassword"] = imap.password
    if smtp.password is not None:
        payload["OutgoingPassword"] = smtp.password
    return payload


def build_profile(config: Config) -> dict[str, Any]:
    meta = config.profile
    count = len(config.accounts)
    description = meta.description or (
        f"Configure {count} compte{'s' if count > 1 else ''} mail IMAP : "
        + ", ".join(a.email for a in config.accounts)
    )
    profile: dict[str, Any] = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": meta.identifier,
        "PayloadUUID": profile_uuid(meta),
        "PayloadDisplayName": meta.name,
        "PayloadDescription": description,
        "PayloadRemovalDisallowed": False,
        # Sur macOS, les comptes mail s'installent pour l'utilisateur.
        "PayloadScope": "User",
        "PayloadContent": [build_mail_payload(meta, a) for a in config.accounts],
    }
    if meta.organization:
        profile["PayloadOrganization"] = meta.organization
    return profile


# --------------------------------------------------------------------------
# Validation du plist
# --------------------------------------------------------------------------

_TOP_REQUIRED = {
    "PayloadType": str,
    "PayloadVersion": int,
    "PayloadIdentifier": str,
    "PayloadUUID": str,
    "PayloadDisplayName": str,
    "PayloadContent": list,
}

_MAIL_REQUIRED = {
    "PayloadType": str,
    "PayloadVersion": int,
    "PayloadIdentifier": str,
    "PayloadUUID": str,
    "EmailAccountType": str,
    "EmailAddress": str,
    "IncomingMailServerAuthentication": str,
    "IncomingMailServerHostName": str,
    "IncomingMailServerPortNumber": int,
    "IncomingMailServerUseSSL": bool,
    "IncomingMailServerUsername": str,
    "OutgoingMailServerAuthentication": str,
    "OutgoingMailServerHostName": str,
    "OutgoingMailServerPortNumber": int,
    "OutgoingMailServerUseSSL": bool,
    "OutgoingMailServerUsername": str,
}

_MAIL_OPTIONAL = {
    "PayloadDisplayName": str,
    "PayloadDescription": str,
    "EmailAccountDescription": str,
    "EmailAccountName": str,
    "IncomingPassword": str,
    "OutgoingPassword": str,
    "OutgoingPasswordSameAsIncomingPassword": bool,
    "IncomingMailServerIMAPPathPrefix": str,
}


def _check_keys(obj: dict, required: dict, optional: dict, where: str, problems: list[str]) -> None:
    for key, typ in required.items():
        if key not in obj:
            problems.append(f"{where} : clé obligatoire absente {key}")
    for key, value in obj.items():
        typ = required.get(key) or optional.get(key)
        if typ is None:
            continue
        # bool est une sous-classe d'int : on l'exclut explicitement.
        if (typ is int and isinstance(value, bool)) or not isinstance(value, typ):
            problems.append(f"{where} : {key} devrait être de type {typ.__name__}")


def validate_profile(profile: dict[str, Any]) -> bytes:
    """Vérifie la structure du profil et renvoie le plist XML sérialisé.

    Lève ``ProfileError`` si un problème est détecté.
    """
    problems: list[str] = []
    _check_keys(
        profile,
        _TOP_REQUIRED,
        {"PayloadOrganization": str, "PayloadDescription": str, "PayloadRemovalDisallowed": bool, "PayloadScope": str},
        "profil",
        problems,
    )
    if profile.get("PayloadType") != "Configuration":
        problems.append("profil : PayloadType doit valoir « Configuration »")

    uuids = [profile.get("PayloadUUID")]
    identifiers = [profile.get("PayloadIdentifier")]
    content = profile.get("PayloadContent")
    if isinstance(content, list):
        if not content:
            problems.append("profil : PayloadContent est vide")
        for i, payload in enumerate(content):
            where = f"payload[{i}]"
            if not isinstance(payload, dict):
                problems.append(f"{where} : doit être un dictionnaire")
                continue
            _check_keys(payload, _MAIL_REQUIRED, _MAIL_OPTIONAL, where, problems)
            if payload.get("PayloadType") != MAIL_PAYLOAD_TYPE:
                problems.append(f"{where} : PayloadType doit valoir {MAIL_PAYLOAD_TYPE}")
            if payload.get("EmailAccountType") != "EmailTypeIMAP":
                problems.append(f"{where} : EmailAccountType doit valoir EmailTypeIMAP")
            uuids.append(payload.get("PayloadUUID"))
            identifiers.append(payload.get("PayloadIdentifier"))

    for value in uuids:
        try:
            uuid.UUID(str(value))
        except ValueError:
            problems.append(f"PayloadUUID invalide : {value!r}")
    if len(set(uuids)) != len(uuids):
        problems.append("PayloadUUID en double dans le profil")
    if len(set(identifiers)) != len(identifiers):
        problems.append("PayloadIdentifier en double dans le profil")

    if problems:
        raise ProfileError("\n".join(problems))

    try:
        data = plistlib.dumps(profile, fmt=plistlib.FMT_XML, sort_keys=True)
        reloaded = plistlib.loads(data)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProfileError(f"sérialisation plist impossible : {exc}") from exc
    if reloaded != profile:
        raise ProfileError("le plist relu ne correspond pas au profil généré")
    return data


def lint_with_plutil(data: bytes) -> str | None:
    """Contrôle supplémentaire avec ``plutil -lint`` (macOS uniquement).

    Renvoie un message d'erreur, ou None si OK ou si plutil est indisponible.
    """
    plutil = shutil.which("plutil")
    if plutil is None:
        return None
    try:
        result = subprocess.run(
            [plutil, "-lint", "-"], input=data, capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return (result.stdout + result.stderr).decode("utf-8", "replace").strip() or "plutil -lint a échoué"
    return None


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------


def write_private_file(path: str | Path, data: bytes) -> Path:
    """Écrit ``data`` dans ``path`` avec les permissions 600, de façon atomique.

    Le fichier temporaire est créé directement en 600 (mkstemp), si bien que
    le contenu n'est jamais lisible par d'autres utilisateurs, même brièvement.
    """
    path = Path(path)
    directory = path.parent if str(path.parent) else Path(".")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            os.chmod(tmp_name, 0o600)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return path
