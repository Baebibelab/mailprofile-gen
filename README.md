# mailprofile-gen

Génère un **profil de configuration Apple (`.mobileconfig`)** contenant
**plusieurs comptes mail IMAP**, à partir d'un seul fichier YAML.

Une fois le profil installé sur un iPhone, un iPad ou un Mac, **chaque adresse
apparaît comme un compte séparé** dans l'app Mail, avec sa propre boîte de
réception, ses propres dossiers et sa propre adresse d'expédition (et non un
compte unique avec des dossiers).

```text
config.yaml  ──►  mailprofile-gen  ──►  comptes.mobileconfig  ──►  iPhone / Mac
(N comptes)                            (1 payload mail par compte)
```

> ⚠️ **Le profil généré contient vos mots de passe en clair.** Supprimez-le dès
> qu'il est installé (voir [Sécurité](#sécurité)).

---

## Sommaire

- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Le fichier de configuration](#le-fichier-de-configuration)
- [Générer le profil](#générer-le-profil)
- [Installer le profil sur iPhone / iPad](#installer-le-profil-sur-iphone--ipad)
- [Installer le profil sur Mac](#installer-le-profil-sur-mac)
- [Ajouter, modifier ou supprimer un compte](#ajouter-modifier-ou-supprimer-un-compte)
- [Signer le profil (facultatif)](#signer-le-profil-facultatif)
- [Sécurité](#sécurité)
- [Dépannage](#dépannage)
- [Développement](#développement)

---

## Installation

Python 3.9 ou plus récent.

```bash
git clone https://github.com/baebibelab/mailprofile-gen.git
```

```bash
cd mailprofile-gen
```

```bash
python3 -m venv .venv && . .venv/bin/activate
```

```bash
pip install .
```

Pour pouvoir [signer le profil](#signer-le-profil-facultatif), installez la
dépendance facultative :

```bash
pip install '.[sign]'
```

La commande `mailprofile-gen` est alors disponible (également utilisable via
`python -m mailprofile_gen`).

## Démarrage rapide

```bash
cp config.example.yaml config.yaml
```

```bash
chmod 600 config.yaml
```

Éditez `config.yaml` (adresses, mots de passe), puis :

```bash
mailprofile-gen -c config.yaml -o comptes.mobileconfig
```

Envoyez `comptes.mobileconfig` sur l'iPhone par AirDrop, installez-le, puis
supprimez le fichier.

---

## Le fichier de configuration

`config.yaml` est ignoré par git (tout comme `config.*.yaml` et les fichiers
`.mobileconfig`). Le modèle commenté est
[`config.example.yaml`](config.example.yaml).

### Exemple complet

```yaml
profile:
  name: "Comptes mail"              # nom du profil affiché sur l'appareil
  organization: "Romain"            # facultatif
  identifier: "com.romain.mailprofile"   # obligatoire, ne plus le changer
  # description: "Mes comptes mail"      # facultatif

default_provider: ovh               # fournisseur des comptes sans « provider »

providers:
  ovh:                              # intégré : ce bloc est facultatif
    imap: { host: ssl0.ovh.net, port: 993, ssl: true }
    smtp: { host: ssl0.ovh.net, port: 465, ssl: true }
  autre:
    imap: { host: imap.exemple.net, port: 993, ssl: true }
    smtp: { host: smtp.exemple.net, port: 587, ssl: true }

accounts:
  - name: "Romain"                  # nom d'expéditeur
    email: contact@exemple.fr
    password: "mot-de-passe-1"
    description: "Contact"          # libellé du compte dans Mail

  - name: "Romain - Facturation"
    email: factures@exemple.fr
    password: "mot-de-passe-2"

  - name: "Romain"
    email: romain@autre-domaine.fr
    provider: autre
    username: "romain"              # si l'identifiant n'est pas l'adresse
    password: "mot-de-passe-3"
    smtp:
      port: 465                     # surcharge pour ce compte uniquement
```

### Section `profile`

| Clé            | Obligatoire | Description |
|----------------|-------------|-------------|
| `identifier`   | oui         | Identifiant de base en notation DNS inversée (ex. `com.romain.mailprofile`). Il sert de `PayloadIdentifier` au profil et à dériver les identifiants des comptes. **Gardez-le identique** d'une génération à l'autre : c'est ce qui permet à une réinstallation de *remplacer* le profil au lieu d'en ajouter un second. |
| `name`         | non         | Nom du profil affiché sur l'appareil (défaut : « Comptes mail »). |
| `organization` | non         | Organisation affichée sous le nom du profil. |
| `description`  | non         | Description du profil (défaut : la liste des adresses). |

### Section `providers` et `default_provider`

Un fournisseur regroupe les réglages serveur partagés par plusieurs comptes :

| Clé                | Description |
|--------------------|-------------|
| `imap.host`, `smtp.host` | Nom d'hôte, sans protocole ni port (ex. `ssl0.ovh.net`). |
| `imap.port`, `smtp.port` | Port (entier). |
| `imap.ssl`, `smtp.ssl`   | `true` pour une connexion chiffrée SSL/TLS. |
| `imap.auth`, `smtp.auth` | Facultatif : `password` (défaut), `crammd5`, `ntlm`, `httpmd5`, `none`. |
| `imap.path_prefix`       | Facultatif : préfixe des dossiers IMAP (ex. `INBOX`), rarement nécessaire. |

Le préréglage **`ovh`** est intégré à l'outil (pas besoin de le recopier). Il
correspond aux e-mails mutualisés OVHcloud (MX Plan), d'après la
[documentation OVHcloud](https://docs.ovhcloud.com/en/guides/web-cloud/email-and-collaborative-solutions/mx-plan/email-generalities) :

| Serveur | Hôte           | Port | Chiffrement |
|---------|----------------|------|-------------|
| IMAP    | `ssl0.ovh.net` | 993  | SSL/TLS     |
| SMTP    | `ssl0.ovh.net` | 465  | SSL/TLS     |

L'identifiant de connexion est l'adresse e-mail complète (comportement par
défaut de l'outil). Un bloc `providers.ovh` dans votre configuration complète
ou remplace ces valeurs (ex. `ovh: { smtp: { port: 587 } }`).

> Les offres OVHcloud *Email Pro* et *Exchange* utilisent d'autres serveurs :
> déclarez-les comme un fournisseur supplémentaire, avec les valeurs indiquées
> dans votre espace client OVHcloud.

`default_provider` désigne le fournisseur utilisé par les comptes qui n'ont
pas de clé `provider`. S'il est absent, chaque compte doit indiquer un
`provider` ou des blocs `imap`/`smtp` complets.

### Section `accounts`

Une liste d'un nombre quelconque de comptes. Chaque compte devient un compte
indépendant dans Mail.

| Clé           | Obligatoire | Description |
|---------------|-------------|-------------|
| `name`        | oui         | Nom affiché comme expéditeur (« De : Romain »). |
| `email`       | oui         | Adresse e-mail. Doit être unique dans le fichier (casse ignorée). |
| `password`    | non\*       | Mot de passe, utilisé pour IMAP et SMTP. |
| `username`    | non         | Identifiant de connexion (défaut : l'adresse). |
| `provider`    | non         | Fournisseur (défaut : `default_provider`). |
| `description` | non         | Libellé du compte dans Mail et dans Réglages (défaut : l'adresse). Pratique pour distinguer « Pro », « Perso », etc. |
| `imap`, `smtp`| non         | Surcharges pour ce compte : `host`, `port`, `ssl`, `auth`, `username`, `password` (et `path_prefix` pour IMAP). Seules les clés indiquées remplacent celles du fournisseur. Permet par exemple un mot de passe SMTP différent. |

\* Si `password` est omis, l'outil affiche un avertissement et l'iPhone ou le
Mac **demandera le mot de passe pendant l'installation** du profil. C'est une
option plus sûre si vous ne voulez pas de mot de passe dans le fichier.

> 💡 **Mettez toujours les mots de passe entre guillemets.** En YAML,
> `password: 0123` serait lu comme un nombre, `password: yes` comme un booléen.
> L'outil refuse ces cas avec un message explicite plutôt que de générer un
> mot de passe faux.

### Validation

La configuration est entièrement vérifiée avant toute génération ; toutes les
erreurs sont listées d'un coup, avec leur emplacement :

```text
Configuration invalide (config.yaml) :
  ✗ profile.identifer : clé inconnue (vouliez-vous dire « identifier » ?) ; clés autorisées : description, identifier, name, organization
  ✗ accounts[0].email : adresse email invalide : 'contact@'
  ✗ accounts[1].password : doit être une chaîne de caractères, trouvé un nombre <masqué> ; mettez la valeur entre guillemets dans le YAML (ex. "0123") pour qu'elle ne soit pas interprétée comme un nombre ou un booléen
  ✗ accounts[2].smtp.port : le port doit être compris entre 1 et 65535, trouvé 99999
```

(`accounts[0]` désigne le premier compte de la liste.) Les mots de passe ne
sont jamais affichés.

---

## Générer le profil

```bash
mailprofile-gen -c config.yaml -o comptes.mobileconfig
```

| Option              | Description |
|---------------------|-------------|
| `-c`, `--config`    | Fichier de configuration (défaut : `config.yaml`). |
| `-o`, `--output`    | Profil à générer (défaut : `comptes.mobileconfig`). Un fichier existant est remplacé. |
| `--check`           | Valide la configuration et affiche les comptes, sans rien écrire. |
| `-q`, `--quiet`     | N'affiche que les avertissements et erreurs. |
| `--sign-cert`, `--sign-key`, `--sign-chain` | Signature, voir [plus bas](#signer-le-profil-facultatif). |

Codes de sortie : `0` succès, `2` configuration invalide, `1` autre erreur.

Ce que fait l'outil :

- un payload `com.apple.mail.managed` par compte, mots de passe IMAP et SMTP
  inclus ;
- des **identifiants stables** : le `PayloadUUID` de chaque compte est un
  UUID v5 dérivé de l'adresse e-mail (et de `profile.identifier`), son
  `PayloadIdentifier` est lisible et lui aussi dérivé de l'adresse, par exemple
  `com.romain.mailprofile.mail.contact.at.exemple.fr`. Régénérer le profil
  donne donc les mêmes identifiants, quel que soit l'ordre des comptes ;
- le plist est produit avec `plistlib`, puis **validé** (clés obligatoires,
  types, unicité des UUID et identifiants, relecture) ; sur macOS, il est en
  plus contrôlé avec `plutil -lint` ;
- le fichier est écrit de façon atomique avec les **permissions 600**
  (lisible par vous seul) ;
- la sortie se termine par un avertissement rappelant que le fichier contient
  les mots de passe en clair.

---

## Installer le profil sur iPhone / iPad

### Par AirDrop (recommandé)

1. Sur le Mac, faites un clic droit sur `comptes.mobileconfig` →
   **Partager** → **AirDrop**, puis choisissez l'iPhone.
2. Sur l'iPhone, acceptez. Le message « Profil téléchargé » s'affiche.
3. Ouvrez **Réglages** : une ligne **Profil téléchargé** apparaît en haut
   (sinon : **Réglages → Général → VPN et gestion de l'appareil**).
4. Touchez le profil, puis **Installer** (en haut à droite), saisissez le code
   de l'iPhone et confirmez. Un profil non signé est indiqué « Non vérifié » :
   c'est normal pour un profil que vous avez généré vous-même.
5. Les comptes apparaissent dans **Mail** (un par adresse) et dans
   **Réglages → Apps → Mail → Comptes**.

> Un profil téléchargé non installé est supprimé automatiquement au bout de
> quelques minutes : installez-le aussitôt après le transfert.

### Par fichier (app Fichiers)

Si vous n'avez pas de Mac : copiez le fichier dans l'app **Fichiers** de
l'iPhone (clé USB / carte SD branchée sur l'iPhone, partage de fichiers via le
Finder ou iTunes, ou iCloud Drive), puis touchez-le dans **Fichiers** : le
message « Profil téléchargé » s'affiche. Continuez à l'étape 3 ci-dessus.

Évitez de l'envoyer par e-mail ou par une messagerie : le fichier (et donc les
mots de passe) resterait stocké sur des serveurs tiers. Si vous passez par
iCloud Drive, supprimez-le ensuite, y compris de « Supprimés récemment ».

**Après l'installation, supprimez le fichier** de l'app Fichiers (et de
« Supprimés récemment »).

---

## Installer le profil sur Mac

1. Double-cliquez sur `comptes.mobileconfig` (ou `open comptes.mobileconfig`
   dans le Terminal). macOS indique que le profil a été téléchargé et doit être
   vérifié dans Réglages Système.
2. Ouvrez **Réglages Système** puis, selon la version de macOS :
   - **Général → Gestion des appareils** (versions récentes) ;
   - **Confidentialité et sécurité → Profils** (macOS 13/14) ;
   - **Préférences Système → Profils** (macOS 12 et antérieur).
3. Double-cliquez sur le profil dans la liste, cliquez sur **Installer…** et
   confirmez avec votre mot de passe de session.
4. Les comptes apparaissent dans **Mail** et dans
   **Réglages Système → Comptes Internet**.

Supprimez ensuite `comptes.mobileconfig` (et videz la corbeille).

---

## Ajouter, modifier ou supprimer un compte

Les comptes installés par un profil ne se modifient pas à la main sur
l'appareil : on modifie la configuration et on **réinstalle le profil**.

1. Modifiez `config.yaml` : ajoutez une entrée dans `accounts`, retirez-en une,
   changez un mot de passe…
2. Régénérez :

   ```bash
   mailprofile-gen -c config.yaml -o comptes.mobileconfig
   ```

3. Installez le nouveau fichier exactement comme la première fois.

Comme `profile.identifier` est inchangé, l'appareil reconnaît le même profil
et **le remplace** au lieu d'en ajouter un second : les nouveaux comptes sont
ajoutés, les comptes retirés du fichier disparaissent de l'appareil, les autres
sont mis à jour. Les identifiants de chaque compte étant dérivés de son adresse,
ajouter ou retirer un compte ne change pas ceux des autres.

À savoir :

- **Ne changez pas `profile.identifier`**, sinon l'appareil verra un nouveau
  profil et vous aurez les comptes en double (supprimez alors l'ancien profil).
- Changer l'**adresse** d'un compte revient à supprimer l'ancien compte et à en
  créer un nouveau.
- Si l'appareil refuse le remplacement ou affiche des comptes en double,
  supprimez d'abord le profil existant (voir ci-dessous) puis installez le
  nouveau.
- Si le profil installé était **signé**, signez la nouvelle version avec le
  **même certificat** : un profil signé ne peut généralement être remplacé que
  par un profil de la même identité.
- Les e-mails étant stockés sur le serveur (IMAP), supprimer ou réinstaller un
  compte ne supprime aucun message : ils sont simplement retéléchargés.

### Supprimer tous les comptes

- **iPhone** : **Réglages → Général → VPN et gestion de l'appareil** → le
  profil → **Supprimer le profil**.
- **Mac** : dans la section Profils / Gestion des appareils de Réglages
  Système, sélectionnez le profil et cliquez sur **−**.

Tous les comptes du profil sont retirés de l'appareil (les e-mails restent sur
le serveur).

---

## Signer le profil (facultatif)

Un profil signé est affiché « Vérifié » (si le certificat est reconnu par
l'appareil) au lieu de « Non vérifié », et son contenu ne peut pas être
modifié sans invalider la signature. La signature **ne chiffre pas** le
profil : les mots de passe restent lisibles par qui obtient le fichier.

Nécessite `pip install '.[sign]'`.

```bash
# Avec un fichier .p12 / .pfx (ex. exporté depuis le Trousseau d'accès)
mailprofile-gen -c config.yaml -o comptes.mobileconfig --sign-cert identite.p12
```

```bash
# Avec un certificat et une clé PEM, plus un certificat intermédiaire
mailprofile-gen -c config.yaml -o comptes.mobileconfig \
  --sign-cert cert.pem --sign-key cle.pem --sign-chain intermediaire.pem
```

- Le mot de passe de la clé ou du `.p12` est lu dans la variable
  d'environnement `MAILPROFILE_SIGN_PASSWORD`, sinon demandé au clavier.
- `--sign-key` est inutile si la clé est dans le même fichier PEM que le
  certificat. `--sign-chain` peut être répété.
- Clés RSA ou ECDSA ; signature CMS (PKCS#7) attachée, SHA-256, au format DER,
  comme `security cms -S` ou `openssl smime -sign -nodetach -binary`.

---

## Sécurité

- `config.yaml` contient vos mots de passe : il est dans le `.gitignore`,
  gardez-le en `chmod 600` (l'outil vous avertit s'il est lisible par
  d'autres utilisateurs). Ne versionnez que `config.example.yaml`.
- Le `.mobileconfig` généré contient les mots de passe **en clair** (un
  `.mobileconfig` est un simple fichier XML, signé ou non). Il est créé avec
  les permissions 600 et ignoré par git, mais **supprimez-le dès l'installation
  terminée**, sur l'ordinateur comme sur l'iPhone / le Mac.
- Transférez-le par AirDrop ou par un support local plutôt que par e-mail ou
  messagerie.
- Pour ne mettre aucun mot de passe dans le fichier, omettez `password` :
  l'appareil le demandera à l'installation.
- Les certificats et clés (`*.p12`, `*.pfx`, `*.pem`, `*.key`) sont aussi
  ignorés par git.

---

## Dépannage

| Problème | Piste |
|----------|-------|
| « Impossible de se connecter » / mot de passe redemandé | Vérifiez l'identifiant (adresse complète chez OVH) et le mot de passe, en testant par exemple sur le webmail. Régénérez puis réinstallez. |
| Comptes en double | `profile.identifier` a changé entre deux installations : supprimez l'ancien profil. |
| « Profil non vérifié » | Normal pour un profil non signé. Voir [Signer le profil](#signer-le-profil-facultatif). |
| Le profil n'apparaît pas dans Réglages | Il expire quelques minutes après le téléchargement : renvoyez-le et installez-le aussitôt. |
| Erreur YAML | Le message indique la ligne et la colonne. Attention à l'indentation (espaces, pas de tabulations) et aux guillemets. |

---

## Développement

```bash
pip install -e '.[dev]'
```

```bash
pytest
```

Organisation du code :

```text
src/mailprofile_gen/
├── cli.py        # interface en ligne de commande
├── config.py     # lecture et validation du YAML
├── providers.py  # préréglages intégrés (ovh)
├── profile.py    # construction, validation et écriture du plist
└── signing.py    # signature CMS facultative
tests/            # tests unitaires (pytest)
```

Hors périmètre pour l'instant : calendriers, contacts, service permanent,
lecture des mails.
