"""Interface en ligne de commande : mailprofile-gen."""

from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys
from pathlib import Path
from typing import Sequence, TextIO

from . import __version__
from .config import Config, ConfigError, load_config
from .profile import ProfileError, build_profile, lint_with_plutil, validate_profile, write_private_file

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2

PASSWORD_ENV = "MAILPROFILE_SIGN_PASSWORD"

WARNING_BANNER = """\
⚠️  ATTENTION : ce profil contient les mots de passe EN CLAIR.
    - Ne le partagez pas, ne l'envoyez pas par e-mail, ne le versionnez pas.
    - Supprimez {path} dès que le profil est installé
      (y compris des Téléchargements / Fichiers de l'iPhone et de la corbeille).
    - Supprimez aussi le fichier transféré sur l'appareil après installation."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mailprofile-gen",
        description=(
            "Génère un profil Apple .mobileconfig contenant plusieurs comptes mail IMAP "
            "(un compte séparé par adresse dans l'app Mail) à partir d'un fichier YAML."
        ),
    )
    parser.add_argument(
        "-c", "--config", default="config.yaml", metavar="FICHIER",
        help="fichier de configuration YAML (défaut : %(default)s)",
    )
    parser.add_argument(
        "-o", "--output", default="comptes.mobileconfig", metavar="FICHIER",
        help="profil à générer (défaut : %(default)s)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="valider la configuration sans générer de fichier",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="n'afficher que les avertissements et les erreurs",
    )
    sign = parser.add_argument_group(
        "signature (facultative)",
        f"Le mot de passe de la clé ou du .p12 est lu dans ${PASSWORD_ENV}, sinon demandé au clavier.",
    )
    sign.add_argument(
        "--sign-cert", metavar="FICHIER",
        help="certificat de signature : .p12/.pfx, ou certificat PEM/DER (éventuellement avec la clé)",
    )
    sign.add_argument("--sign-key", metavar="FICHIER", help="clé privée PEM/DER (si absente du certificat)")
    sign.add_argument(
        "--sign-chain", metavar="FICHIER", action="append", default=[],
        help="certificat(s) intermédiaire(s) à inclure (option répétable)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _password_callback(prompt: str) -> bytes | None:
    env = os.environ.get(PASSWORD_ENV)
    if env:
        return env.encode("utf-8")
    if sys.stdin.isatty():
        return getpass.getpass(prompt).encode("utf-8") or None
    return None


def _check_config_permissions(path: Path, err: TextIO) -> None:
    if os.name != "posix":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(
            f"⚠️  {path} est lisible par d'autres utilisateurs (permissions {stat.S_IMODE(mode):o}) "
            f"alors qu'il contient des mots de passe : chmod 600 {path}",
            file=err,
        )


def _describe(config: Config) -> list[str]:
    lines = []
    for a in config.accounts:
        via = f" via {a.provider}" if a.provider else ""
        imap = f"{a.imap.host}:{a.imap.port}{' SSL' if a.imap.ssl else ''}"
        smtp = f"{a.smtp.host}:{a.smtp.port}{' SSL' if a.smtp.ssl else ''}"
        lines.append(f"  - {a.description} — {a.name} <{a.email}>{via} (IMAP {imap}, SMTP {smtp})")
    return lines


def main(argv: Sequence[str] | None = None, out: TextIO | None = None, err: TextIO | None = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)

    if (args.sign_key or args.sign_chain) and not args.sign_cert:
        print("erreur : --sign-key et --sign-chain nécessitent --sign-cert", file=err)
        return EXIT_CONFIG

    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration invalide ({config_path}) :", file=err)
        for message in exc.errors:
            print(f"  ✗ {message}", file=err)
        return EXIT_CONFIG

    _check_config_permissions(config_path, err)
    for warning in config.warnings:
        print(f"⚠️  {warning}", file=err)

    try:
        profile = build_profile(config)
        data = validate_profile(profile)
    except ProfileError as exc:
        print(f"erreur : profil généré invalide :\n{exc}", file=err)
        return EXIT_FAILURE
    lint_error = lint_with_plutil(data)
    if lint_error:
        print(f"erreur : plutil -lint a rejeté le profil :\n{lint_error}", file=err)
        return EXIT_FAILURE

    n = len(config.accounts)
    if args.check:
        if not args.quiet:
            print(f"Configuration valide : {n} compte{'s' if n > 1 else ''}.", file=out)
            print("\n".join(_describe(config)), file=out)
        return EXIT_OK

    signed = False
    if args.sign_cert:
        from .signing import SigningError, sign_profile

        try:
            data = sign_profile(
                data,
                args.sign_cert,
                key_path=args.sign_key,
                chain_paths=args.sign_chain,
                password_cb=_password_callback,
            )
        except SigningError as exc:
            print(f"erreur de signature : {exc}", file=err)
            return EXIT_FAILURE
        signed = True

    output = Path(args.output)
    if output.resolve() == config_path.resolve():
        print("erreur : le fichier de sortie ne peut pas être le fichier de configuration", file=err)
        return EXIT_FAILURE
    if not output.parent.is_dir():
        print(f"erreur : le dossier {output.parent} n'existe pas", file=err)
        return EXIT_FAILURE
    try:
        write_private_file(output, data)
    except OSError as exc:
        print(f"erreur : impossible d'écrire {output} : {exc.strerror or exc}", file=err)
        return EXIT_FAILURE

    if not args.quiet:
        print(
            f"Profil « {config.profile.name} » généré : {output} "
            f"({n} compte{'s' if n > 1 else ''}, {'signé' if signed else 'non signé'}, permissions 600)",
            file=out,
        )
        print("\n".join(_describe(config)), file=out)
    print(WARNING_BANNER.format(path=output), file=err)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
