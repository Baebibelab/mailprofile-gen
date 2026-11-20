import pytest

from mailprofile_gen.config import ConfigError, load_config, parse_config, validate_config


def errors_of(data):
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    return exc.value.errors


def test_minimal_config_uses_builtin_ovh(base_config):
    config = validate_config(base_config)
    assert len(config.accounts) == 2
    a = config.accounts[0]
    assert a.provider == "ovh"
    assert (a.imap.host, a.imap.port, a.imap.ssl) == ("ssl0.ovh.net", 993, True)
    assert (a.smtp.host, a.smtp.port, a.smtp.ssl) == ("ssl0.ovh.net", 465, True)
    assert a.imap.username == a.smtp.username == "contact@exemple.fr"
    assert a.imap.password == a.smtp.password == "secret-1"
    assert a.imap.auth == "EmailAuthPassword"
    assert a.description == "contact@exemple.fr"
    assert config.warnings == ()


def test_username_description_and_overrides(base_config):
    base_config["accounts"][0].update(
        {
            "username": "login-contact",
            "description": "Contact",
            "imap": {"host": "imap.autre.fr", "path_prefix": "INBOX"},
            "smtp": {"port": 587, "password": "smtp-secret", "username": "smtp-login", "auth": "CRAMMD5"},
        }
    )
    a = validate_config(base_config).accounts[0]
    assert a.description == "Contact"
    assert (a.imap.host, a.imap.port, a.imap.username, a.imap.password) == (
        "imap.autre.fr", 993, "login-contact", "secret-1",
    )
    assert a.imap.path_prefix == "INBOX"
    assert (a.smtp.host, a.smtp.port, a.smtp.username, a.smtp.password) == (
        "ssl0.ovh.net", 587, "smtp-login", "smtp-secret",
    )
    assert a.smtp.auth == "EmailAuthCRAMMD5"


def test_custom_provider_and_per_account_provider(base_config):
    base_config["providers"] = {
        "autre": {
            "imap": {"host": "imap.autre.net", "port": 993, "ssl": True},
            "smtp": {"host": "smtp.autre.net", "port": 587, "ssl": True},
        }
    }
    base_config["accounts"][1]["provider"] = "autre"
    config = validate_config(base_config)
    assert config.accounts[0].imap.host == "ssl0.ovh.net"
    assert config.accounts[1].provider == "autre"
    assert config.accounts[1].smtp.host == "smtp.autre.net"


def test_provider_section_can_partially_override_builtin(base_config):
    base_config["providers"] = {"ovh": {"smtp": {"port": 587}}}
    a = validate_config(base_config).accounts[0]
    assert (a.smtp.host, a.smtp.port) == ("ssl0.ovh.net", 587)


def test_no_default_provider_requires_full_servers(base_config):
    del base_config["default_provider"]
    errors = errors_of(base_config)
    assert any("accounts[0].imap" in e and "aucun fournisseur" in e for e in errors)

    for account in base_config["accounts"]:
        account["imap"] = {"host": "imap.x.fr", "port": 993, "ssl": True}
        account["smtp"] = {"host": "smtp.x.fr", "port": 465, "ssl": True}
    config = validate_config(base_config)
    assert config.accounts[0].provider is None


