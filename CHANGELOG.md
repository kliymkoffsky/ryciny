# Zmiany

Numeracja: `MAJOR.MINOR.PATCH` (semver). Wersja jest w `android/gradle.properties` (`ryciny.version`),
tag w gicie to `vX.Y.Z`, a każdy tag ma release z plikiem APK.






## 0.23.0 - 2026-10-18

- The Frame: **tylko zwierzęta**. Rycina pokazuje najnowsze z: ptaków, zwierząt z dźwięków okolicy (kot, kogut, koń,
  krowa, owca, koza, świnia, żaby, świerszcze, pszczoły, komar) i psów (szczekanie: pies po imieniu, jeśli oznaczony,
  inaczej kundel jego wielkości). Bez samolotów, pociągów, pogody i ludzi. W „Dziś za oknem”: gatunki ptaków, ile
  razy szczekał pies i ile innych zwierząt (zamiast samolotów i pociągów).

## 0.22.1 - 2026-10-18

- Dodatek HA: YAMNet używany po kolei przez analizę na żywo i ponowną ocenę nagrań (blokada); wcześniej
  `POST /api/clips/recheck` w trakcie nasłuchu kończył się błędem interpretera TFLite.
- Modele i czcionki przenoszone z poprzedniej wersji zamiast pobierania ok. 80 MB przy każdej aktualizacji: po
  aktualizacji rozpoznawanie rusza od razu.

## 0.22.0 - 2026-10-18

- Strona publiczna: **nagranie przy każdym wpisie** ptaka i dźwięku okolicy (9 s, MP3), tak jak w HA, a nie jedno
  na gatunek dziennie. Warunek bez zmian: YAMNet nie słyszy w nagraniu ludzi ani muzyki; rozmów i dzieci dodatek
  nie nagrywa w ogóle. Dźwięki okolicy też dostają ocenę `clipPublic`. Stan strony co 4 min (limit zapisów KV).

## 0.21.1 - 2026-10-18

- Filtr „bez ludzi” odrzucał w nocy prawie wszystkie nagrania ptaków: przy cichym tle YAMNet słyszy w szumie
  „oddech” i „parsknięcie” (ok. 0,2 przy progu 0,15). Klasy oddechu, świstu, chrapania, sapania, parsknięcia i
  pociągania nosem (36–41, 45) nie liczą się już jako ludzie; mowa, krzyk, śmiech, śpiew, kaszel, kichanie, tłum,
  dzieci i muzyka dalej tak.
- `POST /api/clips/recheck`: jeszcze raz ocenia zapisane nagrania ptaków odrzucone ze strony publicznej.
- Ocena sąsiednich okien liczy YAMNet raz na sekundę (wcześniej osobno dla każdej klasy).

## 0.21.0 - 2026-10-17

- **Nagrania 9 s** zamiast 3 s: 3 s przed wykryciem, okno wykrycia i 3 s po nim (analiza idzie jedno okno za
  mikrofonem, czyli z 3 s opóźnieniem). Dotyczy ptaków, dźwięków okolicy i najlepszych nagrań gatunków.
- Dodatek HA: nagrania w **MP3** (ok. 70 kB na 9 s; `soundfile`/libsndfile), gra w każdej przeglądarce, także na
  iPhone'ach. Na stronę publiczną nagranie ptaka trafia tylko, gdy YAMNet nie słyszy ludzi ani muzyki w całych 9 s.
- Aplikacja na samym telefonie: 9 s WAV w 24 kHz.
- Starsze nagrania (3 s WAV) zostają i dalej grają.

## 0.20.1 - 2026-10-17

- The Frame: dodatek nie przerywa już oglądania. Przed wysyłką pyta telewizor o Art Mode
  (`get_artmode_status`); gdy telewizor pokazuje Netflixa, kanał albo coś innego, nic nie wysyła i pyta znów za
  5 min. Wcześniej `select_image` z `show` przełączał telewizor w Art Mode w trakcie filmu.
- `GET /api/frame/mode`: sam status Art Mode, bez wysyłania.

## 0.20.0 - 2026-10-17

- The Frame: tło jak stary papier na delikatnym płótnie (nierówny, pożółkły odcień, splot nitek, włókna, rzadkie
  rdzawe plamki, ciemniejsze brzegi), generowane raz w kodzie. Ryciny i miniatury są „drukowane” na papierze
  (mnożenie, z papierem tablicy rozjaśnionym do bieli), bez jasnej obwódki.

