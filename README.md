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
   python ../scripts/init-backend-env.py
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
   
   # Utworzenie backend/.env z indywidualnym kluczem podpisu JWT
   python3 scripts/init-backend-env.py
   ```
   Przy aktualizacji wykonaj ten sam skrypt przed wymianą backendu. Zachowuje skonfigurowany klucz i zastępuje pustą lub przykładową wartość. Zmiana klucza wymaga ponownego zalogowania na wszystkich urządzeniach. Przed wymianą kontenera zabezpiecz bazę, katalog aplikacji i archiwa zapisane w jego warstwie lokalnej. Pierwszą konfigurację i utworzenie konta administratora wykonaj z kontrolowanej sieci przed udostępnieniem panelu. [Audyt i opis ścieżek danych](docs/AUDYT.md)

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

### Aktualizacja istniejącej instalacji do obrazu z tagiem `persistent-v1`

Starsze instalacje trzymają bazę SQLite, katalog aplikacji Marketplace i archiwa w warstwie zapisu kontenera, mimo że produkcyjny Compose montuje wolumen w `/app/data`. Skrypt [scripts/migrate-backend-data.sh](scripts/migrate-backend-data.sh) przenosi te trzy elementy do istniejącego wolumenu przed wymianą kontenera. Zweryfikowana kolejność kroków dla instalacji Compose (Caddy i frontend działają w trakcie prac, panel bywa chwilowo niedostępny):

1. Zatrzymaj Watchtower, aby nie odtwarzał kontenerów w trakcie prac:
   ```bash
   docker compose -f docker-compose.prod.yml stop watchtower
   ```
2. Zatrzymaj backend — `stop` zachowuje kontener i jego warstwę z danymi (nie używaj `down`):
   ```bash
   docker compose -f docker-compose.prod.yml stop backend
   ```
3. Zabezpiecz punkt powrotu. Skrypt migracji w kroku 4 korzysta ze zatrzymanego kontenera, natomiast krok 5 (`up -d` na nowym obrazie) odtworzy backend i usunie stary kontener razem z jego warstwą zapisu — dlatego zrób kopie teraz, przed migracją. Archiwa i kopia bazy zawierają sekrety (hasła, `JWT_SECRET` w plikach `.env`, środowisko kontenera), więc nie zapisuj ich w katalogu projektu ani z prawami 0644 — użyj świeżego katalogu prywatnego poza repo, tworzonego przez `mktemp -d` z uprawnieniami 0700, oraz `umask 077`, żeby pliki powstawały z prawami 0600:
   ```bash
   set -o pipefail
   umask 077
   KATALOG=$(mktemp -d "${HOME}/homelab-rollback-XXXXXX")
   docker commit homelab_backend homelab-backend-rollback:przed-migracja
   docker export homelab_backend | gzip > "$KATALOG/homelab_backend-warstwa.tar.gz"
   VOL=$(docker inspect -f '{{range .Mounts}}{{if and (eq .Type "volume") (eq .Destination "/app/data")}}{{.Name}}{{end}}{{end}}' homelab_backend)
   [ -n "$VOL" ] || { echo "Nie znaleziono wolumenu w /app/data" >&2; exit 1; }
   docker run --rm -v "$VOL":/src:ro alpine tar cz -C /src . > "$KATALOG/backend_data.tar.gz"
   tar czf "$KATALOG/konfiguracja-hosta.tar.gz" .env backend/.env caddy
   chmod -R go-rwx "$KATALOG"
   echo "Kopie w: $KATALOG (wolumen: $VOL)"
   ```
   Do kroku 4 przechodź tylko, gdy cały blok przeszedł bez błędu — `set -o pipefail` sprawia, że zerwany potok `docker export | gzip` nie ujdzie jako sukces (alternatywa bez potoku: `docker export -o plik`). Polecenia kopiują pliki, nie wypisując ich zawartości, więc sekrety nie trafiają do konsoli. `docker commit` tworzy obraz uruchamialny z warstwą zapisu kontenera (w próbie odczytano z niego dane sprzed migracji i uruchomiono powłokę) i obejmuje także zmienne środowiskowe kontenera — nigdy nie publikuj obrazu `homelab-backend-rollback:przed-migracja` w rejestrze. `docker export` to tylko archiwum plików systemu kontenera — **nie jest obrazem**; jego użycie wymaga `docker import` i odtworzenia konfiguracji kontenera. Żadne z nich nie obejmuje zamontowanego wolumenu `/app/data` ani konfiguracji hosta (`.env`, `backend/.env`, katalog `caddy/`) — stąd osobne kopie `backend_data.tar.gz` i `konfiguracja-hosta.tar.gz`. Kopię wolumenu wykonuj zawsze przed migracją — w instalacji Azure baza leży wyłącznie na wolumenie. Pełny powrót z tych artefaktów — podobnie jak powyższe polecenia kopii wolumenu i konfiguracji hosta — pozostaje instrukcją ręczną, nieobjętą próbą (w próbie weryfikowano `commit`, `export` i treść warstwy); jeśli planujesz z niego korzystać, przećwicz go na kopii środowiska przed rzeczywistą wymianą.
4. Przenieś dane do wolumenu:
   ```bash
   bash scripts/migrate-backend-data.sh homelab_backend
   ```
   Wymagania skryptu: zatrzymany backend, nazwany wolumen zamontowany w `/app/data`, standardowa ścieżka bazy (`sqlite+aiosqlite:///./homelab.db`, `.../data/homelab.db` lub `/app/homelab.db`) oraz domyślne `MARKETPLACE_APPS_DIR`/`BACKUP_DIR`, Python w obrazie starego backendu. Instalacje z Azure (cloud-init ustawia `DATABASE_URL=sqlite+aiosqlite:///./data/homelab.db`) mają bazę już na wolumenie — skrypt wtedy weryfikuje ją w miejscu i przenosi tylko aplikacje oraz archiwa. Skrypt odmawia pracy i nie zmienia wolumenu, gdy: backend działa, brakuje wolumenu w `/app/data`, występują własne ścieżki lub dane na wolumenie różnią się od przenoszonych. Uruchomiony ponownie z tymi samymi danymi nie zmienia nic (idempotentny).
