# Instalacja

Ryciny działają na dwa sposoby. Wybierz jeden albo oba:

- **A. Sam telefon:** telefon z Androidem słucha i pokazuje ryciny. Najprostszy start.
- **B. Home Assistant + telefon:** dodatek w Home Assistant słucha mikrofonu przy komputerze z HA i prowadzi Dziennik,
  telefon (albo panel w HA, telewizor, ramka e-ink) tylko wyświetla.

Sprzęt (mikrofon, karta dźwiękowa, ramki): [docs/sprzet.md](docs/sprzet.md).

---

## A. Sam telefon

1. Pobierz `ryciny-vX.Y.Z.apk` z [ostatniego wydania](https://github.com/qunabu/ryciny/releases/latest) na telefon
   z Androidem 10 lub nowszym i otwórz plik. Zezwól na instalację z nieznanych źródeł, jeśli telefon zapyta.
   Kolejne wersje instalują się na poprzednią bez utraty danych.
2. Przy pierwszym uruchomieniu zezwól na: mikrofon, lokalizację i powiadomienia.
3. Ustawienia → **Generowanie rycin**: wybierz OpenAI, Gemini albo OpenRouter i wpisz klucz. Bez klucza ptaki i tak
   mają ryciny (tablice z fugleramme), a samoloty, psy i dźwięki pokażą puste pole.
4. Gotowe. Pasek pod ryciną pokazuje „● nasłuch trwa · słychać: …”. Telefon powinien wisieć na ładowarce; mikrofon
   (najlepiej zewnętrzny, za oknem) słyszy dużo więcej niż przez szybę.

Opcjonalnie: rycina na telewizorze Samsung The Frame. Patrz [Samsung The Frame](#samsung-the-frame).

---

## B. Home Assistant + telefon

Potrzebne: Home Assistant OS (Raspberry Pi 4/5, NUC, maszyna wirtualna), karta dźwiękowa USB z wejściem
mikrofonowym, mikrofon elektretowy (np. Primo EM272) za oknem.

### 1. Podłącz mikrofon

1. Mikrofon do wejścia mikrofonowego karty dźwiękowej USB, kartę do komputera z HA. Jeśli komputer stoi daleko od
   okna, połóż kartę przy oknie i poprowadź przedłużacz USB (dźwięk idzie wtedy cyfrowo, bez szumu).
2. W Home Assistant: **Ustawienia → System → Sprzęt** powinien pokazać kartę USB.

### 2. Zainstaluj dodatek

1. **Ustawienia → Dodatki → Sklep z dodatkami → ⋮ (prawy górny róg) → Repozytoria.**
2. Dodaj adres `https://github.com/qunabu/ryciny` i zamknij okno.
3. Odśwież sklep; na dole pojawi się sekcja **Ryciny**. Otwórz dodatek **Ryciny** → **Zainstaluj**.
   Pierwsza instalacja buduje obraz na miejscu: na Raspberry Pi kilka minut.

### 3. Skonfiguruj

Zakładka **Konfiguracja** dodatku:

| Opcja | Co wpisać |
| --- | --- |
| `image_provider` + klucz (`openai_key`, `gemini_key` albo `openrouter_key`) | do rycin samolotów, psów i dźwięków; bez klucza są tylko ptaki |
| `lat`, `lon` | zostaw puste: dodatek weźmie lokalizację domu z Home Assistant |
| `sounds_off` | dźwięki, których w okolicy nie ma (np. `sheep`, `goat`); można to też przełączać w panelu |

Zakładka **Audio** dodatku: jako **wejście** wybierz kartę dźwiękową USB.

Zakładka **Informacje**: włącz **Pokaż na pasku bocznym** i **Uruchamiaj przy starcie**, potem **Uruchom**.
Przy pierwszym starcie dodatek pobiera modele (ok. 80 MB) i rozkład pociągów (30 MB); postęp widać w **Dzienniku**
dodatku.

### 4. Sprawdź

Otwórz **Ryciny** z bocznego menu HA. Pod ryciną powinno być „● nasłuch trwa · słychać: …”.
Jeśli jest „nagrywanie przerwane”, sprawdź wejście w zakładce **Audio** dodatku.

Pod spodem jest **Test mikrofonu**: pasek poziomu i przycisk **▶ Odsłuchaj ostatnie 3 s**. Zagwiżdż albo klaśnij
przy mikrofonie, pasek powinien skoczyć, a w odsłuchu słychać gwizd. Poziom poniżej -60 dB to prawie cisza: złe
wejście w zakładce **Audio** albo mikrofon w złym gnieździe karty. Test działa od razu po starcie, zanim pobiorą się
modele.

Panel ma trzy zakładki:
- **Rycina**: najnowsza rzecz usłyszana albo widziana, na papierze;
- **Dziennik**: wszystko z miniaturami; przy szczekaniu ▶ (odsłuch) i **Kto to?** (oznaczenie psa: imię i rasa,
  od tej pory dodatek rozpozna go sam);
- **Ustawienia**: progi, dźwięki, samoloty, pociągi; zmiany działają od razu.

### 5. Rycina na dashboardzie (opcjonalnie)

1. **Ustawienia → Urządzenia i usługi → Dodaj integrację → Generic Camera.**
2. **Still image URL:** `http://<adres HA>:8099/api/plate.png?w=1600&h=900`, Stream source zostaw puste.
3. Na dashboardzie dodaj kartę **Picture entity** z tą kamerą.

Dla ekranu e-ink dopisz do adresu `&palette=spectra6` (6 kolorów panelu) albo `&palette=bw`.

### 6. Telefon jako ekran

1. Zainstaluj aplikację jak w części A (punkt 1).
2. **Ustawienia → Źródło danych → Home Assistant**, adres `http://<adres HA>:8099`
   (np. `http://homeassistant.local:8099` albo `http://192.168.1.10:8099`), **Sprawdź połączenie**.
3. Jeśli telefon wcześniej słuchał sam i nauczył się psów: **Wyślij psy z telefonu**.

Telefon wyłącza wtedy swój mikrofon i pokazuje Dziennik, ryciny i samoloty z dodatku. Psy oznaczone w telefonie
trafiają na serwer. Powrót do **Ten telefon** przywraca telefonowi jego własny Dziennik.

Telefon i Home Assistant muszą być w tej samej sieci domowej (port 8099 nie wymaga logowania i nie powinien być
wystawiony do internetu).

### 7. Strona publiczna (opcjonalnie)

Przykład: [Dźwięki Dolnego Migowa](https://dzwieki-migowa.qunabu.workers.dev). Dodatek co ok. 3 minuty wysyła do
Workera Cloudflare ptaki, usłyszane samoloty i dźwięki okolicy z rycinami, a z dźwięku tylko krótkie nagrania ptaków
(jedno na gatunek dziennie, bez ludzi i muzyki według YAMNet, 14 dni). Nie wysyła psów, rozmów, dzieci, muzyki,
dzwonka, współrzędnych ani odległości. Z internetu nic nie wchodzi do domowej sieci.

1. Darmowe konto Cloudflare i token z szablonu **Edit Cloudflare Workers**.
2. W katalogu `public-site/`: `npx wrangler kv namespace create dzwieki-migowa`, wpisz `id` do `wrangler.toml`,
   potem `npx wrangler deploy` i `npx wrangler secret put INGEST_TOKEN` (dowolny długi losowy ciąg).
3. W konfiguracji dodatku: `public_url` = adres Workera, `public_token` = ten sam ciąg.

---

## Samsung The Frame

Działa w obu wariantach; wysyła telefon.

1. Telewizor włączony, w tej samej sieci Wi-Fi co telefon. Adres IP telewizora: w telewizorze **Ustawienia → Ogólne →
   Sieć → Stan sieci → Ustawienia IP**; najlepiej zarezerwuj go w routerze.
2. W aplikacji: **Ustawienia → Samsung The Frame**, wpisz adres IP, **Podgląd**, potem **Wyślij teraz**.
   Przy pierwszym razie telewizor zapyta, czy wpuścić „Ryciny”: zezwól pilotem.
3. Włącz **Wysyłaj rycinę na The Frame**. Rycina zmienia się przy nowym samolocie albo ptaku (do wyboru, które
   rodzaje), nie częściej niż co 15 min.
4. Wyłączenie przełącznika albo **Przywróć sztukę z telewizora** przywraca to, co telewizor pokazywał wcześniej.

---

## Gdy coś nie działa

| Objaw | Co sprawdzić |
| --- | --- |
| „○ nasłuch wyłączony” w telefonie | Ustawienia → Nasłuch włączony; telefon nie zamknięty z listy ostatnich aplikacji; zgoda na mikrofon |
| W panelu HA „nagrywanie przerwane” | zakładka **Audio** dodatku: wybrane wejście USB; karta widoczna w **Ustawienia → System → Sprzęt** |
| Puste pola zamiast rycin | klucz do generowania rycin; błąd generowania jest pod polem klucza (telefon) albo w pasku panelu (HA) |
| Telefon: „brak połączenia z Home Assistant” | adres z `http://` i portem `:8099`; ta sama sieć; dodatek uruchomiony |
| Pociąg bez trasy | rozkład jeszcze się pobiera (30 MB); w Ustawieniach → Pociągi widać, ile przejazdów jest dziś obok domu |
| The Frame: „telewizor nie odpowiada” | telewizor włączony (albo w Art Mode), poprawny adres IP, ta sama sieć |
| Fałszywe dźwięki (np. owce, muzyka) | wyłącz je w Ustawieniach → Dźwięki okolicy |

Logi: telefon `adb logcat -s Rails SamsungFrame FramePusher Remote`; dodatek: zakładka **Dziennik** dodatku w HA.