## 0.19.1 - 2026-10-17

- The Frame: kolumna statystyk z większym odstępem od kreski, tytuły sekcji podkreślone i wyrównane do tej samej
  lewej krawędzi co wiersze, równe odstępy, liczby w „Dziś za oknem” w jednej kolumnie, paski pod nazwami ptaków.

## 0.19.0 - 2026-10-17

- Dodatek HA: **Samsung The Frame** prosto z Home Assistant (bez telefonu). Obraz 4K: po lewej rycina tego, co
  słychać teraz (ptak, samolot albo dźwięk okolicy; bez rozmów, dzieci, muzyki i dzwonka), z opisem (ptaki: dwa
  zdania z polskiej Wikipedii), po prawej „Dziś za oknem” (gatunki, samoloty, pociągi), najczęstsze ptaki tygodnia
  i szansa usłyszenia teraz, z miniaturami rycin. Zmienia się przy nowym dźwięku, nie częściej niż co
  `frame_every_min` minut, i co 30 min dla statystyk; poprzedni obraz jest usuwany z telewizora.
- Panel: Ustawienia → Samsung The Frame (adres IP, włącznik, Wyślij teraz, Przywróć sztukę, Podgląd `api/tv.jpg`).
  Protokół jak w aplikacji (art-app WebSocket + D2D), token parowania w `/data/frame.json`.

## 0.18.0 - 2026-10-17

- Aplikacja na samym telefonie działa jak dodatek HA:
  - nagrania ptaków i dźwięków przy wykryciu (najlepszy moment zdarzenia, bez rozmów i dzieci), kasowane po 14 dniach;
    Dziennik telefonu trzyma 14 dni;
  - najlepsze nagranie każdego gatunku zachowywane na stałe (`best/`, `best.json`), z ▶ w Statystykach;
  - burza, statek i wiatr nie liczą się przy samolocie w promieniu 3 km, a burza tylko przy burzy w Open-Meteo.

## 0.17.0 - 2026-10-17

- **Najlepsze nagranie każdego gatunku**, zachowywane na stałe: dodatek trzyma jedno nagranie na gatunek, to z
  najwyższą pewnością BirdNET w całej historii (`data/best/`, `best.json`), i podmienia je tylko na lepsze. Nie
  podlega kasowaniu po 14 dniach. Na start brane z nagrań, które dodatek już miał.
- W statystykach panelu HA, aplikacji i strony publicznej przy każdym ptaku: „najlepsze nagranie: 99%, data” z ▶.
  Na stronę publiczną trafia tylko, gdy YAMNet nie usłyszał w nim ludzi ani muzyki.

## 0.16.0 - 2026-10-17

- Strona publiczna: **nagrania ptaków** (▶ przy ryciny i w Dzienniku). Jedno na gatunek dziennie, to z najwyższą
  pewnością BirdNET, i tylko takie, w którym YAMNet nie usłyszał ludzi (mowa, krzyk, śmiech, płacz, śpiew, kaszel,
  tłum, dzieci) ani muzyki (próg 0,15; gwizd się nie liczy, bo tak bywa nazywany śpiew ptaków). W KV wygasają po
  14 dniach. Psy, samoloty i dźwięki okolicy dalej bez nagrań.
- Dodatek HA: przy każdym nagraniu ptaka zapisuje, czy może być publiczne (`clipPublic`). Nagrania sprzed tej wersji
  nie mają tej oceny, więc nie trafiają na stronę.

## 0.15.0 - 2026-10-17

- Dodatek HA: **nagrania wykrytych dźwięków**. Przy wykryciu ptaka albo dźwięku zostaje 3 s nagrania najlepszego
  momentu danego zdarzenia (przy lepszym trafieniu poprzednie jest podmieniane), tylko na dysku HA, przez 14 dni;
  starsze są kasowane. Rozmów i dzieci nie nagrywa. Odsłuch ▶ w Dzienniku panelu i aplikacji (tryb Home Assistant).
  Nie trafiają na stronę publiczną.