def test_variable_number_of_accounts(base_config):
    base_config["accounts"] = [
        {"name": f"N{i}", "email": f"user{i}@exemple.fr", "password": "x"} for i in range(12)
    ]
    assert len(validate_config(base_config).accounts) == 12


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda c: c.pop("profile"), "profile : section manquante"),
        (lambda c: c["profile"].pop("identifier"), "profile.identifier : obligatoire"),
        (lambda c: c["profile"].update(identifier="pas un id"), "identifiant invalide"),
        (lambda c: c.update(accounts=[]), "accounts : la liste est vide"),
        (lambda c: c.update(accounts={"a": 1}), "accounts : doit être une liste"),
        (lambda c: c.pop("accounts"), "accounts : section manquante"),
        (lambda c: c["accounts"][0].pop("email"), "accounts[0].email : obligatoire"),
        (lambda c: c["accounts"][0].pop("name"), "accounts[0].name : obligatoire"),
        (lambda c: c["accounts"][0].update(email="foo"), "adresse email invalide"),
        (lambda c: c["accounts"][1].update(email="CONTACT@exemple.fr"), "déjà utilisée par accounts[0]"),
        (lambda c: c["accounts"][0].update(provider="gmail"), "fournisseur inconnu 'gmail'"),
        (lambda c: c.update(default_provider="gmail"), "default_provider : fournisseur inconnu"),
        (lambda c: c["accounts"][0].update(imap={"port": 0}), "entre 1 et 65535"),
        (lambda c: c["accounts"][0].update(imap={"port": "993"}), "doit être un entier"),
        (lambda c: c["accounts"][0].update(imap={"port": True}), "doit être un entier"),
        (lambda c: c["accounts"][0].update(imap={"ssl": "yes"}), "true ou false"),
        (lambda c: c["accounts"][0].update(imap={"host": "imaps://x.fr"}), "nom d'hôte invalide"),
        (lambda c: c["accounts"][0].update(smtp={"auth": "oauth"}), "méthode inconnue"),
        (lambda c: c["accounts"][0].update(smtp={"path_prefix": "INBOX"}), "accounts[0].smtp.path_prefix : clé inconnue"),
        (lambda c: c["accounts"][0].update(pasword="x"), "vouliez-vous dire « password »"),
        (lambda c: c.update(acounts=[]), "vouliez-vous dire « accounts »"),
        (lambda c: c.update(providers=["ovh"]), "providers : doit être un dictionnaire"),
    ],
)
def test_validation_errors(base_config, mutate, expected):
    mutate(base_config)
    errors = errors_of(base_config)
    assert any(expected in e for e in errors), errors


def test_numeric_password_is_rejected_without_leaking_it(base_config):
    base_config["accounts"][0]["password"] = 123456
    errors = errors_of(base_config)
    assert any("accounts[0].password" in e and "guillemets" in e for e in errors)
    assert not any("123456" in e for e in errors)


def test_all_errors_are_reported_at_once(base_config):
    base_config["accounts"][0]["email"] = "foo"
    base_config["accounts"][1]["imap"] = {"port": 70000}
    base_config["profile"]["identifier"] = "x"
    errors = errors_of(base_config)
    assert len(errors) == 3


def test_broken_provider_does_not_cascade(base_config):
    base_config["providers"] = {"perso": {"imap": {"port": "abc"}}}
    base_config["default_provider"] = "perso"
    errors = errors_of(base_config)
    assert errors == ["providers.perso.imap.port : le port doit être un entier, trouvé du texte 'abc'"]


def test_warnings_for_missing_password_and_plaintext(base_config):
    del base_config["accounts"][0]["password"]
    base_config["accounts"][1]["imap"] = {"ssl": False, "port": 143}
    config = validate_config(base_config)
    assert config.accounts[0].imap.password is None
    assert any("demandera" in w for w in config.warnings)
    assert any("SSL désactivé" in w for w in config.warnings)


def test_yaml_errors_are_readable():
    with pytest.raises(ConfigError) as exc:
        parse_config("profile: [unclosed\n", source="c.yaml")
    assert "YAML invalide" in exc.value.errors[0]
    assert "ligne" in exc.value.errors[0]

    with pytest.raises(ConfigError) as exc:
        parse_config("", source="c.yaml")
    assert "vide" in exc.value.errors[0]


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "absent.yaml")
    assert "introuvable" in exc.value.errors[0]


def test_example_config_is_valid():
    from pathlib import Path

    config = load_config(Path(__file__).resolve().parent.parent / "config.example.yaml")
    assert len(config.accounts) == 3
    assert config.profile.identifier == "com.exemple.mailprofile"
