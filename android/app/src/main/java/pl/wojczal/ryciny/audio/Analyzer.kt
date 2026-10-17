package pl.wojczal.ryciny.audio

import android.content.Context
import android.media.AudioManager
import kotlinx.coroutines.flow.MutableStateFlow
import pl.wojczal.ryciny.data.Bark
import pl.wojczal.ryciny.data.Place
import pl.wojczal.ryciny.data.SettingsStore
import pl.wojczal.ryciny.data.Sound
import pl.wojczal.ryciny.data.Store
import pl.wojczal.ryciny.ml.BirdNet
import pl.wojczal.ryciny.ml.Yamnet
import pl.wojczal.ryciny.planes.Sky
import pl.wojczal.ryciny.rails.Rails
import java.io.File
import java.util.UUID

/** What the microphone hears right now, for the live strip on the plate. */
data class Live(
    val listening: Boolean = false,
    val level: Float = 0f,
    val sound: String = "",
    val at: Long = 0,
    val error: String? = null,
)

/** Runs both models over each 3 s window and writes what they found to the journal. */
class Analyzer(
    context: Context,
    private val settings: SettingsStore,
    private val place: Place,
    private val store: Store,
    private val sky: Sky,
    private val state: MutableStateFlow<Live>,
    private val sounds: List<Sound>,
    private val rails: Rails,
) {
    private val birdNet = BirdNet(context)
    private val yamnet = Yamnet(context)
    private val audio = context.getSystemService(AudioManager::class.java)
    private val hits = HashMap<String, ArrayDeque<Long>>()
    private val weather = Weather(place)

    /** A low plane this close was overhead in the last 90 s (sky.py near()). */
    private fun planeNear(km: Double): Boolean {
        val sky = sky.flow.value
        val o = sky.overhead ?: return false
        return System.currentTimeMillis() - sky.updatedAt < 90_000L && o.distKm <= km && (o.altM ?: 0) <= settings.value.overheadMaxAltM
    }

    fun analyze(window: FloatArray, at: Long) {
        val s = settings.value
        // The phone's own playback (a video, a voice message, a notification) reaches the microphone and
        // would be logged as music, talking or a siren: while it plays, nothing is analysed.
        if (audio.isMusicActive) {
            state.value = state.value.copy(level = Dsp.rms(window), sound = "telefon coś odtwarza, pomijam", at = at)
            return
        }
        birds(window, at, s.birdThreshold, s.rangeFilter)

        val audio16 = Dsp.decimate48to16(window)
        val frames = (0 until 3).map { i -> yamnet.run(audio16.copyOfRange(i * 16_000, i * 16_000 + Yamnet.SAMPLES)) }
        val dogScores = frames.map { f -> Yamnet.DOG.maxOf { f.scores[it] } }
        val aircraft = frames.maxOf { f -> Yamnet.AIRCRAFT.maxOf { f.scores[it] } }
        val top = frames.flatMap { f -> f.scores.indices.map { it to f.scores[it] } }.maxBy { it.second }

        state.value = state.value.copy(level = Dsp.rms(window), sound = yamnet.classes[top.first], at = at)
        if (aircraft >= AIRCRAFT_THRESHOLD) sky.heard(at)
        sounds.forEach { sound ->
            if (!(s.sounds[sound.key] ?: sound.enabled)) return@forEach
            val score = frames.maxOf { f -> sound.classes.maxOf { f.scores[it] } }
            if (score < sound.threshold) return@forEach
            val recent = hits.getOrPut(sound.key) { ArrayDeque() }.apply {
                addLast(at)
                while (first() < at - 60_000L) removeFirst()
            }
            if (recent.size < sound.minHits) return@forEach
            if (sound.notNearPlane && planeNear(PLANE_MASK_KM)) return@forEach
            if (sound.weather == "thunder" && weather.thunder() == false) return@forEach
            val train = if (sound.key == "train") rails.match(at) else null
            // Never a recording of people: talking and children are kept as a fact only.
            val record: ((File) -> Unit)? = if (sound.key in NO_AUDIO) null else { f -> Dsp.writeWav(f, window, 48_000) }
            if (train == null) {
                store.addSound(sound.key, at, score, record = record)
            } else {
                store.addSound(sound.key, at, score, train.title, "${train.route} · planowo ${train.hhmm}", train.agency, record)
            }
        }
        if (dogScores.max() >= s.barkThreshold) bark(audio16, frames, dogScores, at, s.barkThreshold, s.dogMatch)
    }

    private fun birds(window: FloatArray, at: Long, threshold: Float, rangeFilter: Boolean) {
        val conf = birdNet.predict(window)
        val here = place.value
        val mask = if (rangeFilter) birdNet.rangeMask(here.lat, here.lon) else null
        birdNet.labels.forEachIndexed { i, label ->
            if (conf[i] >= threshold && label.bird && (mask == null || mask[i])) {
                store.addBird(label.sci, label.name, conf[i], at) { f -> Dsp.writeWav(f, window, 48_000) }
            }
        }
    }

    private fun bark(
        audio16: FloatArray,
        frames: List<Yamnet.Frame>,
        dogScores: List<Float>,
        at: Long,
        threshold: Float,
        match: Float,
    ) {
        val barking = frames.indices.filter { dogScores[it] >= threshold * 0.7f }
        val embedding = List(1024) { k -> barking.map { frames[it].embedding[k] }.average().toFloat() }
        val pitch = Dsp.barkPitch(audio16)

        val best = store.value.dogs.map { dog ->
            dog to (dog.samples.maxOfOrNull { Dsp.cosine(it, embedding) } ?: 0f)
        }.maxByOrNull { it.second }
        val dog = best?.takeIf { it.second >= match }

        val id = UUID.randomUUID().toString().take(8)
        val clip = "$id.wav"
        Dsp.writeWav(File(store.clips, clip), audio16, 16_000)
        store.addBark(
            Bark(
                id = id,
                at = at,
                lastAt = at,
                count = 1,
                score = dogScores.max(),
                pitchHz = pitch,
                size = Dsp.sizeOf(pitch),
                embedding = embedding.map { Math.round(it * 1e4f) / 1e4f },
                dogId = dog?.first?.id,
                similarity = best?.second ?: 0f,
                clip = clip,
            ),
        )
    }

    companion object {
        const val AIRCRAFT_THRESHOLD = 0.25f
        val NO_AUDIO = setOf("talking", "children")
        const val PLANE_MASK_KM = 3.0
    }
}