- Dziennik dodatku trzyma 14 dni (było 7), a osobna historia (`history.json`, rok) zlicza ptaki na dzień i godzinę.
- **Statystyki** (`/api/stats`, jedna implementacja dla panelu, aplikacji i strony): gatunki dziś, 7 i 30 dni,
  najczęstsze ptaki, rozkład godzinowy, samoloty i dźwięki okolicy, a do tego:
  - **szansa usłyszenia** ptaka teraz (na ilu dniach nasłuchu odezwał się o tej godzinie) i w ciągu dnia, z godziną,
    o której najczęściej go słychać;
  - **średnia pewność BirdNET** każdego gatunku z 30 dni, ze wszystkich wykryć.
- Panel HA: zakładka **Statystyki**. Aplikacja: zakładka **Statystyki** (w trybie HA z dodatku, na samym telefonie
  liczona z jego Dziennika). Strona publiczna: szansa usłyszenia i średnia pewność.

## 0.14.0 - 2026-10-16

- Dodatek HA: mniej fałszywych burz i statków przy lotnisku. Po wzmocnieniu mikrofonu YAMNet brał dudnienie
  samolotów (GDN 2 km od domu) za grzmot i statek: 16.10 zapisał 8 „burz” w słoneczny dzień, każdą w pobliżu przelotu.
  - `notNearPlane` w `sounds.json` (burza, statek, wiatr): nie liczą się, gdy nisko leci samolot w promieniu 3 km.
  - Burza (`weather: thunder`) liczy się tylko, gdy Open-Meteo ma burzę w okolicy (kody WMO 95–99) w ostatnich 3
    godzinach albo w następnej. Gdy pogody nie da się sprawdzić, decyduje sam mikrofon.
  - Burza i statek wymagają co najmniej 2 trafień w ciągu minuty (`minHits`).
- API dodatku: `DELETE /api/sounds?key=…&since=…&until=…` usuwa fałszywe wpisy jednego dźwięku z Dziennika.

## 0.13.1 - 2026-10-15

- Strona publiczna: Dziennik stronicowany po 25 wpisów (‹ nowsze, numery stron, starsze ›).
- Dodatek HA: przed wysyłką na stronę publiczną pobiera brakujące ryciny ptaków. Dotąd brał tylko te, które ktoś
  już obejrzał w panelu albo aplikacji, więc część ptaków (np. gęś krótkodzioba) była na stronie bez ryciny.

## 0.13.0 - 2026-10-15

- **Strona publiczna** „Dźwięki Dolnego Migowa”: https://dzwieki-migowa.qunabu.workers.dev. Worker Cloudflare z KV
  (`public-site/`), tylko do odczytu: rycina na żywo, statystyki gatunków (dziś, 7 i 30 dni, ranking, rozkład
  godzinowy) i Dziennik ptaków, usłyszanych samolotów i dźwięków okolicy.
- Dodatek HA: opcje `public_url` i `public_token`. Co ok. 3 minuty (gdy coś się zmieniło) wysyła okrojony Dziennik,
  każdą rycinę raz. Nie wysyła audio, psów, rozmów, dzieci, muzyki, dzwonka, współrzędnych ani odległości samolotów.
  Z internetu nic nie wchodzi do domowej sieci.

## 0.12.0 - 2026-10-15

- Dodatek HA: **wzmocnienie mikrofonu** (`mic_gain_db`, 0–36 dB) w Ustawieniach panelu i w konfiguracji dodatku.
  Cichy mikrofon za oknem dawał przy samolocie 0,8 km od domu tylko ok. -43 dB i YAMNet nie rozpoznawał samolotów
  (wynik „aircraft” 0,01–0,04, próg 0,25). Przy +24 dB oba nagrane przeloty zostały rozpoznane, a w ciszy pojawiły
  się pojedyncze fałszywe dźwięki. Wzmocnienie działa też na pasek poziomu i odsłuch w teście mikrofonu.

## 0.11.0 - 2026-10-15

- Aplikacja: dotknięcie pozycji w Dzienniku otwiera ją na pełnym ekranie z dużą ryciną; przesunięcie palcem (albo
  ‹ nowsze / starsze ›) przechodzi do sąsiednich. Przy szczekaniu są tam też odsłuch i „Kto to?”. Zastępuje
  okienko, które było tylko przy samolotach.

## 0.10.2 - 2026-10-15

