import copy

import pytest

BASE_CONFIG = {
    "profile": {
        "name": "Comptes mail",
        "organization": "Exemple",
        "identifier": "com.exemple.mailprofile",
    },
    "default_provider": "ovh",
    "accounts": [
        {"name": "Camille Martin", "email": "contact@exemple.fr", "password": "secret-1"},
        {"name": "Facturation", "email": "factures@exemple.fr", "password": "secret-2"},
    ],
}


@pytest.fixture
def base_config():
    return copy.deepcopy(BASE_CONFIG)
