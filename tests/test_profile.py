import plistlib
import stat
import uuid

import pytest

from mailprofile_gen.config import validate_config
from mailprofile_gen.profile import (
    ProfileError,
    account_identifier,
    account_uuid,
    build_profile,
    validate_profile,
    write_private_file,
)


def test_one_mail_payload_per_account(base_config):
    profile = build_profile(validate_config(base_config))
    assert profile["PayloadType"] == "Configuration"
    assert profile["PayloadIdentifier"] == "com.romain.mailprofile"
    assert profile["PayloadOrganization"] == "Romain"
    assert profile["PayloadDisplayName"] == "Comptes mail"
    content = profile["PayloadContent"]
    assert [p["PayloadType"] for p in content] == ["com.apple.mail.managed"] * 2
    assert [p["EmailAddress"] for p in content] == ["contact@exemple.fr", "factures@exemple.fr"]


def test_mail_payload_contents(base_config):
    p = build_profile(validate_config(base_config))["PayloadContent"][0]
    assert p["EmailAccountType"] == "EmailTypeIMAP"
    assert p["EmailAccountName"] == "Romain"
    assert p["EmailAccountDescription"] == "contact@exemple.fr"
    assert p["IncomingMailServerHostName"] == "ssl0.ovh.net"
    assert p["IncomingMailServerPortNumber"] == 993
    assert p["IncomingMailServerUseSSL"] is True
    assert p["IncomingMailServerUsername"] == "contact@exemple.fr"
    assert p["IncomingPassword"] == "secret-1"
    assert p["IncomingMailServerAuthentication"] == "EmailAuthPassword"
    assert p["OutgoingMailServerHostName"] == "ssl0.ovh.net"
    assert p["OutgoingMailServerPortNumber"] == 465
    assert p["OutgoingMailServerUseSSL"] is True
    assert p["OutgoingPassword"] == "secret-1"
    assert p["OutgoingPasswordSameAsIncomingPassword"] is True
    assert "IncomingMailServerIMAPPathPrefix" not in p


def test_distinct_smtp_password_and_missing_password(base_config):
    base_config["accounts"][0]["smtp"] = {"password": "autre"}
    del base_config["accounts"][1]["password"]
    content = build_profile(validate_config(base_config))["PayloadContent"]
    assert content[0]["OutgoingPassword"] == "autre"
    assert content[0]["OutgoingPasswordSameAsIncomingPassword"] is False
    assert "IncomingPassword" not in content[1]
    assert "OutgoingPassword" not in content[1]


def test_uuids_are_stable_and_derived_from_address(base_config):
    first = build_profile(validate_config(base_config))
    # Ordre des comptes, mots de passe, nom affiché modifiés : les identifiants ne bougent pas.
    base_config["accounts"].reverse()
    base_config["accounts"][0]["password"] = "nouveau"
    base_config["accounts"][0]["name"] = "Autre nom"
    base_config["accounts"].append({"name": "X", "email": "nouveau@exemple.fr", "password": "x"})
    second = build_profile(validate_config(base_config))

    assert first["PayloadUUID"] == second["PayloadUUID"]
    ids1 = {p["EmailAddress"]: (p["PayloadUUID"], p["PayloadIdentifier"]) for p in first["PayloadContent"]}
    ids2 = {p["EmailAddress"]: (p["PayloadUUID"], p["PayloadIdentifier"]) for p in second["PayloadContent"]}
    for email, ids in ids1.items():
        assert ids2[email] == ids

    meta = validate_config(base_config).profile
    expected = uuid.uuid5(uuid.uuid5(uuid.NAMESPACE_DNS, "com.romain.mailprofile"), "mail:contact@exemple.fr")
    assert account_uuid(meta, "contact@exemple.fr") == str(expected).upper()
    assert account_uuid(meta, "Contact@Exemple.FR") == account_uuid(meta, "contact@exemple.fr")
    assert account_identifier(meta, "contact@exemple.fr") == "com.romain.mailprofile.mail.contact.at.exemple.fr"
    assert account_identifier(meta, "a+b_c@x.fr") == "com.romain.mailprofile.mail.a-b-c.at.x.fr"


def test_uuids_depend_on_profile_identifier(base_config):
    first = build_profile(validate_config(base_config))
    base_config["profile"]["identifier"] = "com.autre.profil"
    second = build_profile(validate_config(base_config))
    assert first["PayloadUUID"] != second["PayloadUUID"]
    assert first["PayloadContent"][0]["PayloadUUID"] != second["PayloadContent"][0]["PayloadUUID"]


def test_validate_profile_roundtrip(base_config):
    profile = build_profile(validate_config(base_config))
    data = validate_profile(profile)
    assert data.startswith(b"<?xml")
    assert plistlib.loads(data) == profile


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda p: p.pop("PayloadUUID"), "PayloadUUID"),
        (lambda p: p.update(PayloadType="Autre"), "Configuration"),
        (lambda p: p["PayloadContent"][0].pop("IncomingMailServerHostName"), "IncomingMailServerHostName"),
        (lambda p: p["PayloadContent"][0].update(IncomingMailServerPortNumber="993"), "int"),
        (lambda p: p["PayloadContent"][0].update(IncomingMailServerPortNumber=True), "int"),
        (lambda p: p["PayloadContent"][0].update(IncomingMailServerUseSSL=1), "bool"),
        (lambda p: p["PayloadContent"][1].update(PayloadUUID=p["PayloadContent"][0]["PayloadUUID"]), "double"),
        (
            lambda p: p["PayloadContent"][1].update(PayloadIdentifier=p["PayloadContent"][0]["PayloadIdentifier"]),
            "double",
        ),
        (lambda p: p["PayloadContent"][0].update(PayloadUUID="pas-un-uuid"), "invalide"),
        (lambda p: p.update(PayloadContent=[]), "vide"),
    ],
)
def test_validate_profile_detects_problems(base_config, mutate, expected):
    profile = build_profile(validate_config(base_config))
    mutate(profile)
    with pytest.raises(ProfileError, match=expected):
        validate_profile(profile)


def test_write_private_file_permissions(tmp_path):
    target = tmp_path / "comptes.mobileconfig"
    target.write_bytes(b"ancien")
    target.chmod(0o644)
    write_private_file(target, b"nouveau")
    assert target.read_bytes() == b"nouveau"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["comptes.mobileconfig"]
