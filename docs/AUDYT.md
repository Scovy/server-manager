# Audyt techniczny Server Managera

**Data przeglądu:** 23 listopada 2026 r. **Wersja bazowa:** `64b7e7c` na gałęzi `main`.

Panel zarządza kontenerami przez gniazdo Dockera, przechowuje konta i konfigurację w SQLite oraz publikuje usługi przez Caddy. Największe ryzyko dla właściciela serwera powstaje w trzech sytuacjach: przy dostępie do operacji administracyjnych, przy wymianie kontenera backendu oraz przy nieudanym odtwarzaniu kopii.

## Zakres i sposób weryfikacji

Przegląd objął backend FastAPI, klienta React, migracje Alembic, produkcyjny Docker Compose, konfigurację Caddy, skrypt instalacji Azure i CI. Testy uruchomiono na Windowsie w odrębnej kopii projektu. Do prób błędów użyto danych tymczasowych i zasymulowanych odpowiedzi Dockera. Weryfikacja wdrożenia na rzeczywistym linuksowym hoście Docker pozostaje osobnym kryterium odbioru.

| Kontrola wersji bazowej | Wynik |
| --- | --- |
| Backend, Python 3.12 | 71 z 72 testów zakończonych powodzeniem. Test odtworzenia bezpiecznego dowiązania symbolicznego nie przeszedł. Osobna próba utworzenia dowiązania zwróciła Windows 1314, czyli brak uprawnienia procesu. |
| Ruff, Mypy i Alembic | Lint i typy przeszły. Migracja pustej bazy do `head` powiodła się, a `alembic check` potwierdził zgodność modeli ze schematem. |
| Frontend, Node 24 | 9 z 9 testów przeszło. ESLint i build produkcyjny przeszły. Główny plik JavaScript miał ok. 1,53 MB przed kompresją i 450 kB po gzip. |

## Ustalenia i kryteria odbioru

### 1. Krytyczny · autoryzacja panelu administracyjnego

W wersji bazowej React przekierowuje niezalogowaną osobę na ekran logowania. Routery kontenerów, zasobów Dockera, kopii, domen, Marketplace i metryk nie mają odpowiadającej temu kontroli po stronie serwera. Terminal WebSocket otwiera połączenie i przechodzi do klienta Dockera bez ustalenia tożsamości operatora. Zasięg problemu zależy od dostępności adresu panelu w sieci. Obejmuje odczyt konfiguracji i logów, modyfikacje usług oraz dostęp do terminala.

**Odbiór.** Każda operacja zarządzania wymaga praw administratora. Backend odróżnia brak sesji od braku uprawnień. Odmowa następuje przed wywołaniem usługi. Sprawdzenie obejmuje HTTP, logi SSE i oba WebSockety. Zalogowany administrator korzysta z nich także po odświeżeniu tokenu. [Rejestracja routerów](../backend/app/main.py) · [Kontenery](../backend/app/routers/containers.py) · [Uwierzytelnianie](../backend/app/dependencies/auth.py)

### 2. Krytyczny · ponowne uruchomienie konfiguracji początkowej

Kreator ustawia znacznik zakończenia w SQLite, ale w wersji bazowej kolejne żądanie inicjalizacji może ponownie zapisać pliki środowiska i konfigurację Caddy. Pomyłka albo cudza zmiana domeny może odciąć administratora od dotychczasowego adresu panelu.

**Odbiór.** Pierwsza udana inicjalizacja zamyka kreator. Ponowienie oraz dwa równoległe zgłoszenia nie mogą wykonać dwóch zapisów ani dwukrotnie przeładować Caddy. Nieprawidłowa konfiguracja musi pozostawiać możliwość poprawnej pierwszej instalacji. [Kreator](../backend/app/routers/setup.py) · [Zapis konfiguracji](../backend/app/services/setup_service.py)

### 3. Krytyczny · przewidywalny klucz podpisu JWT

Ustawienia mają stały domyślny sekret. Ten sam wzorzec znajduje się w przykładowym pliku środowiska, który instalator Azure kopiuje przy wdrożeniu. Właściciel instancji może zakończyć instalację z kluczem znanym z publicznego kodu. Wtedy podpis JWT przestaje stanowić wiarygodne potwierdzenie tożsamości.

