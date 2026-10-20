# Plan: Ryciny jako dodatek do Home Assistant (HA OS)

Cel: mikrofon wpięty do komputera z Home Assistant zbiera dźwięki 24/7, a telefon, tablet czy później
ekran e-ink tylko wyświetla ryciny. Wszystko, co dziś robi aplikacja na Androida (ptaki, psy, 34 dźwięki,
samoloty, pociągi, generowanie rycin), przenosi się do jednego dodatku HA. Aplikacja dostaje tryb „tylko ekran”.

**Stan (0.27.0):** zrobione kroki 1–5 i 7: dodatek (nasłuch, rozpoznawanie, samoloty, pociągi, ryciny, Dziennik,
API, panel w HA, `/api/plate.png`) oraz tryb „Home Assistant” w aplikacji. Zostało: encje i zdarzenia w HA (krok 6)
i obsługa ramek e-ink (krok 8). Na prawdziwym HA OS z mikrofonem jeszcze nie testowane (czeka na mikrofon).

## Sprzęt

- Komputer z **HA OS**: Raspberry Pi 4/5, NUC albo maszyna wirtualna. BirdNET FP32 liczy 3 s nagrania
  w ok. 0,3–0,6 s na Pi 4, więc zapas jest duży.
- **Karta dźwiękowa USB z wejściem mikrofonowym** (np. UGREEN, ok. 40 zł). Daje zasilanie, którego potrzebuje
  mikrofon elektretowy (EM272, smartLav+ przez przejściówkę TRRS → TRS).
- Mikrofon za oknem, w osłonie od wiatru, na krótkim kablu. Jeśli HA stoi daleko, karta dźwiękowa leży przy oknie,
  a do komputera idzie przedłużacz USB (cyfrowo, bez szumu). Szczegóły w [docs/sprzet.md](docs/sprzet.md).

## Architektura

```
mikrofon ─ karta USB ─ HA OS ─ dodatek „Ryciny” (Docker, Python)
                                 ├─ nasłuch: PulseAudio z Supervisora, 48 kHz, okna 3 s
                                 ├─ BirdNET 6K v2.4 + filtr zasięgu   (te same .tflite co w APK)
                                 ├─ YAMNet: psy, 34 dźwięki, silniki  (shared/sounds.json)
                                 ├─ samoloty: adsb.lol + adsbdb        (co 10 s)
                                 ├─ pociągi: GTFS mkuran.pl            (raz dziennie)
                                 ├─ ryciny: fugleramme + OpenAI/Gemini/OpenRouter, wycinanie z tła
                                 ├─ /data: journal.json, art/, clips/, settings.json
                                 ├─ HTTP API (ingress + port w LAN) ──► aplikacja na Androida w trybie „tylko ekran”
                                 ├─ strona WWW z ryciną (ingress)  ──► panel w HA, przeglądarka, później e-ink
                                 └─ zdarzenia do HA (MQTT albo REST) ─► automatyzacje
```

Jeden dodatek zamiast BirdNET-Go i osobnej usługi. Mikrofon czyta jeden proces, wszystkie modele dostają
to samo okno 3 s, a Dziennik ma jeden format. BirdNET-Go zostaje alternatywą, gdyby był potrzebny jego panel WWW.

## Dodatek

Repozytorium dodatków w tym samym repo, żeby w HA wystarczyło dodać adres `https://github.com/qunabu/ryciny`:

