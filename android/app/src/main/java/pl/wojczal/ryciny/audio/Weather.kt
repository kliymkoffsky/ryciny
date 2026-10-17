package pl.wojczal.ryciny.audio

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import pl.wojczal.ryciny.data.Http
import pl.wojczal.ryciny.data.Place
import pl.wojczal.ryciny.data.json

/** Is there a thunderstorm around? Open-Meteo (free, no key), so a jet's rumble is not logged as thunder (weather.py). */
class Weather(private val place: Place) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile private var codes: List<Int>? = null
    @Volatile private var checked = 0L

    /** True or false from the last 3 hours and the next one; null when it could not be checked (the microphone decides). */
    fun thunder(): Boolean? {
        if (System.currentTimeMillis() - checked > CACHE_MS) {
            checked = System.currentTimeMillis()
            scope.launch {
                codes = runCatching {
                    val p = place.value
                    val body = Http.get(
                        "https://api.open-meteo.com/v1/forecast?latitude=%.3f&longitude=%.3f&hourly=weather_code&past_hours=3&forecast_hours=1&timezone=UTC"
                            .format(java.util.Locale.ROOT, p.lat, p.lon),
                    )
                    json.parseToJsonElement(String(body)).jsonObject["hourly"]!!.jsonObject["weather_code"]!!.jsonArray.map { it.jsonPrimitive.int }
                }.getOrNull()
            }
        }
        return codes?.any { it >= 95 } // WMO 95-99: thunderstorm
    }

    companion object {
        private const val CACHE_MS = 15 * 60_000L
    }
}