**Odbiór.** Instalator generuje odrębny sekret i zachowuje go przy ponownym uruchomieniu. Backend odrzuca brak klucza i wartość przykładową przed startem. Dokumentacja opisuje konfigurację lokalną i wpływ rotacji na aktywne sesje. [Ustawienia](../backend/app/config.py) · [Instalator Azure](../infra/azure/cloud-init.yaml.tftpl)

### 4. Wysoki · utrata danych po wymianie kontenera

Produkcyjny Compose montuje wolumen w `/app/data`. Przy wartościach z przykładu SQLite, katalogi aplikacji i lokalne archiwa trafiają odpowiednio do `/app/homelab.db`, `/app/apps` i `/app/backups`. Zwykły restart zachowuje warstwę zapisu kontenera. Aktualizacja wymieniająca kontener tworzy nową warstwę. Skrypt Azure kieruje samą bazę na wolumen, więc wpływ na tę bazę różni się od wdrożenia według instrukcji Compose.

**Odbiór.** Po wymianie backendu administrator loguje się dotychczasowym kontem, widzi pliki aplikacji i otwiera wcześniejsze archiwum. Przed wdrożeniem zmiany na istniejącym serwerze należy przenieść dotychczasowe dane i sprawdzić ich kompletność. Sama zmiana adresu bazy może uruchomić panel z pustą bazą. [Compose](../docker-compose.prod.yml) · [Ścieżki backendu](../backend/app/config.py)

### 5. Wysoki · edycja plików innego projektu Compose

Docker zwraca ścieżki widziane przez hosta. Gdy backend nie widzi katalogu wskazanego przez etykietę kontenera, szuka pliku również według samej nazwy. W izolowanej próbie wybranie kontenera z obcego projektu wskazało pliki Compose i środowiska samego panelu. Zapis w edytorze może przez to zmienić niewłaściwą usługę.

**Odbiór.** Powiązać pełną ścieżkę projektu na hoście z konkretnym montowaniem. Przy nieznanej lokalizacji zwrócić czytelny błąd przed udostępnieniem pliku do edycji. Test powinien uwzględniać dwa projekty z identycznymi nazwami plików oraz prawidłowe mapowanie katalogu panelu. [Rozwiązywanie ścieżek](../backend/app/services/docker_service.py)

### 6. Wysoki · niepełna kopia konfiguracji

Kreator korzysta z `SETUP_CONFIG_ROOT=/workspace`, natomiast usługa kopii ustala katalog projektu na podstawie położenia własnego modułu Pythona. W układzie katalogów obrazu daje to inne ścieżki do plików środowiska i Caddy. Eksport pomija brakujące pliki i może zakończyć się sukcesem mimo braku aktywnej konfiguracji proxy.

**Odbiór.** Kreator, eksport i import używają tego samego źródła ścieżek. Test w układzie katalogów identycznym z obrazem sprawdza zawartość archiwum i odtworzenie konfiguracji po zmianie domeny. [Kopie zapasowe](../backend/app/services/backup_service.py) · [Kreator](../backend/app/services/setup_service.py)

### 7. Wysoki · częściowe odtworzenie po błędzie

Import zastępuje bazę, katalog aplikacji i konfigurację przed zakończeniem odtwarzania wolumenów. W próbie na tymczasowej bazie błąd Dockera przerwał operację, lecz odczyt po błędzie wykazał już wartość z archiwum. Użytkownik może zostać ze starą bazą i wolumenami z innego momentu. Duży import jest dodatkowo odczytywany w całości do pamięci procesu.

**Odbiór.** Przed pierwszym zapisem zweryfikować zawartość archiwum, miejsce na dysku i dostępność wolumenów. Wstrzymać równoległe zapisy, zachować punkt powrotu i obsłużyć awarię w środku odtwarzania. Sprawdzić wartości w bazie i na wolumenie po wymuszonym błędzie. Duże archiwum przyjmować strumieniowo. [Import](../backend/app/routers/backup.py) · [Odtwarzanie danych](../backend/app/services/backup_service.py)

### 8. Średni · ponowienie instalacji z Marketplace

Instalacja zapisuje katalog, Compose i plik środowiska przed uruchomieniem usługi. W teście symulującym błąd pobierania obrazu pierwsza próba zostawiła pliki. Druga odmówiła instalacji pod tą samą nazwą. Administrator nie może po prostu ponowić operacji po ustaniu awarii.

**Odbiór.** Rozróżnić instalację zakończoną, przerwaną i konflikt z cudzym projektem. Po błędzie umożliwić bezpieczne wznowienie, również gdy Docker zdążył utworzyć część zasobów. Test nie może usuwać wcześniej istniejącego kontenera ani katalogu użytkownika. [Instalacja](../backend/app/services/marketplace_service.py)