```
repository.yaml                 nazwa repozytorium dodatków
homeassistant/ryciny/
  config.yaml                   audio: true, ingress: true, ports: 8099, map: share, options (klucze API, miejsce)
  Dockerfile                    obraz bazowy HA (Python 3.12) + ai-edge-litert, numpy, soundfile
  run.sh
  app/
    main.py                     start: nasłuch, pętle samolotów i pociągów, serwer HTTP
    audio.py                    PulseAudio → okna 3 s (port ListenService)
    analyzer.py                 BirdNET + YAMNet, minHits, pomijanie (port Analyzer.kt)
    dsp.py                      decymacja 48→16 kHz, wysokość szczekania, WAV (port Dsp.kt)
    store.py                    journal.json, ten sam schemat co Journal w Store.kt
    sky.py                      adsb.lol, adsbdb, onRoute (port Sky.kt)
    rails.py                    GTFS → przejazdy obok domu (port Timetable.kt + Rails.kt)
    art.py                      fugleramme, generatory, cache, wycinanie z tła (port Art.kt + Cutout.kt)
    api.py                      HTTP API + strona WWW
    ha.py                       zdarzenia do Home Assistant
  models/                       birdnet.tflite, birdnet_meta.tflite, yamnet.tflite, etykiety (z android/…/assets)
shared/                         style.json, sounds.json, dog_breeds.json, aircraft_types.json (bez zmian)
```

Opcje dodatku w UI Home Assistant: dostawca rycin i klucz (OpenAI, Gemini, OpenRouter), szerokość i długość
geograficzna (domyślnie z konfiguracji HA), promień samolotów, progi. Klucze trafiają do `options.json` dodatku,
nie do repo.

## API (dla aplikacji i strony)

| Metoda | Ścieżka | Co robi |
| --- | --- | --- |
| GET | `/api/journal?since=…` | Dziennik (ptaki, szczekania, psy, samoloty, dźwięki), ten sam JSON co w aplikacji |
| GET | `/api/live` | stan na żywo: czy słucha, co słychać, samolot nad głową (SSE albo odpytywanie co kilka s) |
| GET | `/api/art/{kind}/{key}.png` | rycina; jeśli jej nie ma, zamawia generowanie i zwraca 202 |
| GET | `/api/clips/{id}.wav` | nagranie szczekania do odsłuchu |
| POST | `/api/barks/{id}/tag` | „Kto to?”: przypisanie szczekania do psa, nowego albo znanego |
| PUT | `/api/dogs/{id}` | edycja i usuwanie psa |
| GET/PUT | `/api/settings` | przełączniki dźwięków, tylko słyszane samoloty, progi |
| POST | `/api/import` | wczytanie ZIP-a z eksportu aplikacji (ryciny, psy z próbkami, Dziennik) |

W sieci domowej bez logowania, przez ingress za logowaniem HA. Dostęp z zewnątrz: przez Nabu Casa albo VPN.

## Home Assistant

- Encje: `sensor.ryciny_ostatni_ptak`, `sensor.ryciny_samolot`, `sensor.ryciny_pociag` (z trasą w atrybutach),
  `binary_sensor.ryciny_szczekanie`, `event.ryciny_dzwiek` (typ: kosiarka, burza, karetka…).
- Przez MQTT (dodatek Mosquitto, autodiscovery) albo, bez MQTT, przez REST API Supervisora tokenem dodatku.
- Przykładowe automatyzacje do README: powiadomienie „przejeżdża PolRegio do Somonina”, zamknięcie okien przy
  burzy, światło w ogrodzie, gdy szczeka nieznany pies w nocy.

## Aplikacja na Androida: tryb „tylko ekran”

- Ustawienia → „Źródło”: **ten telefon** (jak dziś) albo **serwer Home Assistant** (adres, np. `http://homeassistant.local:8099`).
- W trybie serwera usługa nasłuchu się nie uruchamia, mikrofon nie jest potrzebny.
  - `Store` → `RemoteStore`: odpytuje `/api/journal`.
  - `Art` → pobiera ryciny z `/api/art`.
  - „Kto to?” i edycja psów idą do serwera.
- Rycina, Dziennik i Ustawienia wyglądają tak samo, bo zmienia się tylko źródło danych.
- Tablet przy ścianie w trybie ramki („Nie wygaszaj ekranu”) staje się samym ekranem.

## Ekran e-ink

Kolorowy e-ink z panelem E Ink Spectra 6, ten sam co w Inky Impression. W Polsce kupisz go jako Waveshare z HAT
(7,3" 800×480 za ok. 385 zł, 13,3" 1600×1200 za ok. 1320 zł); szczegóły w [docs/sprzet.md](docs/sprzet.md).

