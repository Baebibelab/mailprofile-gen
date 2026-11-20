"""Chargement et validation du fichier de configuration YAML.

Toutes les erreurs détectées sont collectées puis levées en une seule fois
(``ConfigError``) afin que l'utilisateur puisse tout corriger d'un coup.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .providers import BUILTIN_PROVIDERS

# Méthodes d'authentification acceptées -> constante Apple.
AUTH_METHODS = {
    "password": "EmailAuthPassword",
    "crammd5": "EmailAuthCRAMMD5",
    "ntlm": "EmailAuthNTLM",
    "httpmd5": "EmailAuthHTTPMD5",
    "none": "EmailAuthNone",
}

TOP_LEVEL_KEYS = {"profile", "default_provider", "providers", "accounts"}
PROFILE_KEYS = {"name", "organization", "identifier", "description"}
PROVIDER_KEYS = {"imap", "smtp"}
SERVER_KEYS = {"host", "port", "ssl", "auth"}
IMAP_EXTRA_KEYS = {"path_prefix"}
ACCOUNT_KEYS = {
    "name",
    "email",
    "username",
    "password",
    "provider",
    "description",
    "imap",
    "smtp",
}
ACCOUNT_SERVER_KEYS = SERVER_KEYS | {"username", "password"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$")

DEFAULT_PROFILE_NAME = "Comptes mail"


class ConfigError(Exception):
    """Configuration invalide. ``errors`` contient un message par problème."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    ssl: bool
    username: str
    password: str | None
    auth: str  # constante Apple, ex. "EmailAuthPassword"
    path_prefix: str | None = None


@dataclass(frozen=True)
class Account:
    name: str
    email: str
    description: str
    provider: str | None
    imap: ServerSettings
    smtp: ServerSettings


