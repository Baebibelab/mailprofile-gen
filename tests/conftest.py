import copy

import pytest

BASE_CONFIG = {
    "profile": {
        "name": "Comptes mail",
        "organization": "Romain",
        "identifier": "com.romain.mailprofile",
    },
    "default_provider": "ovh",
    "accounts": [
        {"name": "Romain", "email": "contact@exemple.fr", "password": "secret-1"},
        {"name": "Romain Facturation", "email": "factures@exemple.fr", "password": "secret-2"},
    ],
}


@pytest.fixture
def base_config():
    return copy.deepcopy(BASE_CONFIG)