- **Gdzie działa:** HAT nakłada się na złącze GPIO Raspberry Pi. Jeśli HA działa na Raspberry Pi przy ramce, ekran
  może obsługiwać sam dodatek (dostęp do SPI i GPIO w `config.yaml`: `gpio: true`, `devices: /dev/spidev0.0`).
  Częściej HA stoi gdzie indziej, a przy ramce pracuje osobne Raspberry Pi Zero 2 W z małym programem `frame`.
- **Program `frame`:** co kilka minut pobiera z dodatku gotową grafikę `GET /api/plate.png?w=800&h=480`
  i wysyła ją na panel. Odświeża tylko przy zmianie, bo pełne odświeżenie Spectra 6 trwa 12–28 s i miga.
- **Rysowanie po stronie dodatku:** `/api/plate.png` składa jedną rycinę (jak ekran Rycina w aplikacji) na papierze,
  w rozmiarze panelu, z dithering do 6 kolorów panelu, czyli to samo, co robi `render/dither.py` w fugleramme.
  Ten sam obraz pokazuje strona WWW, więc wygląd sprawdzisz w przeglądarce bez ekranu.
- **Sterownik:** biblioteka Waveshare (`waveshare_epd`, model `epd7in3e` albo `epd13in3e`) zamiast Pimoroni `inky`.
  Mały interfejs `Panel.show(image)`, żeby obsłużyć oba (Inky też zadziała, gdyby kiedyś trafił się Pimoroni).

## Urządzenie ramki

Ramka ma jedno zadanie: pobrać gotowy obraz z dodatku w Home Assistant przez sieć lokalną i pokazać go na ekranie.
Całe rysowanie, dithering i decyzja „czy coś się zmieniło” dzieje się w dodatku, więc ramka może być bardzo prosta.

**Umowa z dodatkiem** (taka sama dla każdego urządzenia):

- `GET /api/plate.png?w=800&h=480&palette=spectra6`: rycina w rozmiarze panelu, już po ditheringu do kolorów panelu,
  gotowa do wysłania 1:1. Inne palety: `bw` (czarno-biały e-ink), `full` (zwykły ekran).
- Nagłówek `ETag`: ramka wysyła `If-None-Match` i dostaje `304 Not Modified`, gdy nic się nie zmieniło, więc nie
  odświeża panelu (pełne odświeżenie Spectra 6 trwa 12–28 s i miga) i nie zużywa baterii na pobieranie.
- Adres w sieci domowej, np. `http://homeassistant.local:8099/api/plate.png`, bez logowania (tylko LAN).

**Urządzenia, od najprostszego dla Home Assistant:**