### 9. Średni · alerty zależne od otwartej karty

Ocena progów oraz odstęp między powiadomieniami należą do pojedynczego połączenia WebSocket. Bez otwartego dashboardu przekroczenie progu nie wywoła webhooka. Przy kilku przeglądarkach każde połączenie może powiadomić o tym samym zdarzeniu.

**Odbiór.** Wykonywać ocenę w harmonogramie na serwerze i współdzielić stan powiadomień. Sprawdzić przekroczenie progu bez klientów, z dwiema kartami, po zmianie konfiguracji oraz po powrocie wartości do normy. [Metryki](../backend/app/routers/metrics.py) · [Harmonogram](../backend/app/services/scheduler.py)

### 10. Wysoki · zastosowanie zmian Compose z obrazu backendu

Funkcja „Apply” uruchamia proces `docker compose`. Obraz backendu instaluje bibliotekę Docker SDK dla Pythona, ale nie dostarcza programu CLI i wtyczki Compose wymaganych przez tę ścieżkę. Test z atrapą procesu może przejść mimo niedziałającego przycisku na serwerze.

**Odbiór.** Uruchomić „Apply” z gotowego obrazu na przykładowej usłudze oraz sprawdzić jej stan i rzeczywiście zastosowaną konfigurację. Najpierw zamknąć problem wyboru plików z punktu 5. [Wykonanie polecenia](../backend/app/services/docker_service.py) · [Obraz backendu](../backend/Dockerfile)

## Proponowane rozszerzenia

1. **Dziennik operatora.** Istniejący model `AuditLog` może zapisywać czas, użytkownika, operację, zasób i wynik. Zacząć od zmian konfiguracji, restartów, usuwania zasobów i odtwarzania kopii. Pomijać wartości sekretów i treść sesji terminalowych. [Model dziennika](../backend/app/models/audit_log.py)
2. **Kopie poza hostem.** Dodać harmonogram, retencję oraz próbne odtworzenie do odizolowanego miejsca. Pokazywać osobno czas utworzenia ostatniego archiwum i czas ostatniej udanej próby odzyskania danych.
3. **Test wdrożeniowy w CI.** Na linuksowym runnerze uruchomić gotowe obrazy z Compose, przejść kreator, utworzyć konto i przykładowe dane. Po wymianie backendu potwierdzić logowanie, konfigurację aplikacji i dostępność kopii. [Obecny przebieg CI](../.github/workflows/ci.yml)

## Kolejność prac

Pierwszy etap obejmuje granicę dostępu do API i uruchomienie instancji. Kolejny powinien połączyć trwałe ścieżki z migracją istniejących danych oraz testem odtworzenia. Po zabezpieczeniu edycji właściwego projektu można naprawić „Apply”, ponawianie instalacji i powiadomienia. Powyższe ustalenia opisują wersję bazową. Wyniki kolejnych poprawek należy dopisywać poniżej wraz z wykonanymi testami.

## Stan po pierwszej serii zmian

**23 listopada 2026 r. · zmiany w repozytorium lokalnym**

| Punkt | Wprowadzona zmiana | Wynik sprawdzenia |
| --- | --- | --- |
| 1. API, logi i terminal | Wspólna kontrola roli administratora dla sześciu routerów zarządzania. HTTP i logi SSE przekazują token w nagłówku autoryzacji. Oba WebSockety sprawdzają konto i rolę przed akceptacją połączenia. Klient odnawia wygasły token HTTP i współdzieli jedno odświeżenie między równoległymi żądaniami. | Anonimowe żądania otrzymują 401, a konto z rolą `viewer` otrzymuje 403. Testy obu WebSocketów potwierdzają odrzucenie przed akceptacją. Administrator odczytał metryki przez rzeczywisty WebSocket lokalnego serwera Uvicorn. Testy terminala i logów używają atrapy Dockera. |
| 2. Pierwsza instalacja | Baza rozstrzyga, które żądanie może zapisać konfigurację. Zamknięty kreator zwraca 409 także dla ponownego sprawdzenia konfiguracji. Pierwsze konto można utworzyć po zakończeniu kreatora. Warunek pustej tabeli użytkowników należy do instrukcji zapisu. | Przy dwóch równoległych próbach w osobnych sesjach SQLite tylko jedna zakończyła inicjalizację. Podobna próba dla dwóch nazw kont pozostawiła dokładnie jednego administratora. Ponowienie zakończonego kreatora zachowało treść plików. |
| 3. Klucz podpisu | Backend sprawdza klucz podczas startu. Skrypt instalacyjny generuje go dla nowej instancji, zachowuje skonfigurowany klucz przy ponowieniu i zastępuje wartość przykładową. Instalatory VM i Azure wywołują ten sam skrypt. Pliki środowiska zostały wykluczone z kontekstu budowy obrazu. | Dwie instalacje otrzymały różne klucze. Powtórzenie instalacji zachowało każdy z nich. Test ustawień potwierdził odrzucenie braku klucza i wartości przykładowej. |
| 6. Ścieżki kopii | Eksport i import korzystają z tego samego mechanizmu ustalania ścieżek co kreator, w tym z `SETUP_CONFIG_ROOT`. Format archiwum pozostał zgodny z wcześniejszymi kopiami. | Test zmienił treść pięciu plików po eksporcie i odtworzył wszystkie z archiwum w tymczasowym katalogu montowania. Starsze archiwum pozwoli odzyskać tylko pliki, które rzeczywiście zawiera. |

