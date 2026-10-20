(function (root) {
  'use strict';

  function parseCoordinates(text) {
    /*
     * Accept one unambiguous latitude/longitude pair copied from a map.
     * Decimal commas and coordinate URLs need interpretation, so reject them.
     */

    const decimal = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)';
    const match = String(text).trim().match(new RegExp('^(' + decimal + ')\\s*[,;]\\s*(' + decimal + ')$'));
    if (!match) throw new Error('Wpisz parę: szerokość, długość. Użyj kropki dziesiętnej, np. 54.352, 18.646.');
    const lat = Number(match[1]), lon = Number(match[2]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      throw new Error('Szerokość musi mieścić się od −90 do 90, a długość od −180 do 180.');
    }
    return {lat, lon};
  }

  function bind(form, initial, save, geolocation) {
    /*
     * Keep the coordinate draft separate from unrelated settings autosaves.
     * Device GPS only fills the draft: the listener may be in a different place.
     */

    const input = form.querySelector('input');
    const fields = form.querySelector('fieldset');
    const status = form.querySelector('[role=status]');
    const device = form.querySelector('[data-location-device]');
    let saved = `${initial.lat}, ${initial.lon}`;
    input.value = saved;
    const message = (text, error = false) => {
      status.textContent = text;
      status.classList.toggle('error', error);
    };
    input.addEventListener('input', () => {
      input.setCustomValidity('');
      message(input.value === saved ? '' : 'Zmiana nie jest jeszcze zapisana.');
    });
    form.addEventListener('reset', () => {
      input.value = input.defaultValue = saved;
      input.setCustomValidity('');
      message('Przywrócono zapisaną lokalizację.');
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      let coordinates;
      try { coordinates = parseCoordinates(input.value); }
      catch (error) {
        input.setCustomValidity(error.message);
        input.reportValidity();
        message(error.message, true);
        return;
      }
      fields.disabled = true;
      message('Zapisywanie lokalizacji…');
      try {
        const result = await save(coordinates);
        if (!result) {
          message('Nie udało się zapisać lokalizacji. Wpisane współrzędne pozostają tutaj. Spróbuj ponownie.', true);
          return;
        }
        saved = `${result.lat}, ${result.lon}`;
        input.value = input.defaultValue = saved;
        message('Lokalizacja zapisana. Nowe rozpoznania korzystają z tego miejsca.');
      } catch (_) {
        message('Nie udało się zapisać lokalizacji. Spróbuj ponownie.', true);
      } finally {
        fields.disabled = false;
      }
    });
    device.disabled = !geolocation;
    if (!geolocation) device.title = 'Lokalizacja urządzenia wymaga HTTPS i dostępu przeglądarki do GPS.';
    device.addEventListener('click', () => {
      fields.disabled = true;
      message('Pobieranie lokalizacji tego urządzenia…');
      geolocation.getCurrentPosition(position => {
        fields.disabled = false;
        input.value = `${position.coords.latitude.toFixed(6)}, ${position.coords.longitude.toFixed(6)}`;
        input.setCustomValidity('');
        message('Sprawdź, czy to miejsce mikrofonu, i naciśnij „Zapisz lokalizację”.');
      }, () => {
        fields.disabled = false;
        message('Nie udało się pobrać lokalizacji. Zezwól przeglądarce na dostęp albo wpisz współrzędne ręcznie.', true);
      }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0});
    });
  }

  function bindTitle(form, initial, save) {
    /*
     * Title edits have their own draft so changing another setting cannot
     * discard typing or silently publish an unfinished title.
     */

    const input = form.querySelector('input');
    const fields = form.querySelector('fieldset');
    const status = form.querySelector('[role=status]');
    let saved = initial.station_title;
    input.value = input.defaultValue = saved;
    const message = (text, error = false) => {
      status.textContent = text;
      status.classList.toggle('error', error);
    };
    input.addEventListener('input', () => {
      input.setCustomValidity('');
      message(input.value === saved ? '' : 'Tytuł nie jest jeszcze zapisany.');
    });
    form.addEventListener('reset', () => {
      input.value = input.defaultValue = saved;
      input.setCustomValidity('');
      message('Przywrócono zapisany tytuł.');
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const title = input.value.trim();
      if (!title || [...title].length > 120 || /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/.test(title)) {
        const error = 'Wpisz tytuł od 1 do 120 znaków, w jednym wierszu.';
        input.setCustomValidity(error);
        input.reportValidity();
        message(error, true);
        return;
      }
      fields.disabled = true;
      message('Zapisywanie tytułu…');
      try {
        const result = await save({station_title: title});
        if (!result) {
          message('Nie udało się zapisać tytułu. Wpisany tekst pozostaje tutaj. Spróbuj ponownie.', true);
          return;
        }
        saved = result.station_title;
        input.value = input.defaultValue = saved;
        message('Tytuł zapisany. Publiczna strona otrzyma go przy następnej publikacji, zwykle w ciągu 5 minut.');
      } catch (_) {
        message('Nie udało się zapisać tytułu. Spróbuj ponownie.', true);
      } finally {
        fields.disabled = false;
      }
    });
  }

  root.RycinyLocation = {parseCoordinates, bind, bindTitle};
  if (typeof module !== 'undefined') module.exports = root.RycinyLocation;
})(typeof window === 'undefined' ? globalThis : window);