@dataclass(frozen=True)
class ProfileMeta:
    name: str
    identifier: str
    organization: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Config:
    profile: ProfileMeta
    accounts: tuple[Account, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------


def load_config(path: str | Path) -> Config:
    """Lit et valide un fichier YAML. Lève ``ConfigError`` en cas de problème."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            [
                f"fichier de configuration introuvable : {path} "
                "(copiez config.example.yaml en config.yaml pour commencer)"
            ]
        ) from None
    except OSError as exc:
        raise ConfigError([f"impossible de lire {path} : {exc.strerror}"]) from None
    except UnicodeDecodeError:
        raise ConfigError([f"{path} n'est pas un fichier texte UTF-8"]) from None
    return parse_config(text, source=str(path))


def parse_config(text: str, source: str = "<config>") -> Config:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        where = ""
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            where = f" (ligne {mark.line + 1}, colonne {mark.column + 1})"
        problem = getattr(exc, "problem", None) or str(exc)
        raise ConfigError([f"{source} : YAML invalide{where} : {problem}"]) from None
    if data is None:
        raise ConfigError([f"{source} : le fichier est vide"])
    return validate_config(data)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


class _Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        # Fournisseurs déjà signalés comme invalides : on évite les erreurs en cascade.
        self.broken_providers: set[str] = set()

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path} : {message}" if path else message)

    def warn(self, path: str, message: str) -> None:
        self.warnings.append(f"{path} : {message}")

    # -- types de base ----------------------------------------------------

    def mapping(self, value: Any, path: str, allowed: set[str]) -> dict | None:
        if not isinstance(value, Mapping):
            self.error(path, f"doit être un dictionnaire (clé: valeur), trouvé {_type_name(value)}")
            return None
        for key in value:
            if not isinstance(key, str):
                self.error(path, f"clé non textuelle : {key!r}")
            elif key not in allowed:
                hint = difflib.get_close_matches(key, sorted(allowed), n=1)
                suggestion = f" (vouliez-vous dire « {hint[0]} » ?)" if hint else ""
                self.error(
                    f"{path}.{key}" if path else key,
                    f"clé inconnue{suggestion} ; clés autorisées : {', '.join(sorted(allowed))}",
                )
        return dict(value)

    def string(self, value: Any, path: str, *, secret: bool = False) -> str | None:
        if isinstance(value, str):
            if not value.strip():
                self.error(path, "ne doit pas être vide")
                return None
            return value
        if value is None:
            self.error(path, "valeur manquante")
            return None
        if isinstance(value, (bool, int, float)):
            shown = "<masqué>" if secret else repr(value)
            self.error(
                path,
                f"doit être une chaîne de caractères, trouvé {_type_name(value)} {shown} ; "
                'mettez la valeur entre guillemets dans le YAML (ex. "0123") '
                "pour qu'elle ne soit pas interprétée comme un nombre ou un booléen",
            )
            return None
        self.error(path, f"doit être une chaîne de caractères, trouvé {_type_name(value)}")
        return None

    def port(self, value: Any, path: str) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            self.error(path, f"le port doit être un entier, trouvé {_type_name(value)} {value!r}")
            return None
        if not 1 <= value <= 65535:
            self.error(path, f"le port doit être compris entre 1 et 65535, trouvé {value}")
            return None
        return value

    def boolean(self, value: Any, path: str) -> bool | None:
        if not isinstance(value, bool):
            self.error(path, f"doit valoir true ou false, trouvé {_type_name(value)} {value!r}")
            return None
        return value

    def host(self, value: Any, path: str) -> str | None:
        host = self.string(value, path)
        if host is None:
            return None
        if "://" in host or not HOST_RE.match(host):
            self.error(path, f"nom d'hôte invalide {host!r} (attendu ex. ssl0.ovh.net, sans protocole ni port)")
            return None
        return host

    def auth(self, value: Any, path: str) -> str | None:
        name = self.string(value, path)
        if name is None:
            return None
        if name.lower() not in AUTH_METHODS:
            self.error(path, f"méthode inconnue {name!r} ; valeurs possibles : {', '.join(AUTH_METHODS)}")
            return None
        return AUTH_METHODS[name.lower()]

    # -- blocs -------------------------------------------------------------

    def server_block(self, value: Any, path: str, kind: str, *, account: bool) -> dict | None:
        """Valide un bloc imap/smtp (partiel) et renvoie les valeurs valides."""
        allowed = set(ACCOUNT_SERVER_KEYS if account else SERVER_KEYS)
        if kind == "imap":
            allowed |= IMAP_EXTRA_KEYS
        block = self.mapping(value, path, allowed)
        if block is None:
            return None
        out: dict[str, Any] = {}
        checks = {
            "host": self.host,
            "port": self.port,
            "ssl": self.boolean,
            "auth": self.auth,
            "username": self.string,
            "path_prefix": self.string,
        }
        for key, check in checks.items():
            if key in block and key in allowed:
                result = check(block[key], f"{path}.{key}")
                if result is not None:
                    out[key] = result
        if "password" in block and "password" in allowed:
            pwd = self.string(block["password"], f"{path}.password", secret=True)
            if pwd is not None:
                out["password"] = pwd
        return out

    def profile(self, value: Any) -> ProfileMeta | None:
        if value is None:
            self.error("profile", "section manquante (au minimum : profile.identifier)")
            return None
        block = self.mapping(value, "profile", PROFILE_KEYS)
        if block is None:
            return None
        name = DEFAULT_PROFILE_NAME
        if "name" in block:
            name = self.string(block["name"], "profile.name") or DEFAULT_PROFILE_NAME
        identifier = None
        if "identifier" not in block:
            self.error(
                "profile.identifier",
                "obligatoire (ex. com.romain.mailprofile) ; il doit rester identique "
                "d'une génération à l'autre pour que le profil soit remplacé et non dupliqué",
            )
        else:
            identifier = self.string(block["identifier"], "profile.identifier")
            if identifier is not None and not IDENTIFIER_RE.match(identifier):
                self.error(
                    "profile.identifier",
                    f"identifiant invalide {identifier!r} ; format attendu en notation DNS inversée, "
                    "lettres, chiffres et tirets séparés par des points (ex. com.romain.mailprofile)",
                )
                identifier = None
        organization = None
        if block.get("organization") is not None:
            organization = self.string(block["organization"], "profile.organization")
        description = None
        if block.get("description") is not None:
            description = self.string(block["description"], "profile.description")
        if identifier is None:
            return None
        return ProfileMeta(name=name, identifier=identifier, organization=organization, description=description)

    def providers(self, value: Any) -> dict[str, dict[str, dict]]:
        providers: dict[str, dict[str, dict]] = {
            name: {kind: dict(settings) for kind, settings in preset.items()}
            for name, preset in BUILTIN_PROVIDERS.items()
        }
        if value is None:
            return providers
        if not isinstance(value, Mapping):
            self.error("providers", f"doit être un dictionnaire (nom: réglages), trouvé {_type_name(value)}")
            return providers
        for name, preset in value.items():
            path = f"providers.{name}"
            if not isinstance(name, str) or not name:
                self.error("providers", f"nom de fournisseur invalide : {name!r}")
                continue
            before = len(self.errors)
            pblock = self.mapping(preset, path, PROVIDER_KEYS)
            if pblock is None:
                self.broken_providers.add(name)
                continue
            merged = providers.get(name, {})
            for kind in ("imap", "smtp"):
                if kind in pblock:
                    settings = self.server_block(pblock[kind], f"{path}.{kind}", kind, account=False)
                    if settings is not None:
                        merged[kind] = {**merged.get(kind, {}), **settings}
            providers[name] = merged
            if len(self.errors) > before:
                self.broken_providers.add(name)
        return providers

    def accounts(self, value: Any, providers: dict, default_provider: str | None) -> list[Account]:
        if value is None:
            self.error("accounts", "section manquante : ajoutez au moins un compte")
            return []
        if not isinstance(value, list):
            self.error("accounts", f"doit être une liste (éléments précédés de « - »), trouvé {_type_name(value)}")
            return []
        if not value:
            self.error("accounts", "la liste est vide : ajoutez au moins un compte")
            return []
        accounts: list[Account] = []
        seen: dict[str, str] = {}
        for index, item in enumerate(value):
            path = f"accounts[{index}]"
            account = self.account(item, path, providers, default_provider)
            if account is None:
                continue
            key = account.email.lower()
            if key in seen:
                self.error(f"{path}.email", f"adresse {account.email} déjà utilisée par {seen[key]}")
                continue
            seen[key] = path
            accounts.append(account)
        return accounts

    def account(self, item: Any, path: str, providers: dict, default_provider: str | None) -> Account | None:
        block = self.mapping(item, path, ACCOUNT_KEYS)
        if block is None:
            return None
        start = len(self.errors)

        email = None
        if "email" not in block:
            self.error(f"{path}.email", "obligatoire")
        else:
            email = self.string(block["email"], f"{path}.email")
            if email is not None:
                email = email.strip()
                if not EMAIL_RE.match(email):
                    self.error(f"{path}.email", f"adresse email invalide : {email!r}")
                    email = None
        label = email or path

        name = None
        if "name" not in block:
            self.error(f"{path}.name", f"obligatoire (nom affiché comme expéditeur pour {label})")
        else:
            name = self.string(block["name"], f"{path}.name")

        description = None
        if block.get("description") is not None:
            description = self.string(block["description"], f"{path}.description")

        username = None
        if block.get("username") is not None:
            username = self.string(block["username"], f"{path}.username")
        password = None
        if "password" in block and block["password"] is not None:
            password = self.string(block["password"], f"{path}.password", secret=True)

        provider_name = None
        if block.get("provider") is not None:
            provider_name = self.string(block["provider"], f"{path}.provider")
        else:
            provider_name = default_provider
        preset: dict[str, dict] = {}
        provider_broken = provider_name in self.broken_providers
        if provider_name is not None and not provider_broken:
            if provider_name not in providers:
                where = f"{path}.provider" if block.get("provider") is not None else "default_provider"
                known = ", ".join(sorted(providers)) or "aucun"
                self.error(where, f"fournisseur inconnu {provider_name!r} ; fournisseurs définis : {known}")
            else:
                preset = providers[provider_name]

        servers: dict[str, ServerSettings | None] = {}
        for kind in ("imap", "smtp"):
            override: dict = {}
            if block.get(kind) is not None:
                override = self.server_block(block[kind], f"{path}.{kind}", kind, account=True) or {}
            merged = {**preset.get(kind, {}), **override}
            missing = [k for k in ("host", "port", "ssl") if k not in merged]
            if missing:
                if provider_name is None:
                    reason = "aucun fournisseur : ni provider sur le compte, ni default_provider"
                else:
                    reason = f"le fournisseur {provider_name!r} ne les définit pas"
                # On ne signale l'absence que si elle n'est pas la conséquence
                # d'une erreur déjà signalée (bloc ou fournisseur invalide).
                already = provider_broken or any(e.startswith(f"{path}.{kind}") for e in self.errors[start:])
                if not already:
                    self.error(
                        f"{path}.{kind}",
                        f"paramètres manquants : {', '.join(missing)} ({reason})",
                    )
                servers[kind] = None
                continue
            server_password = merged.get("password", password)
            if server_password is None:
                self.warn(
                    f"{path}.{kind}",
                    f"aucun mot de passe pour {label} : l'appareil le demandera à l'installation",
                )
            if not merged["ssl"]:
                self.warn(
                    f"{path}.{kind}",
                    f"SSL désactivé pour {label} ({merged['host']}:{merged['port']}) : "
                    "le mot de passe circulera en clair sur le réseau",
                )
            servers[kind] = ServerSettings(
                host=merged["host"],
                port=merged["port"],
                ssl=merged["ssl"],
                username=merged.get("username") or username or email or "",
                password=server_password,
                auth=merged.get("auth", AUTH_METHODS["password"]),
                path_prefix=merged.get("path_prefix") if kind == "imap" else None,
            )

        imap, smtp = servers["imap"], servers["smtp"]
        if len(self.errors) > start or email is None or name is None or imap is None or smtp is None:
            return None
        return Account(
            name=name,
            email=email,
            description=description or email,
            provider=provider_name,
            imap=imap,
            smtp=smtp,
        )


def validate_config(data: Any) -> Config:
    """Valide une configuration déjà chargée (dictionnaire Python)."""
    v = _Validator()
    top = v.mapping(data, "", TOP_LEVEL_KEYS)
    if top is None:
        raise ConfigError(["le fichier doit contenir un dictionnaire avec les sections profile, providers, accounts"])

    profile = v.profile(top.get("profile"))
    providers = v.providers(top.get("providers"))

    default_provider = None
    if top.get("default_provider") is not None:
        default_provider = v.string(top["default_provider"], "default_provider")
        if default_provider is not None and default_provider not in providers:
            v.error(
                "default_provider",
                f"fournisseur inconnu {default_provider!r} ; fournisseurs définis : {', '.join(sorted(providers))}",
            )
            v.broken_providers.add(default_provider)

    accounts = v.accounts(top.get("accounts"), providers, default_provider)

    if v.errors:
        raise ConfigError(v.errors)
    assert profile is not None
    return Config(profile=profile, accounts=tuple(accounts), warnings=tuple(v.warnings))


def _type_name(value: Any) -> str:
    if value is None:
        return "une valeur vide"
    if isinstance(value, bool):
        return "un booléen"
    if isinstance(value, int):
        return "un nombre"
    if isinstance(value, float):
        return "un nombre décimal"
    if isinstance(value, str):
        return "du texte"
    if isinstance(value, list):
        return "une liste"
    if isinstance(value, Mapping):
        return "un dictionnaire"
    return type(value).__name__
