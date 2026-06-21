# Server Manager (Homelab Dashboard)

Panel graficzny do zarządzania domowym serwerem (homelab). Umożliwia monitorowanie parametrów systemu w czasie rzeczywistym, zarządzenie cyklem życia kontenerów Docker, instalowanie aplikacji z wbudowanego sklepu (Marketplace) oraz automatyczną konfigurację tras reverse proxy z obsługą SSL (Caddy).

## Stos Technologiczny

* **Backend:** FastAPI (Python 3.10+), SQLite (asynchroniczny asyncalchemy / aiosqlite), Docker SDK for Python, PyJWT
* **Frontend:** React 19, TypeScript, Vite, TanStack Query, CodeMirror (edytor YAML/env), xterm.js (konsola kontenera)
* **Infrastruktura:** Caddy (Reverse Proxy + Auto SSL), Docker Compose, Terraform (wdrożenie Azure)

---

## 1. Uruchomienie lokalne (Development)

### Backend
1. Przejdź do katalogu backendu i utwórz plik `.env`:
   ```bash
   cd backend
   cp .env.example .env
   ```
2. Skonfiguruj środowisko wirtualne Pythona, zainstaluj zależności i wykonaj migracje bazy danych:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   
   # Uruchomienie migracji bazy SQLite (homelab.db)
   alembic upgrade head
   ```
3. Uruchom serwer deweloperski FastAPI:
   ```bash
   uvicorn app.main:app --reload
   ```
   Serwer API będzie dostępny pod adresem: `http://localhost:8000`

### Frontend
1. Przejdź do katalogu frontendu:
   ```bash
   cd ../frontend
   ```
2. Zainstaluj zależności i uruchom serwer deweloperski Vite:
   ```bash
   npm ci
   npm run dev
   ```
   Aplikacja kliencka będzie dostępna pod adresem: `http://localhost:5173`

---

## 2. Wdrożenie produkcyjne (Production)

### Opcja A: Docker Compose (Lokalnie lub VPS)
1. W głównym katalogu projektu utwórz pliki `.env` na podstawie szablonów:
   ```bash
   # Konfiguracja Caddy i domen bazowych
   cp .env.example .env
   
   # Konfiguracja backendu (ustaw bezpieczny JWT_SECRET)
   cp backend/.env.example backend/.env
   ```
2. Zmodyfikuj plik `.env` w głównym katalogu, wpisując swoją domenę oraz e-mail dla certyfikatów SSL:
   ```env
   SITE_ADDRESS=twoja-domena.pl
   DOMAIN=twoja-domena.pl
   ACME_EMAIL=twój-email@domena.pl
   ```
3. Uruchom cały stos aplikacji w tle:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

### Opcja B: Chmura Azure za pomocą Terraform
W katalogu `infra/azure/` przygotowano konfigurację Terraform, która automatycznie tworzy maszynę wirtualną na Azure, instaluje niezbędne pakiety (Docker, docker-compose) i wdraża aplikację przy użyciu `cloud-init`.

1. Przejdź do katalogu wdrożenia Azure:
   ```bash
   cd infra/azure
   ```
2. Zainicjalizuj Terraform i uruchom wdrożenie:
   ```bash
   terraform init
   terraform apply
   ```
3. Po zakończeniu wdrożenia, w konsoli wyświetli się publiczny adres IP serwera oraz gotowa komenda SSH do logowania.

---

## 3. Konfiguracja HTTPS / SSL (Caddy)

Serwer Caddy automatycznie obsługuje żądania SSL i wystawia certyfikaty Let's Encrypt.
1. Skieruj rekord A swojej domeny (np. `serwer.twojadomena.pl`) na publiczny IP serwera.
2. Upewnij się, że porty **80** i **443** są otwarte i przekierowane na serwerze.
3. W przypadku wdrożenia lokalnego bez domeny publicznej (tylko w sieci LAN), możesz uruchomić serwer w trybie HTTP bez SSL, podając w głównym pliku `.env`:
   ```env
   SITE_ADDRESS=http://localhost
   ```

---

## 4. Dostępne skrypty i testy

### Backend (`/backend`)
* `./venv/bin/pytest` — Uruchomienie testów jednostkowych (weryfikacja logowania, 2FA, kontenerów Docker)
* `ruff check .` — Analiza statyczna i linting kodu Pythona
* `mypy app/` — Weryfikacja typowania statycznego Pythona

### Frontend (`/frontend`)
* `npm run test` — Uruchomienie testów Vitest dla komponentów React
* `npm run lint` — Analiza statyczna i linting kodu TypeScript/ESLint
* `npm run build` — Budowanie wersji produkcyjnej frontendu do katalogu `dist`

---

## 5. CI/CD i aktualizacje

* **GitHub Actions:** Przy każdym wypchnięciu zmian (push) do gałęzi `main` uruchamiany jest automatyczny potok CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)), który testuje aplikację, buduje nowe obrazy Docker i publikuje je w rejestrze `ghcr.io`.
* **Watchtower:** Produkcyjne wdrożenie posiada wbudowaną usługę Watchtower, która automatycznie monitoruje rejestr obrazów i bezprzerwowo aktualizuje kontenery na serwerze w momencie publikacji nowej wersji.

---

## Licencja

Projekt jest udostępniany na licencji MIT. Szczegółowe informacje znajdują się w pliku [LICENSE](LICENSE).