**Kontrakt dla klientów API.** Żądania administracyjne, w tym SSE, używają `Authorization: Bearer <access_token>`. Przeglądarka oferuje dla WebSocket dwa elementy listy subprotokołów: `homelab.v1` i aktualny token dostępu. Serwer negocjuje wyłącznie `homelab.v1`. Przy konfiguracji logowania reverse proxy należy traktować nagłówek negocjacji jako zawierający dane uwierzytelniające. Pierwsza instalacja zakłada kontrolę operatora nad dostępem sieciowym do kreatora do chwili utworzenia konta.

**Weryfikacja zmian.** Backend przeszedł 86 z 87 testów. Pozostał ten sam błąd odtwarzania dowiązania na Windowsie co w wersji bazowej. Frontend przeszedł 12 z 12 testów, ESLint, kompilację TypeScript i build Vite. Ruff i Mypy zakończyły się powodzeniem. Na osobnej tymczasowej bazie wykonano migracje Alembic, sprawdzenie schematu i próbę sieciową obejmującą utworzenie administratora, odświeżenie sesji, odczyt katalogu Marketplace i strumień metryk. Pełny test gotowych obrazów razem z Docker Engine i Caddy pozostaje do wykonania.

**Otwarte po pierwszej serii.** Najwyższy priorytet mają punkty 4, 5 i 7: przeniesienie istniejących danych na trwały wolumen, jednoznaczne powiązanie edytora z projektem oraz możliwość powrotu po błędzie odtwarzania. Otwarte są również punkty 8–10 i trzy propozycje rozszerzeń. Przed wymianą istniejącego kontenera trzeba zabezpieczyć jego lokalne dane i przygotować plik środowiska zgodnie z [instrukcją uruchomienia](../README.md).

## Punkt wznowienia po drugiej serii zmian

**23 listopada 2026 r.** Prace zatrzymały się po dodaniu czterech testów regresji. Najważniejszy otwarty przypadek dotyczy awarii w połowie odtwarzania kopii. Zmiany są w lokalnym katalogu roboczym na gałęzi `main`, której ostatni commit to `64b7e7c`. Obie serie poprawek czekają na commit i wdrożenie. Tego samego dnia wykonano w dystrybucji WSL `HomelabTest-3b847fce6b`, w obrazie `homelab-tests`, pełny zestaw testów oraz próby awarii odtwarzania na rzeczywistym Dockerze; potwierdzone wyniki dopisano poniżej.

