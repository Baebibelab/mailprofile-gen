import io
import plistlib
import stat

import yaml

from mailprofile_gen.cli import EXIT_CONFIG, EXIT_OK, main


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def write_config(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_generates_profile_with_600_and_warning(tmp_path, base_config):
    cfg = write_config(tmp_path, base_config)
    output = tmp_path / "comptes.mobileconfig"
    code, out, err = run(["-c", str(cfg), "-o", str(output)])
    assert code == EXIT_OK, err
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    profile = plistlib.loads(output.read_bytes())
    assert len(profile["PayloadContent"]) == 2
    assert "2 comptes" in out
    assert "non signé" in out
    assert "EN CLAIR" in err
    assert "Supprimez" in err
    # Les mots de passe ne sont jamais affichés.
    assert "secret-1" not in out + err


def test_regeneration_is_deterministic(tmp_path, base_config):
    cfg = write_config(tmp_path, base_config)
    output = tmp_path / "comptes.mobileconfig"
    run(["-c", str(cfg), "-o", str(output)])
    first = output.read_bytes()
    run(["-c", str(cfg), "-o", str(output)])
    assert output.read_bytes() == first


def test_invalid_config_exit_code_and_messages(tmp_path, base_config):
    base_config["accounts"][0]["email"] = "pas-une-adresse"
    cfg = write_config(tmp_path, base_config)
    output = tmp_path / "comptes.mobileconfig"
    code, out, err = run(["-c", str(cfg), "-o", str(output)])
    assert code == EXIT_CONFIG
    assert "Configuration invalide" in err
    assert "accounts[0].email" in err
    assert not output.exists()


def test_missing_config_file(tmp_path):
    code, _, err = run(["-c", str(tmp_path / "absent.yaml")])
    assert code == EXIT_CONFIG
    assert "introuvable" in err


def test_check_mode_writes_nothing(tmp_path, base_config):
    cfg = write_config(tmp_path, base_config)
    output = tmp_path / "comptes.mobileconfig"
    code, out, _ = run(["-c", str(cfg), "-o", str(output), "--check"])
    assert code == EXIT_OK
    assert "Configuration valide" in out
    assert not output.exists()


def test_warns_when_config_is_world_readable(tmp_path, base_config):
    cfg = write_config(tmp_path, base_config)
    cfg.chmod(0o644)
    _, _, err = run(["-c", str(cfg), "--check"])
    assert "chmod 600" in err


def test_output_directory_must_exist(tmp_path, base_config):
    cfg = write_config(tmp_path, base_config)
    code, _, err = run(["-c", str(cfg), "-o", str(tmp_path / "nope" / "x.mobileconfig")])
    assert code == 1
    assert "n'existe pas" in err


def test_sign_key_requires_cert(tmp_path, base_config):
    cfg = write_config(tmp_path, base_config)
    code, _, err = run(["-c", str(cfg), "--sign-key", "k.pem"])
    assert code == EXIT_CONFIG
    assert "--sign-cert" in err