- Dodatek HA: ryciny samolotów, psów i dźwięków zamawiane w tle zaraz po zdarzeniu (każda tylko raz). Wcześniej
  powstawała tylko rycina najnowszej rzeczy i tylko wtedy, gdy ktoś akurat oglądał panel, więc Dziennik miał
  ryciny wyłącznie przy ptakach.

## 0.10.1 - 2026-10-13

- Dodatek HA: **Test mikrofonu** na zakładce Rycina: pasek poziomu (dB) i szczyt odświeżane co 3 s, przycisk
  „Odsłuchaj ostatnie 3 s” (`/api/mic.wav`, bez wzmacniania) i podpowiedź, gdy jest cisza albo przester.
- Nagrywanie rusza od razu po starcie, jeszcze zanim pobiorą się modele, więc mikrofon da się sprawdzić od razu.

## 0.10.0 - 2026-10-09

- **Dodatek do Home Assistant** (`homeassistant/ryciny`, repozytorium dodatków pod adresem tego repo): nasłuch z mikrofonu przy komputerze z HA, BirdNET, YAMNet (psy, 34 dźwięki), samoloty, pociągi, generowanie rycin i Dziennik w tym samym formacie co aplikacja. Lokalizacja domu z Home Assistant.
- **Panel „Ryciny” w HA:** rycina, Dziennik z miniaturami, odsłuch szczekania i oznaczanie psów, Ustawienia zmieniane na żywo. Rycina jako obraz `/api/plate.png` do kamery na dashboardzie (także w 6 kolorach dla e-ink).
- **Aplikacja: Źródło danych → Home Assistant.** Telefon nie słucha, tylko pokazuje Dziennik, ryciny i samoloty z dodatku; psy oznaczane w telefonie trafiają na serwer; „Wyślij psy z telefonu” przenosi nauczone psy. Domyślnie („Ten telefon”) wszystko działa jak dotąd, a Dziennik telefonu zostaje nietknięty.
- The Frame działa w obu trybach.
## 0.9.3 - 2026-10-05

- The Frame: wyłączenie przełącznika „Wysyłaj rycinę na The Frame” (albo przycisk „Przywróć sztukę z telewizora”) usuwa rycinę z telewizora i przywraca to, co pokazywał wcześniej: jego dzieło, pokaz slajdów i automatyczną rotację. Aplikacja zapamiętuje ten stan przy pierwszym wysłaniu i na czas wysyłania wyłącza pokaz slajdów, żeby nie przykrywał ryciny.
## 0.9.2 - 2026-10-05

- The Frame: gdy w ostatnich godzinach nie było samolotu ani ptaka, telewizor dostaje ostatnią taką rycinę z całego Dziennika (do 7 dni), a nie pustą kartkę „Cisza”. Sprawdzone na 55" The Frame (QE55LS03FAUXXH, 2025): parowanie, wysyłka (1,4 MB) i wyświetlenie w Art Mode w ok. 5 s.
## 0.9.1 - 2026-10-05

- The Frame: na telewizor trafiają tylko wybrane rodzaje rycin, domyślnie samoloty i ptaki (psy i dźwięki okolicy do włączenia w Ustawieniach). Z ostatniej godziny wygrywa samolot, potem ptak, potem pies i dźwięk; gdy przez godzinę nic z nich się nie działo, zostaje najnowsza dozwolona rycina.
## 0.9.0 - 2026-10-05

- **Samsung The Frame:** rycina trafia na telewizor w Art Mode przez sieć domową, bez chmury i bez Home Assistant. Ustawienia → „Samsung The Frame”: adres IP telewizora, „Wyślij teraz”, „Podgląd”. Wysyła przy zmianie ryciny, nie częściej niż co 15 min (do ustawienia), w 3840×2160 na papierze, bez passe-partout, i kasuje poprzednią rycinę z pamięci telewizora. Przy pierwszym połączeniu telewizor pyta o zgodę (pilot).
- Ten sam wybór ryciny dla ekranu i telewizora (`plateSubjects`); protokół Art Mode jak w `samsungtvws`, sprawdzony testem z atrapą telewizora.
## 0.8.0 - 2026-10-04