| Punkt audytu | Co już zrobiono i sprawdzono | Co pozostało do sprawdzenia lub poprawy |
| --- | --- | --- |
| 4. Trwałość danych | Na testowym Dockerze przeniesiono bazę SQLite, pliki aplikacji i archiwum ze starego kontenera do nazwanego wolumenu. Nowy obraz odczytał wszystkie trzy. Ponowne uruchomienie migracji zachowało dane. Pełną aktualizację wykonano zgodnie z instrukcją z README: przez lokalny Caddy przechodzono kreator, utworzono konto, zalogowano się i wykonano eksport; po zatrzymaniu starego backendu i Watchtowera uruchomiono skrypt migracji i podmieniono obraz na zbudowany lokalnie. Po wymianie zalogowano się istniejącym kontem i panel pokazał listę archiwów. Sumę kontrolną przedaktualizacyjnego archiwum porównano bezpośrednio na wolumenie, bo jego pobranie przez HTTP nie istnieje (brak endpointu); eksport wykonany po aktualizacji sprawdzono. Pliki aplikacji pozostały na miejscu. Skrypt migracji odrzucił konflikt danych bez zmian, powtórne uruchomienie przeszło idempotentnie, a w symulacji wariantu Azure, z bazą już leżącą na wolumenie, jej suma kontrolna pozostała niezmieniona. | Pełny rollback do stanu przed aktualizacją oraz wariant chmurowy z obrazem z rejestru (GHCR) pozostają niesprawdzone; próba użyła obrazu zbudowanego lokalnie. |
| 5 i 10. Wybór projektu i przycisk „Apply” | Z gotowego obrazu backendu zastosowano zmianę w jednym z dwóch projektów o identycznych nazwach plików Compose. Wybrany kontener otrzymał nową wartość zmiennej i zachował właściwy katalog hosta przy montowaniu względnym. Edytor odmówił dostępu do pliku projektu poza widocznym katalogiem. Potwierdzono edycję `.env` aplikacji z Marketplace: `update_env` przed zapisem bezpiecznie przełącza zgodną parę starego wygenerowanego pliku Compose z wartościami inline oraz `.env` na odwołanie `env_file` w trybie raw, a „Apply” wczytuje zapisaną wartość, również dosłowne `$`, i nie modyfikuje pliku Compose. Własne pliki Compose użytkownika nie są przepisywane. W obsłudze starszych instalacji po błędzie usuwany jest tylko kontener zastępczy o potwierdzonej tożsamości projektu i usługi: obcy kontener pozostaje zachowany, stary wraca na swoje miejsce, a przy zajętej nazwie — pod nazwą zapasową. | Ręcznie zmienione wartości inline nie są nadpisywane: przy rozbieżności pliku Compose i `.env` edytor odmawia i podaje przepis ręcznego dostosowania. Tryb raw wymaga Docker Compose w wersji 2.29 lub nowszej. |
| 7. Odtwarzanie po błędzie | W kodzie są strumieniowy odbiór archiwum, weryfikacja sum kontrolnych, blokada równoległych operacji i zapis stanu do wycofania zmian. Dodano test odtwarzania z symulowanym błędem wolumenu. Błąd zapisu wymuszono także na rzeczywistym Dockerze: na osobnym daemonie w testowej dystrybucji WSL, na dwóch izolowanych wolumenach nazwanych, po rozpoczęciu zapisu drugiego wolumenu import przerwał błąd ENOSPC (tmpfs). Próba ENOSPC potwierdziła pełne wycofanie zmian: baza SQLite, pliki aplikacji, pięć plików konfiguracji i oba wolumeny wróciły do stanu sprzed importu, oba zależne kontenery wznowiły pracę i odpowiadały, a kontenery pomocnicze i katalog tymczasowy `.restore-*` zostały usunięte. | Rozstrzygnąć przypadek nagłego przerwania procesu, opisany w akapicie poniżej: kod nie ma mechanizmu automatycznego odzyskania przy starcie, a ręcznego użycia zachowanych kopii nie przetestowano. |
| 8. Ponowienie instalacji Marketplace | Kod zapisuje identyfikator rozpoczętej instalacji i blokuje równoległą instalację pod tą samą nazwą. Dodano test ponowienia i zachowania cudzych plików; przeszedł on w pełnych zestawach (91/91, po poprawkach 99/99). Potwierdzono na rzeczywistym Dockerze: instalację Compose przerwano po częściowym utworzeniu zasobów, jeszcze bez wiersza w bazie, a ponowienie przez API zwróciło 200 — dokładnie jeden nowy rekord, a kontener zachował swój poprzedni identyfikator, działająca aplikacja, obce kontenery nietknięte. | Jawne ograniczenie: dla częściowej instalacji, której kontener utworzyła jeszcze ścieżka Docker SDK, ponowienie po przełączeniu na Compose CLI nie działa — kolizja nazwy kontenera, retry niczego nie usuwa. |
| 9. Alerty metryk | Ocena progów została przeniesiona z połączeń WebSocket do harmonogramu backendu. Dodano test ponowienia po błędzie webhooka, powrotu metryki do normy i zmiany konfiguracji. Potwierdzono w próbie na świeżym obrazie backendu z ówczesnego drzewa: progi oceniał prawdziwy harmonogram APScheduler co 60 s, a powiadomienie szło przez rzeczywisty lokalny serwer HTTP. Przy stabilnych progach syntetycznych w siedmiu tickach wysłano dokładnie jeden POST — zarówno przy zerowej liczbie klientów, jak i przy dwóch prawdziwych kartach połączonych dwoma Websocketami przez Caddy. | Rzeczywisty zewnętrzny webhook oraz powtórka dostawy po nieudanej próbie (retry E2E) pozostają niesprawdzone; odbiorcą w próbie był serwer lokalny. |

