"""Préréglages de fournisseurs intégrés.

Ils sont toujours disponibles, même s'ils ne figurent pas dans la section
``providers`` du fichier de configuration. Une entrée de même nom dans le
fichier de configuration les complète ou les surcharge.
"""

from __future__ import annotations

BUILTIN_PROVIDERS: dict[str, dict[str, dict]] = {
    # OVHcloud MX Plan (e-mails mutualisés, inclus avec les hébergements web).
    # Doc : https://docs.ovhcloud.com/en/guides/web-cloud/email-and-collaborative-solutions/mx-plan/email-generalities
    # IMAP 993 SSL/TLS, SMTP 465 SSL/TLS ; identifiant = adresse complète.
    "ovh": {
        "imap": {"host": "ssl0.ovh.net", "port": 993, "ssl": True},
        "smtp": {"host": "ssl0.ovh.net", "port": 465, "ssl": True},
    },
}
