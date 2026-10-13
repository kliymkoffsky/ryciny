# Sprzęt

## Zamówione (4 października 2026, AliExpress)

| Co | Model | Sprzedawca | Cena | Razem z dostawą |
| --- | --- | --- | --- | --- |
| Mikrofon | [Primo EM272Z1, krawatowy, ręcznie robiony, kabel 1,5 m, wtyczka 3,5 mm TRS](https://pl.aliexpress.com/item/1005009770962671.html) | Micverve Store | 174,59 zł | 206,57 zł |
| Przedłużacz | [CableCreation 3,5 mm TRS, męski → żeński, 4,5 m](https://pl.aliexpress.com/item/1005004731100981.html) | FengMei Store | 30,19 zł | 50,01 zł |

- Mikrofon ma kapsułę Primo EM272Z1, tę samą co Clippy EM272 polecany przez BirdNET-Pi (szum własny ok. 14 dB(A)).
  W zestawie są osłony od wiatru: piankowa i futrzana.
- Wtyczki są TRS (stereo, bez mikrofonowego pierścienia telefonu), więc mikrofon z przedłużaczem wchodzi prosto
  do karty dźwiękowej USB. Do tabletu albo telefonu potrzebna byłaby jeszcze przejściówka TRS → TRRS (np. Rode SC4).
- Złączkę mikrofonu z przedłużaczem trzymaj w środku, nie za oknem, a kabla nie zwijaj przy zasilaczach,
  bo 4,5 m nieekranowanego kabla łapie przydźwięk.

## Następny etap: podłączenie do Home Assistant

Mikrofon trafi do komputera z Home Assistant (HA OS), który będzie zbierał dźwięki 24/7, a telefon czy tablet
tylko je wyświetlał. Plan: [plan.md](../plan.md).

Do dokupienia:

| Co | Po co | Ile |
| --- | --- | --- |
| Karta dźwiękowa USB z wejściem mikrofonowym (np. UGREEN) | daje mikrofonowi zasilanie (plug-in power) i wpuszcza dźwięk do HA | ok. 40 zł |
| Przedłużacz USB (opcjonalnie) | jeśli komputer z HA stoi dalej niż 4,5 m od okna: karta przy oknie, dźwięk po USB cyfrowo, bez szumu | ok. 20–40 zł |

Zamówione 13 października 2026: karta **UGREEN US205 (30724)** i przedłużacz USB 2.0.

Czego się nauczyliśmy przy pierwszej próbie (test mikrofonu w panelu dodatku, 0.10.1):

- **Przejściówka USB z jednym gniazdem combo (TRRS) nie działa z mikrofonem TRS.** Wtyk z 3 pierścieniami trafia na
  styki słuchawek i masy, mikrofon nie dostaje zasilania i karta nagrywa idealną ciszę (-87 dB). Rozdzielacz
  słuchawki + mikrofon (np. UGREEN AV141) pomaga, karta z osobnym gniazdem mikrofonu jest lepsza.
- **Tania przejściówka combo nagrywała mikrofon tylko do ok. 7 kHz** (jak do rozmów), a wiele ptaków śpiewa wyżej.
  Karta ma nagrywać mikrofon w 48 kHz.
- **Przedłużacz jack 4,5 m zbierał przydźwięk sieci** (50 Hz i harmoniczne, w odsłuchu jak „pierdzenie”): 90% energii
  nagrania, bez przedłużacza 45 dB mniej. Długość do okna nadrabiać przedłużaczem USB, nie kablem jack.

## Później: kolorowy ekran e-ink (jak w fugleramme)

Ten sam panel co w Pimoroni Inky Impression (E Ink Spectra 6, 6 kolorów: czarny, biały, czerwony, zielony,
niebieski, żółty), od Waveshare, z nakładką HAT dla Raspberry Pi. Samego Inky Impression w polskich sklepach
nie ma; Waveshare jest w [Kamami](https://kamami.pl/szukaj?controller=search&s=spectra+6). Ceny z 5 października 2026.

| Rozmiar | Model | Cena | Dostępność |
| --- | --- | --- | --- |
| 4" 600×400 | Waveshare 27367, z HAT | 226,69 zł | ok. 4 tygodnie |
| **7,3" 800×480 (polecany)** | [Waveshare, z HAT](https://kamami.pl/en/e-paper-displays/1197403-7-3inch-e-ink-spectra-6-e6-full-color-e-paper-display-e-ink-display-low-power-consumption-800-4-5902186321373.html) | **385,17 zł** | ok. 4 tygodnie |
| 13,3" 1600×1200 (jak ramka fugleramme) | Waveshare 29355, z HAT | 1 318,77 zł | od ręki |

- 4" jest za mały na ramkę (drobne podpisy), 13,3" wygląda najlepiej, ale kosztuje ponad 1300 zł. 7,3" to rozsądny środek.
- Bierz wersję **z HAT**: sam panel (np. EL073TF1 z AliExpressu) nie ma płytki sterującej i nie nałoży się na Raspberry Pi.
  Starsza wersja 7,3" (F) w kolorach ACeP na Allegro (ok. 830 zł) jest droższa i ma bledsze kolory.
- Waveshare to nie Pimoroni: panel ten sam, ale bez przycisków z boku i z innym sterownikiem. fugleramme obsługuje
  tylko Inky, więc sterownik Waveshare trzeba dopisać (opis w [plan.md](../plan.md)).
- **Gotowa ramka bez Raspberry Pi:** Seeed reTerminal E1002 (7,3" Spectra 6 + ESP32-S3 w obudowie, bateria,
  ESPHome) za ok. 94 USD na AliExpress. Inne możliwe urządzenia ramki i ich porównanie: [plan.md](../plan.md#urządzenie-ramki).
- Ekran nakłada się na Raspberry Pi. Jeśli Home Assistant działa na Raspberry Pi przy ścianie, ekran może siedzieć
  na nim; jeśli HA stoi gdzie indziej, przy ramce potrzebne jest osobne **Raspberry Pi Zero 2 W** (ok. 80–100 zł)
  z kartą microSD i zasilaczem, które pobiera rycinę z HA.

### Gotowe ramki e-ink, którym Home Assistant wysyła obraz przez sieć lokalną

Bez składania i bez Raspberry Pi: ramka jest w obudowie, a obraz dostaje przez Wi-Fi albo Bluetooth z sieci domowej.
Stan z 5 października 2026; żadnej z nich jeszcze nie testowaliśmy.

| Ramka | Ekran | Cena | Jak dostaje obraz z Home Assistant | Plusy | Minusy |
| --- | --- | --- | --- | --- | --- |
| [BLOOMIN8 EinkCanvas](https://bloomin8.com/products/bloomin8-eink-canvas) | 13,3" Spectra 6, 150 PPI | ok. 499 USD (wersja 28,5" ok. 2399 USD) | oficjalna integracja z HA i lokalne REST API; automatyzacja wysyła obraz | najbliżej „po prostu ramki”, 13,3" jak fugleramme, bateria na długo, karta SD, działa bez chmury | drogo; integrację z HA znamy tylko z opisu producenta |
| [paperlesspaper OpenPaper L](https://linuxiac.com/openpaper-l-launches-as-a-13-3-inch-open-source-color-e-ink-frame/) | 13,3" kolor | do sprawdzenia | opcjonalny firmware offline: obraz przez Bluetooth albo z lokalnego URL-a; [integracja HA](https://github.com/djiwondee/paperlesspaper-ha) z akcją `upload_image` | otwarty projekt (Niemcy, UE), otwarte API | ceny i dostępności nie sprawdziliśmy |
| [Waveshare ESP32-S3 PhotoPainter](https://www.waveshare.com/wiki/ESP32-S3-PhotoPainter) (SKU 32408) | 7,3" Spectra 6 (E6), 800×480, drewniana rama, akumulator 3,7 V w zestawie | **419,23 zł w [Kamami](https://kamami.pl/wyswietlacze-e-paper/1202699-esp32-s3-photopainter-7-3inch-e6-full-color-e-paper-display-with-solid-wood-photo-frame-ultra-long-5902186339125.html)** (ok. 6 tygodni) albo na AliExpress od [SpotPear](https://pl.aliexpress.com/item/1005010272772913.html) (siostrzana marka Waveshare): 456,19 zł bez akumulatora + 63,59 zł dostawy, czyli drożej niż Kamami | fabrycznie strona WWW na ramce i upload przez Wi-Fi (obraz musi być gotową, zditherowaną BMP); z [firmware społeczności](https://hackaday.io/project/205124-esp32-wifi-e-ink-photo-frame) sama pobiera obraz z URL-a | najtańsza gotowa kolorowa ramka, bateria, Wi-Fi i Bluetooth | fabryczny firmware jest prymitywny; wysyłkę z aplikacji trzeba dopisać |
| Seeed reTerminal E1002 | 7,3" Spectra 6, 800×480 | ok. 94 USD (AliExpress), ok. 127 USD ([RobotShop](https://www.robotshop.com/products/seeedstudio-reterminal-e1002-full-color-epaper-display)) | ESPHome: sama pobiera obraz z dodatku (`online_image`) | natywnie w HA jako urządzenie ESPHome, bateria 2000 mAh na tygodnie | obsługa Spectra 6 w ESPHome jest nowa (zgłaszane błędy, np. [#12322](https://github.com/esphome/esphome/issues/12322)) |
| TRMNL z własnym, lokalnym serwerem | 7,5", tylko odcienie szarości | ok. 140 USD | lokalny serwer zgodny z API TRMNL albo webhook z HA | dojrzały ekosystem dashboardów | bez kolorów, więc nie dla rycin |

Jeśli masz już **Samsung The Frame**, rycina może wisieć na nim w Art Mode, bez kupowania ramki: integracja HACS
([ha-samsungtv-smart](https://github.com/TheFab21/ha-samsungtv-smart) albo
[Samsung Frame Art Director](https://github.com/janstrm/Home-Assistant-Samsung-Frame-Art-Director-Integration))
wysyła obraz lokalnie przez API telewizora. Szczegóły w [plan.md](../plan.md#urządzenie-ramki).

**Wybrana ramka: Waveshare ESP32-S3 PhotoPainter z Kamami** (419,23 zł z akumulatorem, ok. 6 tygodni, polski sklep
z gwarancją). Na AliExpress ta sama ramka (SpotPear) wychodzi ok. 520 zł z dostawą i bez akumulatora, więc Kamami
jest tańsze; AliExpress jest tylko szybszy (dostawa ok. 1–3 tygodnie). Najszybciej: [Amazon.pl](https://www.amazon.pl/dp/B0FWRHXCC3), ta sama ramka (ESP32-S3-PhotoPainter, E6) od Waveshare,
wysyłka Amazon, **456,99 zł bez akumulatora**, darmowa dostawa w 2 dni, zwrot do 30 dni. Brak akumulatora nie przeszkadza:
ramka, która co kilkanaście minut pobiera nową rycinę przez Wi-Fi, i tak powinna wisieć na kablu USB-C.
Oficjalny sklep Waveshare na AliExpress ma też
[13,3" E6 z wbudowanym ESP32-S3](https://pl.aliexpress.com/item/1005012080314699.html) za 1 428,19 zł (sam panel
z płytką, bez ramy).
Uwaga przy zakupie gdzie indziej: stara wersja **„PhotoPainter” bez „ESP32-S3”** (RP2040, 7-kolorowy ACeP,
np. na Alibabie za ok. 240–280 zł) bierze obrazy **tylko z karty SD**, bez Wi-Fi, więc ani telefon, ani Home Assistant
nic do niej nie wyślą. To samo dotyczy **PhotoPainter (B)** (Waveshare 30068, w Kamami 444,41 zł, od ręki): ma już
ładny ekran E6, ale procesor RP2350 bez Wi-Fi i obrazy tylko z karty microSD. Szukaj w tytule „ESP32-S3-PhotoPainter”
(Waveshare 32408) i „E6” albo „Spectra 6”.
Wysyłkę ryciny z aplikacji (przygotowanie BMP w 6 kolorach panelu i upload przez Wi-Fi) dopiszemy, gdy ramka przyjdzie.

**Co wybrać:**
- **13,3" bez składania:** BLOOMIN8 EinkCanvas (oficjalna integracja HA) albo paperlesspaper OpenPaper L.
- **7,3" tanio, bez składania:** Waveshare ESP32-S3 PhotoPainter albo Seeed reTerminal E1002 (ten drugi najprościej spina się z HA).
- **13,3" najtaniej, z własnym składaniem:** Waveshare 13,3" z HAT (tabela wyżej) + Raspberry Pi Zero 2 W.

Wszystkie kolorowe ramki pokażą ten sam obraz z dodatku (`/api/plate.png`, już w 6 kolorach panelu). Różni się tylko to,
kto zaczyna przesłanie: ramka pobiera sama (reTerminal, PhotoPainter z nowym firmware) albo automatyzacja w HA
wypycha obraz przy zmianie ryciny (BLOOMIN8, paperlesspaper). Szczegóły: [plan.md](../plan.md#urządzenie-ramki).

### Urządzenie przy ekranie, gdy kupujesz sam panel z HAT

| Urządzenie | Cena | Uwagi |
| --- | --- | --- |
| Raspberry Pi Zero 2 W + karta microSD + zasilacz | ok. 80–100 zł + ok. 40 zł | domyślne; obsługuje każdy rozmiar, także 13,3"; program `frame` pobiera obraz z HA |
| Raspberry Pi, na którym działa sam Home Assistant | 0 zł | tylko jeśli HA stoi przy ramce; ekran obsługuje wtedy dodatek |
| ESP32 + Waveshare e-Paper Driver Board (do samego panelu, bez HAT) | ok. 50–70 zł | ESPHome jak w reTerminal; tylko do 7,3" (za mało RAM-u na 1600×1200) |
| Stary tablet albo telefon z Androidem | 0 zł | nie e-ink, ale pokaże tę samą rycinę w aplikacji (tryb „tylko ekran”) albo w przeglądarce |

## Wariant bez Home Assistant: tablet jako ramka

Używany tablet z Androidem i zewnętrzny mikrofon za oknem, z aplikacją nasłuchującą na tablecie. Ceny z października 2026.

| Co | Model | Gdzie | Ile |
| --- | --- | --- | --- |
| Tablet | Samsung Galaxy Tab A7 10.4 (SM-T500 / SM-T505), używany | [OLX](https://www.olx.pl/elektronika/komputery/tablety/q-samsung-galaxy-tab-a7/) | ok. 300–450 zł |
| Mikrofon | Clippy EM272, wersja **TRRS** (do telefonu) | [Micbooster](https://micbooster.com) | ok. 60 USD |
| Osłona od wiatru | futrzana osłona do Clippy EM272 | Micbooster | ok. 25 USD |

Razem: ok. 650–800 zł.

## Tablet: Samsung Galaxy Tab A7 10.4

- Android 10–12. Aplikacja wymaga Androida 10 lub nowszego i 64-bitowego procesora, a Tab A7 spełnia oba warunki.
- Ekran 10,4", czyli dobry rozmiar na ramkę.
- **Gniazdo słuchawkowe 3,5 mm.** To najważniejsza cecha: mikrofon wchodzi do gniazda, a USB-C zostaje wolne
  do ładowania 24/7, bez przejściówek i hubów.
- W ustawieniach baterii włącz ochronę baterii (ładowanie do 85%). Przy pracy non stop wydłuża to jej życie.
- Na OLX jest zwykle sporo ofert po 300–450 zł, także z Gdańska. Wersja 32 GB wystarczy.

Tańsza alternatywa: Lenovo Tab M10 HD 2. generacji. Też ma gniazdo 3,5 mm, ale słabszy procesor.

Na co uważać przy zakupie:
- bateria nie powinna puchnąć (ekran nie może odstawać od obudowy);
- tablet musi być wylogowany z konta Google sprzedawcy (bez blokady FRP);
- port USB-C musi ładować.

## Mikrofon: Clippy EM272 TRRS

- Kapsuła Primo EM272: lepsza czułość i mniej szumu niż typowe mikrofony krawatowe. To popularny wybór do
  nagrywania ptaków ([forum iNaturalist](https://forum.inaturalist.org/t/clip-on-directional-microphone-for-android-phone/29112),
  [nagrania na xeno-canto](https://xeno-canto.org/736683)).
- Dookólny: łapie ptaki, psy, kosiarkę i samoloty ze wszystkich stron.
- Zamów wersję **TRRS** (wtyczka do telefonu), nie TRS ani XLR. Android sam przełącza nagrywanie na mikrofon
  podłączony do gniazda.

Tańsza alternatywa: dowolny mikrofon krawatowy z wtyczką TRRS, np. Boya BY-M1 (ok. 50 zł). Zadziała, ale ciche
ptaki z daleka będzie łapał gorzej.

## Montaż

- **Mikrofon na zewnątrz**, np. pod parapetem albo na ramie okna, w osłonie od wiatru i osłonięty od deszczu.
  Przez szybę ptaki są prawie niesłyszalne.
- Kabel przejdzie przez uszczelkę zamkniętego okna. Jeśli jest za krótki, dokup przedłużacz TRRS 3,5 mm.
- Tablet zostaje w środku, podłączony do ładowarki. W aplikacji zostaw włączone „Nie wygaszaj ekranu (tryb ramki)”.

Aplikacji nie testowano jeszcze ani na Tab A7, ani z zewnętrznym mikrofonem, tylko na Pixelu 9 z wbudowanym
mikrofonem. Jeśli coś nie zadziała, najpierw sprawdź na pasku na dole ryciny, czy aplikacja słyszy dźwięk
(„słychać: …”).
