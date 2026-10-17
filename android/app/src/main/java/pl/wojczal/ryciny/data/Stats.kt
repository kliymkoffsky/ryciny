package pl.wojczal.ryciny.data

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** The statistics the add-on's /api/stats returns (stats.py); on the phone alone, [localStats] counts the same. */
@Serializable
data class Stats(
    val updatedAt: Long = 0,
    val hour: Int = 0,
    val daysObserved: Int = 0,
    val birds: BirdStats = BirdStats(),
    val planes: PlaneStats = PlaneStats(),
    val sounds: SoundStats = SoundStats(),
)

@Serializable
data class BirdStats(
    val today: Int = 0,
    val week: Int = 0,
    val month: Int = 0,
    val top: List<TopBird> = emptyList(),
    val hours: List<Int> = List(24) { 0 },
    /** Share of the observed days a species was heard in the current hour. */
    val chanceNow: List<Chance> = emptyList(),
    /** Share of the observed days a species was heard at all. */
    val chanceDay: List<Chance> = emptyList(),
    /** Average BirdNET confidence per species over 30 days, highest first. */
    val confidence: List<Confidence> = emptyList(),
)

@Serializable
data class Confidence(val sci: String, val name: String, val conf: Float, val count: Int)

@Serializable
data class TopBird(val sci: String, val name: String, val count: Int, val conf: Float? = null)

@Serializable
data class Chance(val sci: String, val name: String, val day: Float, val now: Float, val bestHour: Int, val hours: List<Float> = emptyList(), val conf: Float? = null)

@Serializable
data class PlaneStats(val today: Int = 0, val week: Int = 0, val airlinesToday: Int = 0)

@Serializable
data class SoundStats(val kindsToday: Int = 0, val trainsToday: Int = 0, val week: Int = 0)

private val ZONE: ZoneId = ZoneId.of("Europe/Warsaw")
private const val TOP = 12
private const val CHANCE_DAYS = 30L

/** The phone's own journal (7 days) counted the way the add-on counts its history. */
fun localStats(j: Journal, soundOn: (String) -> Boolean, now: Long = System.currentTimeMillis()): Stats {
    val t = Instant.ofEpochMilli(now).atZone(ZONE)
    val today = t.toLocalDate()
    val dayStart = today.atStartOfDay(ZONE).toInstant().toEpochMilli()
    val week = now - 7 * 86_400_000L

    // day -> species -> detections per hour, from the newest moment of each journal entry.
    val history = sortedMapOf<LocalDate, MutableMap<String, IntArray>>()
    val names = mutableMapOf<String, String>()
    // The phone keeps each entry's best confidence only, so its average leans high.
    val sums = mutableMapOf<String, Pair<Double, Int>>()
    j.birds.forEach { b ->
        val (c, n) = sums[b.sci] ?: (0.0 to 0)
        sums[b.sci] = (c + b.conf * b.count) to (n + b.count)
        val at = Instant.ofEpochMilli(b.lastAt).atZone(ZONE)
        history.getOrPut(at.toLocalDate()) { mutableMapOf() }.getOrPut(b.sci) { IntArray(24) }[at.hour] += b.count
        names[b.sci] = b.name
    }
    fun since(days: Long) = history.filterKeys { it > today.minusDays(days) }
    fun species(h: Map<LocalDate, Map<String, IntArray>>) = h.values.flatMap { it.keys }.toSet()
    val weekDays = since(7)
    val top = mutableMapOf<String, Int>()
    val hours = IntArray(24)
    weekDays.values.forEach { day -> day.forEach { (s, h) -> top[s] = (top[s] ?: 0) + h.sum(); h.forEachIndexed { i, n -> hours[i] += n } } }

    val past = since(CHANCE_DAYS).filterKeys { it != today }.ifEmpty { history.filterKeys { it == today } }
    val n = past.size
    val conf = sums.mapValues { (_, v) -> (v.first / v.second).toFloat() }
    val chance = species(past).map { s ->
        val heard = past.values.mapNotNull { it[s] }
        val byHour = List(24) { i -> heard.count { it[i] > 0 }.toFloat() / n }
        Chance(s, names[s] ?: s, heard.size.toFloat() / n, byHour[t.hour], byHour.indices.maxBy { byHour[it] }, byHour, conf[s])
    }
    val planes = j.planes.filter { it.heard }
    val sounds = j.sounds.filter { soundOn(it.key) }
    return Stats(
        updatedAt = now,
        hour = t.hour,
        daysObserved = n,
        birds = BirdStats(
            today = history[today]?.size ?: 0,
            week = species(weekDays).size,
            month = species(since(30)).size,
            top = top.entries.sortedByDescending { it.value }.take(TOP).map { TopBird(it.key, names[it.key] ?: it.key, it.value, conf[it.key]) },
            confidence = conf.entries.sortedByDescending { it.value }.map { Confidence(it.key, names[it.key] ?: it.key, it.value, sums.getValue(it.key).second) },
            hours = hours.toList(),
            chanceNow = chance.filter { it.now > 0 }.sortedByDescending { it.now }.take(TOP),
            chanceDay = chance.sortedByDescending { it.day }.take(30),
        ),
        planes = PlaneStats(
            today = planes.count { it.at >= dayStart },
            week = planes.count { it.at >= week },
            airlinesToday = planes.filter { it.at >= dayStart && it.airline.isNotBlank() }.map { it.airline }.toSet().size,
        ),
        sounds = SoundStats(
            kindsToday = sounds.filter { it.lastAt >= dayStart }.map { it.key }.toSet().size,
            trainsToday = sounds.count { it.key == "train" && it.lastAt >= dayStart },
            week = sounds.count { it.lastAt >= week },
        ),
    )
}
