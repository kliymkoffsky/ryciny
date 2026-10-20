# Ryciny

Dodatek słucha mikrofonu podłączonego do komputera z Home Assistant i rozpoznaje ptaki (BirdNET), psy z sąsiedztwa,
34 dźwięki okolicy (YAMNet), samoloty nad domem (adsb.lol, adsbdb) i pociągi (rozkład PKP PLK). Każdą rzecz pokazuje
jako XIX-wieczną rycinę. Aplikacja Ryciny na Androida może wtedy tylko wyświetlać to, co zebrał dodatek.

## Instalacja

Pełna instrukcja krok po kroku: [INSTALL.md](https://github.com/qunabu/ryciny/blob/main/INSTALL.md).

1. Ustawienia → Dodatki → Sklep z dodatkami → ⋮ → Repozytoria → dodaj `https://github.com/qunabu/ryciny`.
2. Zainstaluj „Ryciny” (pierwsza instalacja buduje obraz na miejscu, na Raspberry Pi kilka minut).
3. Konfiguracja: klucz do generowania rycin (OpenAI, Gemini albo OpenRouter; bez klucza ryciny ptaków i tak są).
   Lokalizacja domu jest brana z Home Assistant, chyba że wpiszesz własną.
4. Uruchom. Przy pierwszym starcie dodatek pobiera modele (ok. 80 MB) i rozkład pociągów (30 MB).

## Mikrofon

Mikrofon elektretowy (np. Primo EM272) przez kartę dźwiękową USB z wejściem mikrofonowym. W Home Assistant:
Ustawienia → System → Sprzęt / Audio, wybierz kartę USB jako wejście dla dodatku „Ryciny” (zakładka dodatku → Audio).
Pasek na dole ryciny pokazuje, czy nasłuch trwa i co słychać.

## Panel i dashboard

- **Panel „Ryciny” w bocznym menu:** rycina, Dziennik z miniaturami, odsłuch szczekania i „Kto to?” do oznaczania
  psów, Ustawienia (progi, dźwięki, samoloty, pociągi; zmiany działają od razu).
- **Rycina na dashboardzie:** dodaj integrację „Generic Camera” z adresem
  `http://<adres HA>:8099/api/plate.png?w=1600&h=900` (Still image URL) i kartę „Picture entity”.
  Dla ekranu e-ink: `&palette=spectra6` (6 kolorów panelu) albo `&palette=bw`.

## Tytuł publicznej strony

W panelu **Ustawienia → Tytuł publicznej strony** wpisz nazwę nasłuchu i naciśnij
**Zapisz tytuł**. Tytuł może mieć od 1 do 120 znaków. Zapis pozostaje po restarcie.
Nagłówek publicznej strony i nazwa jej karty w przeglądarce zmienią się przy następnej
publikacji, zwykle w ciągu 5 minut, także gdy w dzienniku nie przybyło dźwięków.
Adres strony, współrzędne i dotychczasowy dziennik pozostają bez zmian.

## Zmiana miejsca nasłuchu

W panelu wybierz **Ustawienia → Lokalizacja nasłuchu**. Wpisz lub wklej parę
`szerokość, długość`, np. `54.352, 18.646`, i naciśnij **Zapisz lokalizację**.
Obie liczby zapisują się razem i pozostają po ponownym uruchomieniu dodatku.
Zapisana lokalizacja ma pierwszeństwo przed lokalizacją Home Assistant i konfiguracją dodatku.

Przycisk **Użyj lokalizacji tego urządzenia** wypełnia pole po zgodzie przeglądarki
(wymaga HTTPS lub localhost). Sprawdź, czy urządzenie jest przy mikrofonie, i zapisz.
Możesz też zawsze wpisać współrzędne ręcznie; **Cofnij** przywraca zapisaną parę.

Ptaki i pogoda korzystają z nowego miejsca przy następnym rozpoznaniu. Samoloty
oraz rozkład pociągów odświeżają się w tle; dane z poprzedniego miejsca są od razu
pomijane. Dziennik i adres publikacji pozostają te same. Dokładne współrzędne
nie trafiają do publicznej strony.

## Aplikacja na telefonie

W aplikacji Ryciny: Ustawienia → „Źródło danych” → Home Assistant, adres `http://<adres HA>:8099`.
Telefon nie słucha wtedy sam, pokazuje Dziennik, ryciny i samoloty z dodatku, a oznaczone psy trafiają na serwer.
„Wyślij psy z telefonu” przenosi psy nauczone wcześniej na telefonie.

## API

| | |
| --- | --- |
| `GET /api/journal` | Dziennik w formacie aplikacji (ETag) |
| `GET /api/live` | nasłuch, samolot nad głową, stan rozkładu |
| `GET /api/art?kind=&key=&subject=` | rycina (generowana raz) |
| `GET /api/plate.png?w=&h=&palette=` | gotowa rycina jako obraz (ETag) |
| `GET /api/clips/<id>.wav` | nagranie szczekania |
| `POST /api/dogs`, `POST /api/barks/<id>/tag`, `PUT/DELETE /api/dogs/<id>` | psy |
| `GET/PUT /api/settings`, `GET /api/sounds` | ustawienia z panelu |
| `POST /api/import` | Dziennik z telefonu (psy z próbkami) |

Port 8099 jest dostępny w sieci domowej bez logowania (dla aplikacji); panel w bocznym menu idzie przez logowanie HA.