- Ryciny można generować przez **OpenRouter**: Ustawienia → „Generowanie rycin” → OpenRouter, klucz `sk-or-…` i model (domyślnie `google/gemini-2.5-flash-image`, działa każdy model OpenRoutera generujący obrazy). Samoloty dostają proporcje 3:2, reszta 1:1.

## 0.7.2 - 2026-10-04

- Owca i koza są domyślnie wyłączone: w mieście ich „beczenie” to były głosy dzieci, a te łapie osobna kategoria.
- Ustawienia → „Dźwięki okolicy”: przełącznik dla każdego z 34 dźwięków. Wyłączony dźwięk nie jest zapisywany i znika z ryciny oraz z Dziennika (również wcześniejsze wpisy). Domyślne ustawienie to nowe pole `enabled` w `shared/sounds.json`.

## 0.7.1 - 2026-10-04

- Mniej fałszywych dźwięków: gdy telefon sam coś odtwarza (film, wiadomość głosowa, dźwięk powiadomienia), analiza jest wstrzymana, bo mikrofon słyszał telefon i zapisywał „muzykę”, „rozmowy” czy „syreny”.
- Muzyka liczy się dopiero po 3 trafieniach w ciągu minuty, z progiem 0,7 (było: jedno okno z progiem 0,6). Rozmowy, syreny i alarm samochodowy po 2 trafieniach. Nowe pole `minHits` w `shared/sounds.json`.

## 0.7.0 - 2026-10-04

- Nowe dźwięki z rycinami: samochód (próg 0,5), zabawa dzieci (0,4) i rozmowy ludzi (0,6). Przy rozmowach i dzieciach zapisuje się tylko sam fakt: bez nagrania i bez rozpoznawania słów. Motocykl był już od 0.3.0.
- Rycina układa dźwięki według chwili, w której się zaczęły, więc długie zdarzenie (ruch uliczny, rozmowa) nie wypycha ciągle reszty na dalsze miejsca.

## 0.6.0 - 2026-10-04

- Samoloty: rycina i Dziennik pokazują tylko te, które mikrofon usłyszał (YAMNet: silnik odrzutowy, śmigło, samolot). Pozostałe przeloty dalej zapisują się w tle, ale nie są pokazywane, więc nie generują się dla nich ryciny. Przełącznik „Pokazuj tylko samoloty, które słychać” w Ustawieniach przywraca wszystkie.
- Rycina usłyszanego samolotu zostaje na ekranie także po jego odlocie (z godziną i najmniejszą odległością).

## 0.5.4 - 2026-10-04

- Naprawione pociągi: rozkład w ogóle się nie pobierał, bo brakowało uprawnienia `ACCESS_NETWORK_STATE` (sprawdzanie typu sieci rzucało wyjątek, który po cichu przerywał przeliczanie).
- Pierwsze pobranie rozkładu (30 MB) idzie przez każdą sieć; część telefonów zgłasza domowe Wi-Fi jako taryfowe. Odświeżanie co 3 dni dalej czeka na sieć bez limitu.
- Rozkład liczy się dopiero po ustaleniu lokalizacji, a trasy dzisiejszych pociągów przeliczają się przy każdej zmianie rozkładu (wcześniej mogły dostać trasę z linii w centrum Gdańska).
- Logi rozkładu w `adb logcat -s Rails`.

## 0.5.3 - 2026-10-04

- Samoloty: trasa z adsbdb jest pokazywana tylko wtedy, gdy samolot jest przy jednym z lotnisk albo w promieniu 300 km od linii między nimi. adsbdb przypisuje trasy do numerów lotów, które linie wykorzystują ponownie, więc nad Gdańskiem pojawiało się np. „Abu Zabi → Budapeszt”.

## 0.5.2 - 2026-10-04

- Przycisk „Zatrzymaj nasłuch” / „Włącz nasłuch” pod ryciną i przełącznik „Nasłuch” na górze Ustawień (wcześniej tylko z powiadomienia albo przez stuknięcie w mały napis).
- Wyłączony nasłuch zostaje wyłączony po ponownym otwarciu aplikacji.

## 0.5.1 - 2026-10-04

