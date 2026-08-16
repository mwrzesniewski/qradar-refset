# QRadar Reference Set CLI v4

Najważniejsze poprawki:
- naprawiony logger (`self.logger` zawsze istnieje),
- CLI faktycznie tworzy i przekazuje logger do QRadarClient,
- Active Choices: `jenkins-refsets`,
- nazwa reference setu jest przekazywana jako zwykły tekst,
- URL query jest kodowane po stronie Python,
- jeden lub wiele IP przez przecinki i/lub nowe linie,
- wszystkie IP są walidowane przed rozpoczęciem operacji,
- duplikaty są usuwane przed operacją.

## Jenkins Active Choices

```bash
python3 cli.py jenkins-refsets
```

## Dodanie jednego IP

```bash
python3 cli.py add --refset "Blocked IPs" --ip "10.0.0.1"
```

## Dodanie wielu IP

```bash
python3 cli.py add --refset "Blocked IPs" --ip "10.0.0.1,10.0.0.2"
```

lub:

```bash
python3 cli.py add --refset "Blocked IPs" --ip "$IPS"
```

gdzie `$IPS` może zawierać:

```text
10.0.0.1
10.0.0.2
192.168.1.10,172.16.1.1
```

## Logger

```bash
python3 cli.py   --log-level DEBUG   --log-file ./qradar-cli.log   add   --refset "Blocked IPs"   --ip "10.0.0.1,10.0.0.2"
```


## Sprawdzanie czy IP jest w reference secie

Jeden adres:

```bash
python3 cli.py contains   --refset "Blocked IPs"   --ip "10.0.0.1"
```

Alias:

```bash
python3 cli.py check   --refset "Blocked IPs"   --ip "10.0.0.1"
```

Wiele adresów:

```bash
python3 cli.py contains   --refset "Blocked IPs"   --ip "10.0.0.1,10.0.0.2"
```

lub wieloliniowo:

```bash
python3 cli.py contains   --refset "Blocked IPs"   --ip "$IPS"
```

Przykładowy output:

```text
10.0.0.1=true
10.0.0.2=false
```

Dla jednego IP exit code:
- `0` = IP istnieje
- `1` = IP nie istnieje
- `2` = błąd API / konfiguracji / walidacji

Dla wielu IP:
- `0` = sprawdzenie wykonane poprawnie
- `2` = co najmniej jeden błąd techniczny

## Usuwanie IP z reference seta

Jeden adres:

```bash
python3 cli.py remove   --refset "Blocked IPs"   --ip "10.0.0.1"
```

Alias:

```bash
python3 cli.py delete   --refset "Blocked IPs"   --ip "10.0.0.1"
```

Wiele adresów:

```bash
python3 cli.py remove   --refset "Blocked IPs"   --ip "10.0.0.1,10.0.0.2"
```

Usunięcie działa w trzech krokach:

```text
reference set NAME
        |
        v
resolve NAME -> collection ID
        |
        v
find entry by collection_id + IP value
        |
        v
DELETE /reference_data_collections/set_entries/{entry_id}
```

Jeśli IP nie istnieje, wynik to `NOT_FOUND`, bez traktowania tego jako błędu Jenkinsa.