**Nagłe przerwanie odtwarzania.** W osobnej próbie, na tym samym daemonie, proces backendu przerwano sygnałem SIGKILL w chwili rozpoczęcia zapisu drugiego wolumenu. Bezpośrednio po zabiciu procesu stan był częściowo zmieniony: drugi wolumen był wyczyszczony, a oba zależne kontenery pozostały wstrzymane. Katalog `.restore-*` z plikiem `recovery.json`, kopiami plików i snapshotami wolumenów przetrwał. Harness potwierdził ten stan bez przeprowadzania restartu właściwego backendu. Kod nie ma mechanizmu automatycznego odzyskania przy starcie; ręcznego postępowania z zachowanymi kopiami nie przetestowano. Przypadek pozostaje otwarty i jest istotny przed wydaniem.

**Od czego wznowić.** Pierwsze potwierdzenia po drugiej serii: w dystrybucji WSL `HomelabTest-3b847fce6b`, w obrazie `homelab-tests`, wszystkie cztery nowe [testy regresji](../backend/tests/test_repair_regressions.py) przeszły (4/4), a pełny zestaw backendu zakończył się wynikiem 91/91 — wcześniejszy wynik 87/87 dotyczył stanu sprzed dodania tych testów. Po poprawkach Marketplace i review niezależnie potwierdzono aktualny backend w tym samym obrazie, z odciętą siecią (`--network none`): wynik 99/99. Ostatni potwierdzony wynik frontendu to 12/12, wraz z ESLint i buildem produkcyjnym. Próbę awarii drugiego wolumenu z błędem ENOSPC wykonano na rzeczywistym Dockerze z pełnym wycofaniem zmian (wiersz 7). Testy awaryjnego wyboru pliku Compose oraz preflight HTTPS kreatora uodporniono na zmienną obrazu `HOMELAB_DATA_MOUNT` i na repozytorium zamontowane tylko do odczytu. Kolejne próby potwierdziły pełną aktualizację przez lokalny Caddy (wiersz 4), alerty z prawdziwym harmonogramem i dwiema kartami przeglądarki (wiersz 9) oraz ponowienie instalacji Marketplace na rzeczywistym Dockerze (wiersz 8). Najważniejszym otwartym przypadkiem przed wydaniem pozostaje nagłe przerwanie odtwarzania (SIGKILL, akapit powyżej); poza nim zostały jawne ograniczenia z tabeli: pełny rollback i obraz z rejestru (wiersz 4), ręczne dostosowanie rozbieżnych wartości inline i wymagany Compose 2.29+ (wiersz 5 i 10), ponowienie po przełączeniu SDK→CLI (wiersz 8) oraz zewnętrzny webhook (wiersz 9).

**Przed wydaniem.** Kreator, utworzenie konta, kopię, wymianę backendu i ponowne logowanie potwierdziła lokalna próba aktualizacji przez Caddy (wiersz 4); wariant chmurowy z obrazem z rejestru pozostaje niesprawdzony. Instrukcja aktualizacji istniejącej instalacji znajduje się w README, a kontrole jakości potwierdzono ponownie: aktualny backend 99/99, frontend 12/12, ESLint i build przeszły. Do prób przygotowano osobną dystrybucję WSL `HomelabTest-3b847fce6b`. W chwili zapisania pierwotnej notatki była zatrzymana; później tego samego dnia uruchomiono ją do pełnego zestawu testów oraz prób awarii odtwarzania na rzeczywistym Dockerze. Dystrybucja pozostaje w użyciu — działa na niej lokalny panel użytkownika i nie jest planowane jej usunięcie; ewentualne posprzątanie po zakończeniu pracy nastąpi tylko za zgodą. Najważniejszym otwartym przypadkiem przed wydaniem pozostaje nagłe przerwanie odtwarzania (SIGKILL). Dziennik operatora i kopie poza hostem pozostają propozycjami rozwoju.
