# QRadar Reference Set CLI

CLI for managing IP reference sets through the non-deprecated
`/api/reference_data_collections/*` REST endpoints.

## Requirements

- Python 3.10+
- QRadar REST API 16.0+
- Authorized Service token
- QRadar CA certificate (`tls.pem`) or another trusted CA bundle

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.ini.example config.ini
```

Edit `config.ini`, or inject the token from Jenkins:

```bash
export QRADAR_TOKEN='...'
```

## Commands

```bash
python3 cli.py refsets --ip-only
python3 cli.py refsets --ip-only --output plain
python3 cli.py list --refset Blocked_IPs
python3 cli.py add --refset Blocked_IPs --ip 192.0.2.10
python3 cli.py remove --refset Blocked_IPs --ip 192.0.2.10
python3 cli.py contains --refset Blocked_IPs --ip 192.0.2.10
python3 cli.py import --refset Blocked_IPs --file ips.txt
```

You can use a numeric ID instead of the name:

```bash
python3 cli.py list --refset-id 123
```

## Jenkins-friendly output

Reference-set dropdown:

```bash
python3 cli.py refsets --ip-only --output plain
```

JSON for pipelines:

```bash
python3 cli.py add --refset Blocked_IPs --ip 192.0.2.10 --output json
```

Exit codes:

- `0` success / `contains=true`
- `1` not found for `contains` or `remove`
- `2` configuration/API/input error
- `130` interrupted


## Kodowanie nazw z Jenkins

Jenkins przekazuje surową nazwę reference setu, np. `Blocked IPs / Warszawa #1`.
Nie wykonuj URL-encodingu po stronie Groovy/Jenkins. Python koduje query string dokładnie raz przed wysłaniem do QRadar, dzięki czemu unika podwójnego kodowania `%20 -> %2520`.


## Jenkins Active Choices

Do pobierania samych nazw reference setów:

```bash
python3 cli.py jenkins-refsets
```

Tylko reference sety typu IP:

```bash
python3 cli.py jenkins-refsets --ip-only
```

Przykładowy wynik:

```text
Allowed IPs
Blocked IPs / Warszawa
IOC_IPs
VPN Whitelist
```

Każda nazwa jest zwracana w osobnej linii, bez JSON i bez dodatkowego tekstu.

Przykład dla Active Choices Plugin:

```groovy
def command = [
    "python3",
    "/opt/qradar-refset/cli.py",
    "--config",
    "/opt/qradar-refset/config.ini",
    "jenkins-refsets",
    "--ip-only"
]

def process = command.execute()
process.waitFor()

if (process.exitValue() != 0) {
    def errorText = process.err.text.trim()
    return ["ERROR: " + (errorText ?: "QRadar CLI failed")]
}

def values = process.in.text
    .readLines()
    .collect { it.trim() }
    .findAll { it }

return values ?: ["ERROR: No reference sets returned"]
```

Jenkins przekazuje i wyświetla surowe nazwy. URL encoding wykonuje Python dopiero przy wysyłaniu requestu do QRadar.


## Logging

Domyślny poziom:

```bash
python3 cli.py --log-level INFO refsets --ip-only
```

Pełne informacje HTTP i diagnostyka:

```bash
python3 cli.py --log-level DEBUG \
  --log-file ./qradar-cli.log \
  add \
  --refset "Blocked IPs / Warszawa" \
  --ip "10.0.0.1,10.0.0.2"
```

Logi zawierają m.in.:
- start i koniec komendy,
- nazwę reference setu,
- rozwiązanie name -> collection ID,
- kolejne operacje na IP,
- statusy odpowiedzi HTTP,
- błędy per IP.

Token SEC nie jest logowany.

## Wiele adresów IP z Jenkins

Parametr `--ip` przyjmuje teraz jeden lub wiele adresów.

Pojedynczy:

```bash
python3 cli.py add \
  --refset "$REFSET" \
  --ip "10.0.0.1"
```

Rozdzielone przecinkami:

```bash
python3 cli.py add \
  --refset "$REFSET" \
  --ip "10.0.0.1,10.0.0.2,192.168.1.10"
```

W osobnych liniach:

```bash
python3 cli.py add \
  --refset "$REFSET" \
  --ip "$IPS"
```

gdzie `IPS` może mieć wartość:

```text
10.0.0.1
10.0.0.2
192.168.1.10
```

Można także mieszać przecinki i nowe linie:

```text
10.0.0.1,10.0.0.2
192.168.1.10
172.16.1.5,172.16.1.6
```

Parser:
1. dzieli dane po przecinku, CR i LF,
2. usuwa puste elementy i spacje,
3. waliduje każdy IPv4/IPv6,
4. normalizuje adresy przez `ipaddress.ip_address`,
5. usuwa duplikaty, zachowując kolejność,
6. odrzuca całą komendę przed kontaktem z QRadar, jeśli którykolwiek token nie jest poprawnym IP.

## Jenkins example

Przykład parametru tekstowego `IPS`:

```groovy
sh """
python3 /opt/qradar-refset/cli.py \
  --config /opt/qradar-refset/config.ini \
  --log-level INFO \
  --log-file "${WORKSPACE}/qradar-cli.log" \
  add \
  --refset "${REFSET}" \
  --ip "${IPS}"
"""
```

Dla bardziej bezpiecznego przekazania wieloliniowego inputu zalecane jest użycie zmiennej środowiskowej lub pliku tymczasowego zamiast ręcznego składania shell stringa.