5. Przygotuj obraz backendu i wymień kontener — wybierz dokładnie jedną ścieżkę; nie maskuj nieudanego pobierania lokalnym budowaniem:
   - Publikowany obraz (domyślna instalacja): pobierz tag wskazany w kompozycji produkcyjnej; jeśli `pull` zgłosi błąd, przerwij pracę i wyjaśnij przyczynę przed wymianą kontenera:
     ```bash
     docker compose -f docker-compose.prod.yml pull backend
     docker compose -f docker-compose.prod.yml up -d backend
     ```
   - Lokalny build z bieżącego kodu (to nie jest publikowany obraz — używaj świadomie): zbuduj, a przy odtwarzaniu wyłącz pobieranie z rejestru, aby wynik budowania nie został zastąpiony tagiem z rejestru:
     ```bash
     docker compose -f docker-compose.prod.yml build backend
     docker compose -f docker-compose.prod.yml up -d --pull never backend
     ```
6. Zweryfikuj przez przeglądarkę (adres panelu): logowanie dotychczasowym kontem, lista aplikacji Marketplace z plikami aplikacji oraz lista archiwów z kopią sprzed wymiany; pobierz nową kopię i sprawdź jej zawartość. Jeśli zachowano dotychczasowy `JWT_SECRET` w `backend/.env` (skrypt `scripts/init-backend-env.py` go nie zmienia), aktywne sesje i tokeny pozostają ważne.
7. Wznów Watchtower dopiero po pomyślnej weryfikacji z kroku 6 i tylko wtedy, gdy obrazy kontenerów obserwowanych przez Watchtower istnieją w obserwowanym rejestrze (jego `command` wskazuje nazwy kontenerów) — dla tagów dostępnych tylko lokalnie Watchtower co cykl bezskutecznie próbuje pobrać obraz z rejestru i pozostawia kontenery bez zmian (zaobserwowano w próbie):
   ```bash
   docker compose -f docker-compose.prod.yml start watchtower
   ```

Po potwierdzeniu stabilności usuń artefakty punktu powrotu z kroku 3 (prywatny katalog `$KATALOG` z archiwami oraz lokalny obraz `homelab-backend-rollback:przed-migracja`). Sama zmiana adresu bazy bez przeniesienia danych uruchomi panel z pustą bazą — nie zmieniaj `DATABASE_URL` ręcznie przed migracją. Kolejność kroków 1–4 i 6 oraz wymianę kontenera sprawdzono na izolowanej instalacji testowej z lokalnie zbudowanym obrazem; pobrania obrazu z `ghcr.io`, publikacji ani pełnego powrotu z artefaktów nie objęła próba.

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