- Pociągi usłyszane, zanim rozkład się wczytał, dostają trasę wstecz, gdy tylko rozkład jest gotowy (wcześniej zostawały jako sam „Przejechał pociąg”).
- Rozkład przelicza się od razu, gdy zmieni się lokalizacja; wcześniej po starcie przez pół godziny mógł być liczony dla centrum Gdańska.
- Gdy pociąg nie ma trasy, rycina mówi dlaczego (rozkład się wczytuje, brak rozkładu, brak pociągu ±5 min).

## 0.5.0 - 2026-10-04

- Pociągi: gdy mikrofon usłyszy pociąg, aplikacja dopasowuje go do rozkładu wszystkich polskich pociągów (SKM Trójmiasto, PolRegio, Intercity…; GTFS z mkuran.pl na danych PKP PLK) i pokazuje przewoźnika, numer, skąd i dokąd jedzie oraz planową godzinę. Rozkład (30 MB) pobiera się przez Wi-Fi raz na 3 dni; opóźnienia nie są uwzględniane.
- Ryciny dźwięków i psów generują się w tle, gdy dany dźwięk lub pies pojawi się pierwszy raz, więc Dziennik od razu ma ich miniatury (np. koń). Samoloty dalej na dotknięcie.

## 0.4.0 - 2026-10-04

- Dziennik: miniatura ryciny przy każdym wpisie (ptak, samolot, pies, dźwięk). Miniatury pokazują tylko ryciny zapisane w telefonie, więc przewijanie niczego nie generuje; płatną rycinę samolotu zamawia się dotknięciem wpisu. Darmowe tablice ptaków dociągają się same.

## 0.3.1 - 2026-10-04

- Dolne menu ma trzy zakładki: lista znanych psów przeszła do Dziennika (filtr „psy”), nad szczekania.
- Kosiarka łapie się z większej odległości: próg z 0,3 na 0,15 (piła łańcuchowa z 0,35 na 0,25). Kosiarka sąsiada przy progu 0,3 nie została zapisana.

## 0.3.0 - 2026-10-04

- 31 dźwięków okolicy, każdy z własną ryciną: kosiarka, piła łańcuchowa, majsterkowanie, burza, deszcz, wiatr, statek i syrena mgłowa, dzwony kościelne, pociąg, motocykl, helikopter, karetka, policja, straż pożarna, syrena alarmowa, fajerwerki, alarm samochodowy, kot, kogut, koń, krowa, owca, koza, świnia, żaby, świerszcze, pszczoły i osy, komar, muzyka u sąsiadów, dzwonek do drzwi, lodziarz.
- Lista dźwięków, ich progi i prompty rycin są w `shared/sounds.json`, wspólnym z wersją na Pi. Mowa, płacz i inne ludzkie odgłosy są celowo pominięte.
- Dziennik: filtr „dźwięki”.

## 0.2.0 - 2026-10-04

- Kosiarka: YAMNet wykrywa koszenie trawy u sąsiada, a rycina pokazuje je jako tablicę z XIX-wiecznego poradnika ogrodniczego.
- Dziennik: przy każdym samolocie jest przycisk „Rycina”, który pokazuje rycinę tego typu w barwach linii (i ją generuje, jeśli jeszcze jej nie ma).
- Ryciny nie są generowane dwa razy: generowanie dokańcza się nawet po przełączeniu ekranu, oryginał z API jest zapisywany przed wycinaniem tła, a w Ustawieniach widać, ile rycin jest w pamięci.

## 0.1.0 - 2026-10-04

Pierwsza wersja testowa na Androida.

- Nasłuch w tle: BirdNET 6K v2.4 (ptaki, filtr gatunków dla miejsca i tygodnia) i YAMNet (szczekanie, silniki samolotów).
- Samoloty z adsb.lol i adsbdb: typ, linia, rejestracja, trasa, wysokość, odległość, kierunek.
- Psy: wykrywanie szczekania, szacunek wielkości z wysokości głosu, oznaczanie psów z sąsiedztwa („Kto to?”) i rozpoznawanie ich po próbkach.
- Rycina pokazuje jedną rzecz naraz: najnowszą z samolotu nad głową, ostatniego ptaka i ostatniego psa. Dotknięcie przełącza na następną.
- Ryciny ptaków z fugleramme; samoloty i psy generowane przez OpenAI lub Gemini, wycinane z tła i zapisywane w telefonie.
- Dziennik z odsłuchem szczekania, lista psów, ustawienia, eksport ZIP dla wersji na Raspberry Pi.