| Urządzenie | Ekran | Cena (X 2026) | Jak działa | Plusy | Minusy |
| --- | --- | --- | --- | --- | --- |
| **Seeed reTerminal E1002** | wbudowany 7,3" Spectra 6, 800×480 | ok. 94 USD na AliExpress | ESP32-S3 z firmware ESPHome: `online_image` pobiera `/api/plate.png`, `epaper_spi` wyświetla, potem głęboki sen | gotowa ramka w obudowie, bez lutowania i bez Raspberry Pi; bateria 2000 mAh na tygodnie; widoczna w HA jako urządzenie ESPHome | tylko 7,3"; obsługa Spectra 6 w ESPHome jest nowa (zgłaszane błędy, np. [#12322](https://github.com/esphome/esphome/issues/12322)) |
| **Raspberry Pi Zero 2 W + Waveshare HAT** | 7,3" albo 13,3" Spectra 6 | Pi ok. 80–100 zł + ekran 385 / 1320 zł | Linux, mały program `frame` w Pythonie: pobiera PNG, sterownik `waveshare_epd` wysyła na panel | obsługuje każdy rozmiar, także 13,3" jak fugleramme; pełna kontrola, łatwe debugowanie | zasilanie z sieci (nie na baterii), karta microSD do przygotowania |
| **ESP32 + płytka Waveshare e-Paper Driver Board + panel** | 7,3" Spectra 6 (sam panel) | płytka ok. 50–70 zł + panel ok. 280 zł | ESPHome jak w reTerminal, tylko złożone samemu | tanio, na baterii | składanie, obudowa do zrobienia, dla 13,3" nie polecam (mało RAM-u na 1600×1200) |
| **Stary tablet albo telefon z Androidem** | LCD | 0 zł, jeśli leży w szufladzie | aplikacja Ryciny w trybie „tylko ekran” albo przeglądarka w trybie kiosku na stronie dodatku | od razu, kolorowo, z animacją | to nie e-ink: świeci, zużywa prąd, mniej „jak obraz” |
| **Pimoroni Inky Frame 7,3"** | wbudowany 7,3" | ok. 400–500 zł | Raspberry Pi Pico W z MicroPythonem: pobiera PNG i wyświetla | gotowa ramka, na baterii | mniej związana z HA niż ESPHome; starszy panel 7-kolorowy w części wersji |
| **Cokolwiek z przeglądarką** (telewizor, stary laptop, Echo Show) | dowolny | 0 zł | strona `/plate` dodatku na pełnym ekranie | zero pracy | nie e-ink |

**Gotowe ramki, którym Home Assistant wysyła obraz przez sieć lokalną (bez składania):**

| Ramka | Ekran | Cena | Jak dostaje obraz | Uwagi |
| --- | --- | --- | --- | --- |
| [BLOOMIN8 EinkCanvas](https://bloomin8.com/products/bloomin8-eink-canvas) | 13,3" Spectra 6 | ok. 499 USD | oficjalna integracja z HA i lokalne REST API; dodatek wysyła `/api/plate.png` automatyzacją | najbliżej „po prostu ramki”; bateria, karta SD; drogo, ale 13,3" jak fugleramme |
| [paperlesspaper OpenPaper L](https://linuxiac.com/openpaper-l-launches-as-a-13-3-inch-open-source-color-e-ink-frame/) | 13,3" kolor | sprawdzić | opcjonalny firmware offline: obraz przez Bluetooth albo z lokalnego URL-a; [integracja HA](https://github.com/djiwondee/paperlesspaper-ha) z akcją `upload_image` | otwarty projekt z Niemiec, otwarte API |
| [Waveshare ESP32-S3 PhotoPainter](https://www.waveshare.com/wiki/ESP32-S3-PhotoPainter) | 7,3" Spectra 6 | ok. 60–90 USD | fabrycznie: strona WWW na ramce, upload przez Wi-Fi (gotowa, zditherowana BMP); z firmware społeczności: sama pobiera obraz z URL-a | tania gotowa ramka w drewnianej oprawie; przyda się `palette=spectra6` i format BMP z dodatku |
| Seeed reTerminal E1002 | 7,3" Spectra 6 | ok. 94 USD | ESPHome (`online_image`), sama pobiera z dodatku | opisana wyżej |
| TRMNL (z własnym, lokalnym serwerem) | 7,5", tylko odcienie szarości | ok. 140 USD | lokalny serwer zgodny z API TRMNL albo webhook z HA | dobra do tekstu i dashboardów, ale bez kolorów, więc nie dla rycin |

**Samsung The Frame (Art Mode):** też działa, lokalnie, bez chmury. Integracje HACS, np.
[ha-samsungtv-smart](https://github.com/TheFab21/ha-samsungtv-smart) albo
[Samsung Frame Art Director](https://github.com/janstrm/Home-Assistant-Samsung-Frame-Art-Director-Integration),
wysyłają obraz przez lokalne API telewizora (biblioteka `samsungtvws`) i ustawiają go w Art Mode. Dodatek daje wtedy
`/api/plate.jpg?w=3840&h=2160&palette=full`: pełne kolory, 16:9, JPEG do 1,9 MB (limit telewizora), na papierze,
bez ditheringu. Automatyzacja w HA wysyła go tylko przy zmianie ryciny (nie częściej niż co kilkanaście minut)
i kasuje poprzednią rycinę z pamięci telewizora, żeby jej nie zapchać. Przy pierwszym parowaniu trzeba zaakceptować
dostęp pilotem; adres IP telewizora warto zarezerwować w routerze.

Wszystkie poza TRMNL biorą ten sam obraz z `/api/plate.png`. Różni się tylko to, kto inicjuje przesłanie:
ramka pobiera sama (reTerminal, PhotoPainter z nowym firmware) albo automatyzacja w HA wypycha obraz przy zmianie ryciny
(BLOOMIN8, paperlesspaper). Dla tej drugiej grupy dodatek wystawia zdarzenie „rycina się zmieniła”, a automatyzacja
wywołuje akcję integracji z adresem obrazu.

**Rekomendacja:**
- **13,3" bez składania:** BLOOMIN8 EinkCanvas (oficjalna integracja HA) albo paperlesspaper OpenPaper L.
- **7,3" tanio, bez składania:** Waveshare ESP32-S3 PhotoPainter albo Seeed reTerminal E1002.
- **7,3" najbliżej HA:** Seeed reTerminal E1002. Najprostsza i najtańsza kolorowa ramka e-ink, natywnie w Home Assistant przez ESPHome,
  bez Raspberry Pi. Zanim kupisz, sprawdź aktualny stan obsługi Spectra 6 w ESPHome (`epaper_spi`).
- **13,3" jak fugleramme:** Raspberry Pi Zero 2 W z Waveshare 13,3" HAT. ESP32 nie uniesie wygodnie obrazu 1600×1200.
- **Na start, zanim będzie e-ink:** stary tablet z aplikacją w trybie „tylko ekran”. Ten sam obraz, ta sama umowa.

Przykład dla ESPHome (szkic, do sprawdzenia na prawdziwym urządzeniu):

```yaml
online_image:
  - id: plate
    url: http://homeassistant.local:8099/api/plate.png?w=800&h=480&palette=spectra6
    format: PNG
    type: RGB565
    on_download_finished:
      - component.update: epaper
display:
  - platform: epaper_spi
    id: epaper
    model: <model Spectra 6 z dokumentacji ESPHome>
    update_interval: never
    lambda: it.image(0, 0, id(plate));
interval:
  - interval: 15min
    then:
      - component.update: plate   # 304 z dodatku = brak odświeżania panelu
```

## Kolejność

1. **Rdzeń w Pythonie, bez HA:** BirdNET + YAMNet na pliku WAV, ten sam wynik co w aplikacji. Testy jak
   w Androidzie: `Timetable` na prawdziwym GTFS, `onRoute`, wysokość szczekania, `minHits`.
2. **Nasłuch na żywo** z karty USB (najpierw na Macu albo Linuksie, potem PulseAudio w HA) + `journal.json`.
3. **Samoloty, pociągi, ryciny** (porty `Sky`, `Rails`, `Art`, `Cutout`).
4. **API + prosta strona WWW** z ryciną i Dziennikiem (ingress w HA).
5. **Dodatek HA:** `config.yaml`, `Dockerfile`, obrazy na aarch64 i amd64 budowane w GitHub Actions,
   instalacja z adresu repozytorium.
6. **Encje i zdarzenia w HA.**
7. **Aplikacja w trybie „tylko ekran”** + import ZIP-a, żeby przenieść ryciny i nauczone psy z telefonu.
8. **Ekran e-ink:** `/api/plate.png` z ditheringiem do 6 kolorów i `ETag`, potem jedno z urządzeń ramki
   (reTerminal E1002 z ESPHome albo Raspberry Pi Zero 2 W z programem `frame`).

Każdy krok da się sprawdzić osobno. Po kroku 4 ramka działa już w przeglądarce, bez aplikacji.

## Do ustalenia, gdy będzie mikrofon

- Gdzie stoi komputer z HA względem okna: długość kabla albo przedłużacza USB.
- Czy w HA jest Mosquitto (MQTT), czy zdarzenia mają iść przez REST.
- Czy panel w HA ma być osobną stroną (ingress), czy kartą na pulpicie.
- Licencja BirdNET (CC BY-NC-SA) dopuszcza użytek prywatny, więc dodatek nie może być sprzedawany.
