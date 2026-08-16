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
