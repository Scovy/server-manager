# Plan Implementacji — Homelab Dashboard
### Praca inżynierska | Kierunek: Informatyka

---

## Spis treści

1. [Opis projektu](#1-opis-projektu)
2. [Porównanie z istniejącymi rozwiązaniami](#2-porównanie-z-istniejącymi-rozwiązaniami)
3. [Architektura systemu](#3-architektura-systemu)
4. [Tech Stack](#4-tech-stack)
5. [Schemat bazy danych](#5-schemat-bazy-danych)
6. [Fazy implementacji](#6-fazy-implementacji)
7. [Szczegółowy harmonogram (16 tygodni)](#7-szczegółowy-harmonogram-16-tygodni)
8. [Moduły — szczegóły implementacji](#8-moduły--szczegóły-implementacji)
9. [API — kluczowe endpointy](#9-api--kluczowe-endpointy)
10. [Hardening serwera](#10-hardening-serwera)
11. [Skrypt instalacyjny](#11-skrypt-instalacyjny)
12. [Struktura projektu](#12-struktura-projektu)
13. [Testowanie](#13-testowanie)
14. [MVP vs Nice-to-have](#14-mvp-vs-nice-to-have)
15. [CI/CD — GitHub Actions](#15-cicd--github-actions)

---

## 1. Opis projektu

**Homelab Dashboard** to webowy panel zarządzania dla prywatnych serwerów opartych na Ubuntu Server. Łączy monitoring systemu, zarządzanie kontenerami Docker, marketplace szablonów aplikacji oraz automatyczną konfigurację SSL z reverse proxy. System instaluje się jedną komendą i zawiera wbudowany moduł hardeningu serwera.

### Cele projektu

- Dostarczenie prostego w obsłudze interfejsu do zarządzania homeserverem bez znajomości CLI
- Automatyzacja powtarzalnych zadań: SSL, DNS, backup, aktualizacje bezpieczeństwa
- Edukacja użytkownika w zakresie hardowania serwera przez wbudowane wiki
- Stworzenie otwartego, rozszerzalnego systemu opartego wyłącznie na technologiach open-source

---

## 2. Porównanie z istniejącymi rozwiązaniami

| Funkcja | Homelab Dashboard | Portainer | CasaOS | Cosmos Cloud |
|---|---|---|---|---|
| Monitoring systemu | ✅ | ❌ | ✅ | ✅ |
| Marketplace szablonów | ✅ | ✅ | ✅ | ✅ |
| Auto SSL + subdomeny | ✅ | ❌ | ❌ | ✅ |
| Server hardening | ✅ | ❌ | ❌ | ❌ |
| Wiki hardeningu | ✅ | ❌ | ❌ | ❌ |
| Backup & Restore UI | ✅ | ❌ | ❌ | ✅ |
| TOTP 2FA | ✅ | ✅ | ❌ | ✅ |
| Audit log | ✅ | ✅ | ❌ | ❌ |
| Instalacja 1 komendą | ✅ | ✅ | ✅ | ✅ |
| Terminal w przeglądarce | ✅ | ✅ | ❌ | ❌ |

---

## 3. Architektura systemu

```
┌─────────────────────────────────────────────────────┐
│                    Przeglądarka                      │
│              React SPA — port 443 HTTPS              │
└─────────────────────┬───────────────────────────────┘
                      │ HTTPS / WebSocket / SSE
┌─────────────────────▼───────────────────────────────┐
│           Caddy — Reverse Proxy + SSL                │
│    Let's Encrypt, dynamiczne subdomeny, port 80/443  │
└──────────┬──────────────────────┬───────────────────┘
           │                      │
┌──────────▼──────┐    ┌──────────▼──────────────────┐
│   Frontend      │    │   Backend FastAPI            │
│  Vite + Nginx   │    │   systemd service            │
│  port 3000      │    │   port 8000                  │
│  (static build) │    │   REST / WebSocket / SSE     │
└─────────────────┘    └──────────┬───────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
    ┌─────────▼──────┐  ┌────────▼───────┐  ┌────────▼───────────────┐
    │  Docker Engine  │  │    SQLite      │  │ System (psutil)        │
    │  /docker.sock   │  │  konfiguracja  │  │ CPU/RAM/Dysk           │
    │  (docker-socket │  └────────────────┘  └────────────────────────┘
    │   -proxy)       │
    └─────────────────┘
```

> **Uwaga architektoniczna:** Backend FastAPI działa jako natywna usługa systemd na hoście (nie w kontenerze Docker). Daje to bezpośredni dostęp do `psutil` (metryki hosta, a nie kontenera), prostszą komunikację z Docker Engine, oraz eliminuje problem "Docker-in-Docker". Frontend jest budowany jako statyczny build i serwowany przez Caddy.

### Komunikacja w czasie rzeczywistym

- **WebSocket** (`/ws/metrics`) — push metryk systemowych co 2 sekundy do wszystkich klientów
- **SSE** (`/api/containers/{id}/logs`) — strumieniowanie logów kontenera
- **WebSocket** (`/api/containers/{id}/exec`) — terminal w przeglądarce (xterm.js) — wymaga dwukierunkowej komunikacji (stdin/stdout), dlatego SSE (jednokierunkowe) nie jest wystarczające

---

## 4. Tech Stack

### Backend

| Technologia | Wersja | Zastosowanie |
|---|---|---|
| Python | 3.12+ | Język backendu |
| FastAPI | 0.111+ | Framework HTTP/WebSocket/SSE |
| SQLAlchemy | 2.0+ | ORM z async support |
| SQLite | 3.x | Baza danych (jeden plik = trivialny backup) |
| Docker SDK for Python | 7.x | Komunikacja z Docker Engine |
| psutil | 6.x | Metryki systemowe (CPU, RAM, dysk, sieć) |
| APScheduler | 3.x | Harmonogram zadań (backup, Lynis, DDNS) |
| pyotp | 2.x | TOTP 2FA (Google Authenticator) |
| PyJWT | 2.x | JWT access + refresh tokens (python-jose jest porzucony i posiada znane CVE) |
| bcrypt | 4.x | Hashowanie haseł (cost factor 12) |

### Frontend

| Technologia | Wersja | Zastosowanie |
|---|---|---|
| React | 18+ | Framework UI |
| TypeScript | 5+ | Typowanie statyczne |
| Vite | 5+ | Bundler, HMR w dev |
| TanStack Query | 5+ | Cache, polling, invalidacja |
| Tailwind CSS | 3+ | Utility-first styling |
| shadcn/ui | latest | Komponenty UI (dostępne, zgodne z Tailwind) |
| Recharts | 2+ | Wykresy metryk (LineChart, AreaChart) |
| xterm.js | 5+ | Terminal w przeglądarce (logi, exec shell) |
| CodeMirror | 6+ | Edytor YAML/ENV z syntax highlighting |
| React Router | 6+ | Routing SPA |

### Infrastruktura

| Technologia | Zastosowanie |
|---|---|
| Caddy v2 | Reverse proxy, auto Let's Encrypt, Admin API |
| Docker + Docker Compose v2 | Konteneryzacja aplikacji użytkownika i samego dashboardu |
| Ubuntu Server 22.04 / 24.04 LTS | Docelowy system operacyjny |
| UFW | Firewall |
| Fail2Ban | IPS — ochrona przed bruteforce |
| Lynis | Audyt bezpieczeństwa systemu |

### Uzasadnienie kluczowych wyborów

**Caddy zamiast Nginx/Traefik** — Caddy posiada wbudowany Admin API umożliwiający dynamiczne dodawanie reguł routingu bez restartu serwisu. Obsługa Let's Encrypt jest natywna i nie wymaga dodatkowych pluginów. HTTP → HTTPS redirect działa domyślnie.

**SQLite zamiast PostgreSQL** — homelab to środowisko single-user. SQLite eliminuje potrzebę zarządzania oddzielnym serwerem bazy danych. Cały stan aplikacji to jeden plik — backup sprowadza się do jego skopiowania.

**FastAPI zamiast Node.js/Express** — Python posiada oficjalny Docker SDK oraz psutil, które są kluczowymi bibliotekami projektu. FastAPI generuje dokumentację OpenAPI automatycznie, co ułatwia testowanie i prezentację na obronie.

---

## 5. Schemat bazy danych

```sql
-- Użytkownicy i uwierzytelnianie
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,             -- bcrypt hash
    totp_secret TEXT,                      -- NULL = 2FA wyłączone
    role        TEXT DEFAULT 'admin',      -- admin | viewer
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Historia metryk systemowych
CREATE TABLE metrics_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    cpu_percent REAL,
    ram_percent REAL,
    ram_used_mb INTEGER,
    disk_percent REAL,
    net_bytes_sent INTEGER,
    net_bytes_recv INTEGER
);

-- Indeks na timestamp — wymagany dla wydajnego TTL pruning (DELETE WHERE timestamp < ...)
-- Bez indeksu każde czyszczenie robi full table scan co 60 sekund
CREATE INDEX idx_metrics_history_ts ON metrics_history(timestamp);

-- Zainstalowane aplikacje (kontenery z marketplace)
CREATE TABLE apps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    container_id    TEXT UNIQUE,           -- Docker container ID
    name            TEXT NOT NULL,
    template_id     TEXT,                  -- referencja do szablonu marketplace
    domain          TEXT,                  -- np. gitea.example.org
    ssl_enabled     INTEGER DEFAULT 1,
    compose_path    TEXT,                  -- ścieżka do docker-compose.yml
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Konfiguracja subdomen i SSL
CREATE TABLE domains (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subdomain       TEXT NOT NULL,
    container_id    TEXT,
    target_port     INTEGER,
    ssl_status      TEXT DEFAULT 'pending', -- pending | active | error
    cert_expiry     DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Harmonogram i konfiguracja backupów
CREATE TABLE backup_schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    frequency   TEXT DEFAULT 'weekly',     -- daily | weekly | manual
    keep_last   INTEGER DEFAULT 7,
    remote_url  TEXT,                      -- opcjonalnie rclone target
    last_run    DATETIME,
    next_run    DATETIME
);

-- Audit log
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    user_id     INTEGER REFERENCES users(id),
    action      TEXT NOT NULL,             -- np. container.stop, backup.create
    target      TEXT,                      -- np. container ID, domain name
    ip_address  TEXT,
    success     INTEGER DEFAULT 1
);

-- Konfiguracja ogólna (klucz-wartość)
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Fazy implementacji

### Faza 1 — Fundament & Instalacja (tygodnie 1–3)

**Cel:** działający szkielet aplikacji z uwierzytelnianiem i podstawową listą kontenerów.

Zakres:
- Skrypt instalacyjny (`install.sh`) — instalacja zależności, konfiguracja UFW/Fail2Ban, `docker compose up -d`
- FastAPI boilerplate: struktura projektu, middleware CORS, obsługa błędów, Alembic migracje
- SQLite schema: tabele `users`, `audit_log`, `settings`
- JWT auth: login, refresh token w httpOnly cookie, middleware autoryzacji
- Docker bridge: połączenie z `/var/run/docker.sock`, endpoint `GET /api/containers`
- React + Vite setup: routing, protected routes, ekran logowania, sidebar nawigacja

### Faza 2 — Monitoring & Dashboard (tygodnie 4–6)

**Cel:** widok dashboardu z żywymi metrykami i wykresami.

Zakres:
- psutil polling co 2 sekundy, WebSocket `/ws/metrics`
- Zapis historii metryk do SQLite co 60 sekund (TTL 7 dni, rotacja starych rekordów)
- Per-kontener metryki przez Docker stats stream API
- Frontend: karty CPU/RAM/Disk/Network, Recharts LineChart z rolling window 60 punktów
- Alerty: konfiguracja progów (np. CPU > 80%), webhook na Discord lub e-mail

### Faza 3 — Zarządzanie kontenerami (tygodnie 7–9)

**Cel:** pełna obsługa cyklu życia kontenerów z logami i terminalem.

Zakres:
- Akcje: start, stop, restart, kill, remove (z opcją usunięcia wolumenów)
- SSE stream logów (`docker logs --follow`) → xterm.js w przeglądarce
- Exec do kontenera: WebSocket → `/bin/sh` → xterm.js terminal
- Edytor docker-compose.yml: CodeMirror z syntax highlight YAML + walidacja
- Edytor zmiennych .env: tabela klucz-wartość z maskowaniem sekretów
- Zarządzanie wolumenami i sieciami Docker z poziomu UI

### Faza 4 — Marketplace & SSL (tygodnie 10–13)

**Cel:** deploy nowych aplikacji jednym kliknięciem z automatycznym HTTPS.

Zakres:
- Katalog szablonów w formacie JSON/YAML (10+ aplikacji MVP)
- Deploy flow: wybór szablonu → formularz env vars → walidacja portu/wolumenu → `docker compose up -d`
- Caddy Admin API: dynamiczne dodawanie reguł routingu po deploy
- Let's Encrypt przez HTTP-01 challenge, auto-odnowienie certyfikatów
- DuckDNS/FreeDDNS integracja: automatyczna aktualizacja rekordu A
- Update checker: porównanie aktualnego tagu image z Docker Hub API

**Aplikacje w marketplace (MVP):**
Nextcloud, Jellyfin, Plex, Gitea, n8n, Vaultwarden, Home Assistant, Uptime Kuma, Immich, Portainer

### Faza 5 — Backup, Hardening & Wiki (tygodnie 14–16)

**Cel:** bezpieczeństwo, odtwarzalność systemu i dokumentacja dla użytkownika.

Zakres:
- Backup: archiwum `.tar.gz` z bazą SQLite, konfiguracją Caddy, plikami `.env`, sygnaturą SHA256
- Restore: upload archiwum → walidacja sygnatury → restart serwisów
- Harmonogram auto-backup (APScheduler), retencja N ostatnich backupów
- TOTP 2FA: pyotp + QR code, backup codes jednorazowe
- Audit log UI: tabela z filtrowaniem po akcji, użytkowniku, zakresie dat
- Wiki wbudowane w dashboard: Markdown renderer, sekcje hardeningu krok po kroku
- Lynis: wyniki ostatniego audytu widoczne w zakładce Security

---

## 7. Szczegółowy harmonogram (16 tygodni)

| Tydzień | Cel | Deliverable |
|---|---|---|
| 1 | Setup projektu, repo, CI/CD | GitHub Actions (lint + test na PR), Docker Compose dev |
| 2 | Backend: auth + Docker bridge | JWT auth, endpoint `GET /api/containers` |
| 3 | Frontend: layout + auth UI | Ekran logowania, lista kontenerów, sidebar |
| 4 | Metryki systemu (backend) | WebSocket `/ws/metrics`, historia w SQLite |
| 5 | Dashboard UI | Wykresy CPU/RAM/Network/Disk, per-kontener panel |
| 6 | Alerty & powiadomienia | Webhook Discord/e-mail, konfiguracja progów |
| 7 | Container manager (backend) | Start/stop/kill/remove API, SSE logów, exec |
| 8 | Container UI | xterm.js logi + terminal, edytor compose/env |
| 9 | Wolumeny & sieci Docker | Lista wolumenów, inspektor sieci, bind mounts |
| 10 | Caddy integration | Admin API wrapper, dynamiczne routy, Let's Encrypt |
| 11 | Marketplace (backend) | Struktura szablonów, deploy flow, walidacja |
| 12 | Marketplace UI + DDNS | Karty aplikacji, kategorie, DuckDNS integracja |
| 13 | Update checker + import | Docker Hub API, import własnych szablonów |
| 14 | Backup & Restore | Export/import tar.gz, harmonogram, SHA256 |
| 15 | Hardening + 2FA + Audit log | Skrypt hardening, TOTP UI, tabela audit logu |
| 16 | Wiki + testy + dokumentacja | Wiki Markdown, testy Pytest, README, OpenAPI docs |

**Szacowany nakład pracy:** ~320–380 godzin (ok. 22 h/tydzień przez 16 tygodni)

---

## 8. Moduły — szczegóły implementacji

### 8.1 System Monitor

- `psutil` polling co 2s: `cpu_percent()`, `virtual_memory()`, `disk_usage()`, `net_io_counters()`
- WebSocket endpoint `/ws/metrics` — broadcast do wszystkich połączonych klientów
- Metryki per-kontener przez Docker API stream (`docker stats --no-stream`)
- Historia zapisywana co 60 sekund do tabeli `metrics_history`, TTL 7 dni
- Recharts `LineChart` z `ResponsiveContainer` i rolling window ostatnich 60 punktów
- Alerty progowe: konfiguracja w UI → zapis w `settings` → sprawdzanie przy każdym pollingu

### 8.2 Container Manager

- Docker SDK: `docker.from_env()` przez `/var/run/docker.sock`
- Akcje synchroniczne: `container.start()`, `container.stop()`, `container.kill()`, `container.remove(v=True)`
- Logi: `container.logs(stream=True, follow=True)` → generator → FastAPI `EventSourceResponse`
- Exec: `container.exec_run(cmd, socket=True)` → WebSocket → xterm.js
- Edytor compose: FastAPI odczytuje/zapisuje plik YAML, `docker compose up -d --force-recreate`
- Edytor ENV: parse pliku `.env` → słownik → zapis z powrotem do pliku

### 8.3 Marketplace

Struktura szablonu:

```yaml
id: gitea
name: Gitea
description: Self-hosted Git service
category: dev
logo: gitea.png
version: "1.21"
ports:
  - host: 3000
    container: 3000
volumes:
  - host: ./data/gitea
    container: /data
env_vars:
  - key: GITEA_DATABASE_TYPE
    default: sqlite3
    required: true
  - key: USER_UID
    default: "1000"
    required: false
compose_template: |
  version: "3.8"
  services:
    gitea:
      image: gitea/gitea:{{ version }}
      environment:
        USER_UID: {{ USER_UID }}
      ports:
        - "{{ ports[0].host }}:{{ ports[0].container }}"
      volumes:
        - {{ volumes[0].host }}:{{ volumes[0].container }}
```

Deploy flow:
1. `POST /api/marketplace/deploy` z wypełnionymi parametrami
2. Renderowanie szablonu Jinja2
3. Sprawdzenie dostępności portu (`socket.connect()`)
4. Zapis do `./apps/{app_name}/docker-compose.yml`
5. `docker compose up -d`
6. Dodanie rekordu do tabeli `apps`
7. Wywołanie Caddy Admin API — dodanie reguły routingu + regeneracja `Caddyfile` (persystencja)
8. Aktualizacja DDNS (jeśli skonfigurowane)
9. Dodanie Docker labels do kontenera: `com.homelab.managed=true`, `com.homelab.template={template_id}`, `com.homelab.compose-project={app_name}` — umożliwiają mapowanie uruchomionego kontenera z powrotem do jego projektu compose

### 8.4 SSL & Reverse Proxy (Caddy)

Caddy Admin API — dodanie nowej reguły routingu:

```python
import httpx

async def add_caddy_route(subdomain: str, target_port: int, domain: str):
    route = {
        "match": [{"host": [f"{subdomain}.{domain}"]}],
        "handle": [{
            "handler": "reverse_proxy",
            "upstreams": [{"dial": f"localhost:{target_port}"}]
        }]
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:2019/config/apps/http/servers/srv0/routes",
            json=route
        )
    return resp.status_code == 200
```

Caddy obsługuje Let's Encrypt automatycznie — sama subdomena w konfiguracji uruchamia pobieranie certyfikatu.

> **Ważne — persystencja konfiguracji Caddy:** Dynamicznie dodane reguły routingu przez Admin API są utracone po restarcie Caddy. Rozwiązanie: po każdej zmianie routingu backend generuje plik `Caddyfile` na podstawie aktualnego stanu tabeli `domains` i wykonuje `caddy reload`. Alternatywnie można użyć `POST /config/` do zapisania pełnej konfiguracji do storage Caddy.

### 8.5 Backup & Restore

Zawartość backupu:

```
backup_2024-11-15_03-00.tar.gz
├── manifest.json          # wersja dashboardu, timestamp, SHA256 każdego pliku
├── database.sqlite        # cała baza SQLite
├── caddy_config.json      # eksport konfiguracji Caddy
├── apps/
│   ├── gitea/
│   │   ├── docker-compose.yml
│   │   └── .env
│   └── nextcloud/
│       ├── docker-compose.yml
│       └── .env
└── settings.json          # eksport tabeli settings
```

Restore flow:
1. Upload pliku przez UI
2. Weryfikacja SHA256 każdego pliku z `manifest.json`
3. Zatrzymanie dashboardu (`docker compose stop backend`)
4. Przywrócenie `database.sqlite`
5. Przywrócenie plików `docker-compose.yml` i `.env`
6. Import konfiguracji do Caddy Admin API
7. Restart backendu

### 8.6 Security Module

- JWT: `access_token` (TTL 15 min) w headerze `Authorization: Bearer`, `refresh_token` (TTL 7 dni) w httpOnly cookie
- 2FA: `pyotp.TOTP(secret).verify(code)` — weryfikacja przy logowaniu, konfiguracja przez QR code
- Rate limiting: `slowapi` — max 5 prób logowania / minutę / IP, po przekroczeniu blokada 15 min. **Uwaga:** za Caddy reverse proxy backend widzi wszystkie żądania z IP `127.0.0.1`. Należy skonfigurować Caddy do przekazywania nagłówka `X-Forwarded-For` oraz `slowapi` do używania `request.headers.get("X-Forwarded-For")` jako klucza rate limitingu.
- CSRF protection: double-submit cookie pattern — backend generuje token CSRF w cookie, frontend dołącza go jako nagłówek `X-CSRF-Token` w każdym żądaniu modyfikującym stan. Wymagane ponieważ `refresh_token` jest przechowywany w httpOnly cookie.
- Audit log: middleware FastAPI zapisuje każde żądanie modyfikujące stan do tabeli `audit_log`
- Role: `admin` (pełny dostęp) i `viewer` (GET /api/metrics, GET /api/containers — tylko odczyt)
- Graceful degradation: wszystkie operacje Docker są opakowane w try/except — jeśli Docker Engine jest niedostępny, dashboard wyświetla stan degradowany (metryki systemu działają, zarządzanie kontenerami wyłączone z komunikatem błędu)

---

## 9. API — kluczowe endpointy

### Autentykacja

```
POST   /api/auth/login          # login + opcjonalne 2FA challenge
POST   /api/auth/refresh         # odświeżenie access tokena
POST   /api/auth/logout          # unieważnienie refresh tokena
POST   /api/auth/2fa/setup       # generowanie sekretu TOTP + QR code
POST   /api/auth/2fa/verify      # weryfikacja kodu TOTP
```

### System

```
GET    /api/health               # status usług: backend, Docker Engine, SQLite, Caddy — używany przez monitoring i healthcheck systemd
```

### Metryki

```
GET    /ws/metrics               # WebSocket: metryki co 2s
GET    /api/metrics/history      # historia metryk (query: from, to, interval)
GET    /api/metrics/alerts       # konfiguracja i historia alertów
PUT    /api/metrics/alerts       # aktualizacja progów alertów
```

### Kontenery

```
GET    /api/containers                    # lista wszystkich kontenerów
GET    /api/containers/{id}              # szczegóły kontenera
POST   /api/containers/{id}/start        # start
POST   /api/containers/{id}/stop         # stop (grace period)
POST   /api/containers/{id}/restart      # restart
POST   /api/containers/{id}/kill         # kill (SIGKILL)
DELETE /api/containers/{id}             # remove (query: ?volumes=true)
GET    /api/containers/{id}/logs         # SSE stream logów
GET    /api/containers/{id}/stats        # aktualne zużycie zasobów
GET    /api/containers/{id}/compose      # odczyt docker-compose.yml
PUT    /api/containers/{id}/compose      # aktualizacja docker-compose.yml
GET    /api/containers/{id}/env          # odczyt zmiennych .env
PUT    /api/containers/{id}/env          # aktualizacja zmiennych .env
POST   /api/containers/{id}/exec         # WebSocket: exec shell
```

### Marketplace

```
GET    /api/marketplace                  # lista szablonów (query: category, search)
GET    /api/marketplace/{id}             # szczegóły szablonu
POST   /api/marketplace/deploy           # deploy aplikacji z szablonu
POST   /api/marketplace/import           # import własnego szablonu
GET    /api/marketplace/updates          # sprawdzenie dostępnych aktualizacji
```

### Domeny i SSL

```
GET    /api/domains                      # lista subdomen i status certyfikatów
POST   /api/domains                      # dodaj subdomenę + Caddy route
DELETE /api/domains/{id}                # usuń subdomenę
POST   /api/domains/ddns/update          # ręczna aktualizacja DDNS
GET    /api/domains/ddns/config          # konfiguracja DDNS
PUT    /api/domains/ddns/config          # aktualizacja konfiguracji DDNS
```

### Backup

```
POST   /api/backup/export                # tworzenie i pobieranie archiwum
POST   /api/backup/import                # przywrócenie z archiwum (upload)
GET    /api/backup/list                  # lista lokalnych backupów
DELETE /api/backup/{filename}           # usunięcie backupu
GET    /api/backup/schedule              # konfiguracja harmonogramu
PUT    /api/backup/schedule              # aktualizacja harmonogramu
```

### Bezpieczeństwo

```
GET    /api/security/audit-log           # historia zdarzeń (query: user, action, from, to)
GET    /api/security/lynis               # ostatni raport Lynis
POST   /api/security/lynis/run           # uruchomienie audytu Lynis
GET    /api/security/sessions            # aktywne sesje użytkownika
DELETE /api/security/sessions/{id}      # unieważnienie sesji
```

---

## 10. Hardening serwera

### Automatyczny (skrypt instalacyjny)

| Komponent | Co robi |
|---|---|
| **UFW** | `ufw allow 22,80,443/tcp && ufw enable` — blokada wszystkiego poza SSH/HTTP/HTTPS |
| **Fail2Ban — SSH jail** | `maxretry=5`, `bantime=1h`, `findtime=10m` |
| **Fail2Ban — Caddy jail** | Monitorowanie logów Caddy: 429/401 → ban po 10 próbach |
| **unattended-upgrades** | Automatyczne instalowanie łatek bezpieczeństwa (security only) |
| **SSH hardening (basic)** | `PermitRootLogin no`, `MaxAuthTries 3`, `LoginGraceTime 60` |
| **Lynis cronjob** | Audyt co niedzielę o 3:00, raport w `/var/log/lynis-report.dat` |
| **Docker socket** | Dostęp przez `docker-socket-proxy` (Tecnativa) — ogranicza dostępne endpointy Docker API do wymaganych (containers, images, volumes, networks). Backend łączy się z proxy zamiast bezpośrednio z `/var/run/docker.sock`. Pełny dostęp do socketa = dostęp root, dlatego proxy jest warstwą ochronną. |

### Manualny (Wiki w dashboardzie)

| Sekcja | Zawartość |
|---|---|
| **SSH key-only** | Generowanie klucza Ed25519, dodanie do `authorized_keys`, wyłączenie uwierzytelniania hasłem |
| **2FA dla SSH** | Instalacja `libpam-google-authenticator`, konfiguracja `/etc/pam.d/sshd` |
| **Zmiana portu SSH** | Edycja `sshd_config`, aktualizacja reguły UFW, aktualizacja jailów Fail2Ban |
| **CrowdSec** | Alternatywa dla Fail2Ban z crowdsourced threat intelligence, integracja z bouncerem Caddy |
| **Offsite backup** | Konfiguracja Rclone (S3, Backblaze B2, Nextcloud), test przywracania |
| **Audit systemu** | Interpretacja raportu Lynis, priorytetyzacja ostrzeżeń, plan działania |

---

## 11. Skrypt instalacyjny

```bash
#!/bin/bash
# install.sh — Homelab Dashboard installer
# Użycie: curl -fsSL https://get.homelab-dashboard.dev | bash

set -e

# 1. Weryfikacja systemu
check_os() {
    [[ -f /etc/os-release ]] && source /etc/os-release
    if [[ "$ID" != "ubuntu" ]] || [[ "${VERSION_ID}" < "22.04" ]]; then
        echo "ERROR: Wymagany Ubuntu 22.04 lub nowszy"
        exit 1
    fi
}

# 2. Instalacja zależności
install_dependencies() {
    apt-get update -q
    apt-get install -y -q \
        docker.io docker-compose-plugin \
        fail2ban ufw lynis \
        unattended-upgrades apt-listchanges
}

# 3. Konfiguracja UFW
setup_ufw() {
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
}

# 4. Konfiguracja Fail2Ban
setup_fail2ban() {
    cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 3600

[caddy]
enabled = true
port = 80,443
logpath = /var/log/caddy/access.log
maxretry = 10
EOF
    systemctl restart fail2ban
}

# 5. SSH hardening
harden_ssh() {
    sed -i 's/#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
    sed -i 's/#MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config
    systemctl restart sshd
}

# 6. Lynis cronjob
setup_lynis() {
    echo "0 3 * * 0 root lynis audit system --quiet > /var/log/lynis-report.dat 2>&1" \
        > /etc/cron.d/lynis-audit
}

# 7. Konfiguracja dashboardu
setup_dashboard() {
    mkdir -p /opt/homelab-dashboard
    cd /opt/homelab-dashboard

    # Generowanie sekretów
    JWT_SECRET=$(openssl rand -hex 32)
    ADMIN_PASS=$(openssl rand -base64 12)

    cat > .env << EOF
JWT_SECRET=${JWT_SECRET}
ADMIN_PASSWORD=${ADMIN_PASS}
DOMAIN=${DOMAIN:-localhost}
EOF

    # Pobieranie docker-compose.yml
    curl -fsSL https://raw.githubusercontent.com/user/homelab-dashboard/main/docker-compose.yml \
        -o docker-compose.yml

    docker compose up -d
}

# Główna pętla instalacji
main() {
    echo "🏠 Homelab Dashboard — instalator"
    echo "=================================="
    read -p "Podaj swoją domenę (np. home.example.org): " DOMAIN

    check_os
    install_dependencies
    setup_ufw
    setup_fail2ban
    harden_ssh
    setup_lynis
    setup_dashboard

    echo ""
    echo "✅ Instalacja zakończona!"
    echo "   URL: https://${DOMAIN}"
    echo "   Login: admin"
    echo "   Hasło: ${ADMIN_PASS}"
    echo ""
    echo "⚠️  Zmień hasło po pierwszym logowaniu!"
}

main "$@"
```

---

## 12. Struktura projektu

```
homelab-dashboard/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app init, middleware
│   │   ├── config.py               # Ustawienia z .env (pydantic-settings)
│   │   ├── database.py             # SQLAlchemy engine, session
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── app.py
│   │   │   ├── domain.py
│   │   │   └── audit_log.py
│   │   ├── routers/
│   │   │   ├── auth.py             # /api/auth/*
│   │   │   ├── containers.py       # /api/containers/*
│   │   │   ├── metrics.py          # /api/metrics/* + /ws/metrics
│   │   │   ├── marketplace.py      # /api/marketplace/*
│   │   │   ├── domains.py          # /api/domains/*
│   │   │   ├── backup.py           # /api/backup/*
│   │   │   └── security.py         # /api/security/*
│   │   ├── services/
│   │   │   ├── docker_service.py   # Docker SDK wrapper
│   │   │   ├── metrics_service.py  # psutil + Docker stats
│   │   │   ├── caddy_service.py    # Caddy Admin API client
│   │   │   ├── ddns_service.py     # DuckDNS/FreeDDNS update
│   │   │   ├── backup_service.py   # tar.gz export/import
│   │   │   └── scheduler.py        # APScheduler jobs
│   │   └── middleware/
│   │       ├── auth.py             # JWT verification
│   │       └── audit.py            # Audit log middleware
│   ├── marketplace/
│   │   └── templates/
│   │       ├── gitea.yaml
│   │       ├── nextcloud.yaml
│   │       ├── jellyfin.yaml
│   │       └── ...
│   ├── alembic/                    # Migracje bazy danych
│   ├── tests/
│   │   ├── test_auth.py
│   │   ├── test_containers.py
│   │   └── test_marketplace.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx       # Główny widok metryk
│   │   │   ├── Containers.tsx      # Lista i zarządzanie kontenerami
│   │   │   ├── ContainerDetail.tsx # Szczegóły + logi + terminal
│   │   │   ├── Marketplace.tsx     # Katalog aplikacji
│   │   │   ├── Domains.tsx         # Zarządzanie subdomenami
│   │   │   ├── Backup.tsx          # Backup & Restore
│   │   │   ├── Security.tsx        # Audit log + Lynis
│   │   │   ├── Wiki.tsx            # Przewodnik hardeningu
│   │   │   └── Settings.tsx        # Ustawienia dashboardu
│   │   ├── components/
│   │   │   ├── MetricCard.tsx
│   │   │   ├── MetricChart.tsx
│   │   │   ├── ContainerCard.tsx
│   │   │   ├── LogViewer.tsx       # xterm.js wrapper
│   │   │   ├── Terminal.tsx        # exec shell
│   │   │   └── AppCard.tsx         # karta marketplace
│   │   ├── hooks/
│   │   │   ├── useMetricsWS.ts     # WebSocket hook
│   │   │   ├── useContainers.ts    # TanStack Query
│   │   │   └── useAuth.ts
│   │   ├── api/                    # axios klienty API
│   │   └── types/                  # TypeScript interfaces
│   ├── Dockerfile
│   └── package.json
│
├── caddy/
│   └── Caddyfile                   # Konfiguracja startowa
│
├── docker-compose.yml              # Stack: backend + frontend + caddy
├── docker-compose.dev.yml          # Override dla developmentu
├── install.sh                      # Skrypt instalacyjny
└── README.md
```

---

## 13. Testowanie

### Testy jednostkowe (backend)

```python
# tests/test_containers.py — przykład
import pytest
from unittest.mock import MagicMock, patch
from app.services.docker_service import DockerService

@pytest.fixture
def docker_service():
    with patch('docker.from_env') as mock_docker:
        service = DockerService()
        service.client = mock_docker.return_value
        yield service

def test_list_containers(docker_service):
    mock_container = MagicMock()
    mock_container.id = "abc123"
    mock_container.name = "gitea"
    mock_container.status = "running"
    docker_service.client.containers.list.return_value = [mock_container]

    result = docker_service.list_containers()
    assert len(result) == 1
    assert result[0]["name"] == "gitea"

def test_stop_container_not_found(docker_service):
    from docker.errors import NotFound
    docker_service.client.containers.get.side_effect = NotFound("xyz")
    with pytest.raises(ValueError, match="Container not found"):
        docker_service.stop_container("xyz")
```

### Testy integracyjne (API)

```python
# tests/test_auth_api.py — przykład
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_login_success():
    response = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "testpass"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_rate_limit():
    for _ in range(6):
        client.post("/api/auth/login", json={"username": "x", "password": "wrong"})
    response = client.post("/api/auth/login", json={"username": "x", "password": "wrong"})
    assert response.status_code == 429
```

### Zakres testów

| Komponent | Typ testu | Narzędzie |
|---|---|---|
| Docker service | Unit (mock) | pytest + unittest.mock |
| Auth endpoints | Integration | FastAPI TestClient |
| Caddy service | Unit (mock HTTP) | pytest + httpx mock |
| Backup service | Integration | pytest + tmp_path |
| Frontend komponenty | Unit | Vitest + React Testing Library |
| E2E flows | End-to-end | Playwright (opcjonalne) |

---

## 14. MVP vs Nice-to-have

### MVP (praca inżynierska — wymagane)

- Dashboard z metrykami systemu w czasie rzeczywistym (CPU/RAM/Disk/Network)
- Zarządzanie kontenerami Docker (start/stop/kill/remove/logi/terminal)
- Marketplace z min. 5 szablonami aplikacji
- Automatyczny SSL i subdomeny przez Caddy
- Backup i Restore konfiguracji
- Uwierzytelnianie z JWT
- Server hardening przez skrypt instalacyjny
- Instalacja jedną komendą

### Nice-to-have (jeśli zostanie czas)

- TOTP 2FA
- Audit log z UI
- Wiki hardeningu
- Alerty z webhookiem Discord/e-mail
- Integracja Cloudflare API (auto-tworzenie rekordów DNS)
- Backup zdalny przez Rclone
- Update checker dla kontenerów
- Role użytkowników (admin / viewer)
- Import własnych szablonów marketplace
- Powiadomienia webpush

---

## 15. CI/CD — GitHub Actions

### Strategia

Pipeline oparty na kontenerach Docker — **nie wymaga tworzenia nowej VM przy każdym pushu**. Wszystkie etapy (lint, testy, build) działają w kontenerach CI runnera GitHub Actions. Testy integracyjne używają `docker compose` wewnątrz runnera do uruchomienia efemerycznego stosu testowego.

W przyszłości, jeśli GitHub Actions stanie się ograniczeniem (limity minut, potrzeba self-hosted runnera), migracja na Gitea Actions jest prosta — format YAML jest kompatybilny.

### Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    name: Lint & Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Backend lint
        run: |
          cd backend
          pip install ruff mypy
          ruff check .
          mypy app/ --ignore-missing-imports

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Frontend lint & typecheck
        run: |
          cd frontend
          npm ci
          npm run lint
          npx tsc --noEmit

  test:
    name: Tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Backend tests
        run: |
          cd backend
          pip install -r requirements.txt -r requirements-dev.txt
          pytest --tb=short --cov=app --cov-report=term-missing

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Frontend tests
        run: |
          cd frontend
          npm ci
          npm run test

  build:
    name: Build Docker Images
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4

      - name: Build backend image
        run: docker build -t homelab-backend:${{ github.sha }} ./backend

      - name: Build frontend image
        run: docker build -t homelab-frontend:${{ github.sha }} ./frontend

  deploy:
    name: Push to Registry
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & Push
        run: |
          docker build -t ghcr.io/${{ github.repository }}/backend:latest ./backend
          docker build -t ghcr.io/${{ github.repository }}/frontend:latest ./frontend
          docker push ghcr.io/${{ github.repository }}/backend:latest
          docker push ghcr.io/${{ github.repository }}/frontend:latest
```

### Testowanie skryptu instalacyjnego

Skrypt `install.sh` oraz pełny flow hardeningu **nie są testowane przy każdym pushu** — wymagają pełnego systemu operacyjnego z uprawnieniami root. Zamiast tego:

- **Manualnie** przed każdym release: uruchomienie na lokalnym sprzęcie (VM lub bare metal z Ubuntu Server)
- **Opcjonalnie** cotygodniowy cron job w GitHub Actions z Vagrant/cloud VM do testu instalacji od zera

### Strategia deploymentu

1. CI buduje obrazy i pushuje do GitHub Container Registry (GHCR)
2. Na serwerze: `watchtower` automatycznie wykrywa nowe obrazy i restartuje kontenery
3. Alternatywnie: webhook z GitHub → skrypt na serwerze wykonuje `docker compose pull && docker compose up -d`
4. Migracje bazy danych: Alembic `upgrade head` wykonuje się automatycznie przy starcie backendu (w skrypcie `entrypoint.sh` lub w `main.py` jako startup event)
