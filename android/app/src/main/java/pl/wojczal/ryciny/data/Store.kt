package pl.wojczal.ryciny.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import java.io.File
import java.util.UUID

/** One bird singing, merged while it keeps singing (gaps under a minute). */
@Serializable
data class BirdHit(
    val sci: String,
    val name: String,
    val conf: Float,
    val at: Long,
    val lastAt: Long = at,
    val count: Int = 1,
    /** The add-on's recording of the best moment (kept 14 days there); null on the phone alone. */
    val clip: String? = null,
)

/** One barking episode: windows of the same dog less than [Store.BARK_GAP_MS] apart. */
@Serializable
data class Bark(
    val id: String,
    val at: Long,
    val lastAt: Long,
    val count: Int,
    val score: Float,
    val pitchHz: Float,
    val size: String,
    val embedding: List<Float>,
    val dogId: String? = null,
    val similarity: Float = 0f,
    val clip: String? = null,
)

/** A dog the user has named; its barks are the YAMNet embeddings they tagged. */
@Serializable
data class Dog(
    val id: String,
    val name: String,
    val breed: String,
    val breedEn: String,
    val samples: List<List<Float>> = emptyList(),
)

@Serializable
data class PlanePass(
    val hex: String,
    val callsign: String,
    val title: String,
    val airline: String,
    val route: String,
    val at: Long,
    val lastAt: Long,
    val minDistKm: Float,
    val minAltM: Int?,
    val heard: Boolean = false,
    val typeCode: String = "",
    val airlineIcao: String = "",
)

/** One stretch of a sound from shared/sounds.json (mowing, a storm, a ship...), until it has been quiet for [Store.SOUND_GAP_MS]. */
@Serializable
data class SoundEvent(
    val key: String,
    val at: Long,
    val lastAt: Long,
    val count: Int = 1,
    val score: Float,
    /** What exactly was heard, when the app can tell: for a train, its number and operator. */
    val title: String = "",
    val subtitle: String = "",
    /** Picks a more specific engraving, e.g. the train operator's livery. */
    val variant: String = "",
    /** The add-on's recording (kept 14 days there); never for talking or children. */
    val clip: String? = null,
)

/** Written by 0.2.0, read once to carry its mowing over into [SoundEvent]s. */
@Serializable
data class Mowing(
    val at: Long,
    val lastAt: Long,
    val count: Int = 1,
    val score: Float,
)

@Serializable
data class Journal(
    val birds: List<BirdHit> = emptyList(),
    val barks: List<Bark> = emptyList(),
    val dogs: List<Dog> = emptyList(),
    val planes: List<PlanePass> = emptyList(),
    val sounds: List<SoundEvent> = emptyList(),
    val mowing: List<Mowing> = emptyList(),
)

@OptIn(FlowPreview::class)
class Store(private val dir: File, scope: CoroutineScope) {
    private val file = File(dir, "journal.json")
    val clips = File(dir, "clips").apply { mkdirs() }

    /** Each species' most confident recording ever: kept for good, replaced only by a better one (like the add-on). */
    val bestDir = File(dir, "best").apply { mkdirs() }
    private val bestFile = File(dir, "best.json")
    private val bestState = MutableStateFlow(
        runCatching { json.decodeFromString(BEST_SERIALIZER, bestFile.readText()) }
            .getOrDefault(emptyMap()),
    )
    val best: StateFlow<Map<String, BestClip>> = bestState
    private val state = MutableStateFlow(load())
    val flow: StateFlow<Journal> = state
    val value: Journal get() = state.value

    /** Showing the Home Assistant add-on's journal: nothing is saved over the phone's own, writes go to the add-on. */
    @Volatile
    var remote: Boolean = false
        private set
    var server: Remote? = null
    val localFile: File get() = file

    fun showRemote(journal: Journal) {
        remote = true
        state.value = journal
    }

    fun showLocal() {
        remote = false
        state.value = load()
    }

    init {
        scope.launch(Dispatchers.IO) {
            state.drop(1).debounce(3_000).collect { journal ->
                if (remote) return@collect
                val tmp = File(dir, "journal.json.tmp")
                tmp.writeText(json.encodeToString(Journal.serializer(), journal))
                tmp.renameTo(file)
            }
        }
    }

    /**
     * [record] writes the 3 s window to a file; it is called only when this detection's recording is kept: a new
     * event, a better one than the event's recording so far, or the best of the species ever.
     */
    fun addBird(sci: String, name: String, conf: Float, at: Long, record: ((File) -> Unit)? = null) {
        val prev = state.value.birds.lastOrNull { it.sci == sci }?.takeIf { at - it.lastAt < BIRD_GAP_MS }
        val clip = if (record != null && (prev == null || conf > prev.conf || prev.clip == null)) newClip(record) else null
        keepBest(sci, conf, at, clip, record)
        state.update { j ->
            val last = j.birds.lastOrNull { it.sci == sci }
            val birds = if (last != null && at - last.lastAt < BIRD_GAP_MS) {
                j.birds.map { if (it === last) it.copy(lastAt = at, count = it.count + 1, conf = maxOf(it.conf, conf), clip = clip ?: it.clip) else it }
            } else {
                j.birds + BirdHit(sci, name, conf, at, clip = clip)
            }
            j.copy(birds = birds.filter { at - it.lastAt < KEEP_MS })
        }
        pruneClips(at)
    }

    private fun newClip(record: (File) -> Unit): String? = runCatching {
        val name = UUID.randomUUID().toString().take(8) + ".wav"
        record(File(clips, name))
        name
    }.getOrNull()

    private fun keepBest(sci: String, conf: Float, at: Long, clip: String?, record: ((File) -> Unit)?) {
        val old = bestState.value[sci]
        if (old != null && conf <= old.conf) return
        val name = UUID.randomUUID().toString().take(8) + ".wav"
        val file = File(bestDir, name)
        runCatching { clip?.let { File(clips, it).copyTo(file) } ?: record?.invoke(file) ?: return }.getOrElse { return }
        old?.let { File(bestDir, it.clip).delete() }
        bestState.value = bestState.value + (sci to BestClip(conf, at, name))
        runCatching {
            bestFile.writeText(json.encodeToString(BEST_SERIALIZER, bestState.value))
        }
    }

    private var pruned = 0L

    /** Recordings older than [CLIP_KEEP_MS] or no longer in the journal go; at most every 10 minutes. */
    private fun pruneClips(now: Long, force: Boolean = false) {
        if (!force && System.currentTimeMillis() - pruned < 600_000L) return
        pruned = System.currentTimeMillis()
        state.update { j ->
            j.copy(
                birds = j.birds.map { if (it.clip != null && now - it.lastAt >= CLIP_KEEP_MS) it.copy(clip = null) else it },
                sounds = j.sounds.map { if (it.clip != null && now - it.lastAt >= CLIP_KEEP_MS) it.copy(clip = null) else it },
                barks = j.barks.map { if (it.clip != null && now - it.lastAt >= CLIP_KEEP_MS) it.copy(clip = null) else it },
            )
        }
        val j = state.value
        val used = (j.birds.map { it.clip } + j.sounds.map { it.clip } + j.barks.map { it.clip }).filterNotNull().toSet()
        clips.listFiles()?.filter { it.name !in used && now - it.lastModified() > 60_000L }?.forEach { it.delete() }
    }

    /** Folds a bark into the running episode of the same dog, or opens a new one. */
    fun addBark(bark: Bark) = state.update { j ->
        val last = j.barks.lastOrNull()
        val same = last != null && bark.at - last.lastAt < BARK_GAP_MS &&
            (last.dogId == bark.dogId && (bark.dogId != null || last.size == bark.size))
        val barks = if (same) {
            j.barks.dropLast(1) + last!!.copy(
                lastAt = bark.at,
                count = last.count + 1,
                score = maxOf(last.score, bark.score),
                clip = if (bark.score > last.score && bark.clip != null) bark.clip else last.clip,
            )
        } else {
            j.barks + bark
        }
        j.copy(barks = trimBarks(barks, bark.at))
    }

    private fun trimBarks(barks: List<Bark>, now: Long): List<Bark> {
        val kept = barks.filter { now - it.lastAt < KEEP_MS }.takeLast(MAX_BARKS)
        return kept
    }

    /** Tags a bark episode as [dogId]'s; its embedding becomes one more sample of that dog. */
    fun tagBark(barkId: String, dogId: String) {
        if (remote) server?.tagBark(barkId, dogId)
        tagBarkHere(barkId, dogId)
    }

    private fun tagBarkHere(barkId: String, dogId: String) = state.update { j ->
        val bark = j.barks.firstOrNull { it.id == barkId } ?: return@update j
        j.copy(
            barks = j.barks.map { if (it.id == barkId) it.copy(dogId = dogId, similarity = 1f) else it },
            dogs = j.dogs.map { if (it.id == dogId) it.copy(samples = (it.samples + listOf(bark.embedding)).takeLast(MAX_SAMPLES)) else it },
        )
    }

    fun newDog(name: String, breed: String, breedEn: String): String {
        val id = UUID.randomUUID().toString().take(8)
        if (remote) server?.newDog(id, name, breed, breedEn)
        state.update { it.copy(dogs = it.dogs + Dog(id, name, breed, breedEn)) }
        return id
    }

    fun editDog(id: String, name: String, breed: String, breedEn: String) {
        if (remote) server?.editDog(id, name, breed, breedEn)
        editDogHere(id, name, breed, breedEn)
    }

    private fun editDogHere(id: String, name: String, breed: String, breedEn: String) = state.update { j ->
        j.copy(dogs = j.dogs.map { if (it.id == id) it.copy(name = name, breed = breed, breedEn = breedEn) else it })
    }

    fun deleteDog(id: String) {
        if (remote) server?.deleteDog(id)
        deleteDogHere(id)
    }

    private fun deleteDogHere(id: String) = state.update { j ->
        j.copy(
            dogs = j.dogs.filterNot { it.id == id },
            barks = j.barks.map { if (it.dogId == id) it.copy(dogId = null, similarity = 0f) else it },
        )
    }

    fun addSound(
        key: String, at: Long, score: Float, title: String = "", subtitle: String = "", variant: String = "",
        record: ((File) -> Unit)? = null,
    ) {
        val prev = state.value.sounds.lastOrNull { it.key == key }?.takeIf { at - it.lastAt < SOUND_GAP_MS }
        val clip = if (record != null && (prev == null || score > prev.score || prev.clip == null)) newClip(record) else null
        addSoundHere(key, at, score, title, subtitle, variant, clip)
        pruneClips(at)
    }

    private fun addSoundHere(key: String, at: Long, score: Float, title: String, subtitle: String, variant: String, clip: String?) = state.update { j ->
        val last = j.sounds.lastOrNull { it.key == key }
        // Two different trains a few minutes apart are two events, not one long one.
        val same = last != null && at - last.lastAt < SOUND_GAP_MS && (title.isBlank() || last.title.isBlank() || title == last.title)
        val sounds = if (same) {
            j.sounds.map {
                if (it !== last) it else it.copy(
                    lastAt = at, count = it.count + 1, score = maxOf(it.score, score),
                    title = it.title.ifBlank { title }, subtitle = it.subtitle.ifBlank { subtitle }, variant = it.variant.ifBlank { variant },
                    clip = clip ?: it.clip,
                )
            }
        } else {
            j.sounds + SoundEvent(key, at, at, 1, score, title, subtitle, variant, clip = clip)
        }
        j.copy(sounds = sounds.filter { at - it.lastAt < KEEP_MS }.takeLast(MAX_SOUNDS))
    }

    /** Re-derives events' details from the current timetable, e.g. a train's route; [details] null leaves one as it is. */
    fun fillSounds(key: String, details: (SoundEvent) -> Triple<String, String, String>?) = state.update { j ->
        j.copy(
            sounds = j.sounds.map { e ->
                if (e.key != key) e
                else details(e)?.let { (title, subtitle, variant) -> e.copy(title = title, subtitle = subtitle, variant = variant) } ?: e
            },
        )
    }

    fun addPlane(pass: PlanePass) = state.update { j ->
        val last = j.planes.lastOrNull { it.hex == pass.hex }
        val planes = if (last != null && pass.at - last.lastAt < PLANE_GAP_MS) {
            j.planes.map {
                if (it !== last) it else it.copy(
                    lastAt = pass.at,
                    minDistKm = minOf(it.minDistKm, pass.minDistKm),
                    minAltM = listOfNotNull(it.minAltM, pass.minAltM).minOrNull(),
                    heard = it.heard || pass.heard,
                    route = pass.route.ifBlank { it.route },
                    airline = pass.airline.ifBlank { it.airline },
                    title = pass.title.ifBlank { it.title },
                    typeCode = pass.typeCode.ifBlank { it.typeCode },
                    airlineIcao = pass.airlineIcao.ifBlank { it.airlineIcao },
                )
            }
        } else {
            j.planes + pass
        }
        j.copy(planes = planes.filter { pass.at - it.lastAt < KEEP_MS }.takeLast(MAX_PLANES))
    }

    private fun load(): Journal {
        val j = runCatching { json.decodeFromString(Journal.serializer(), file.readText()) }.getOrDefault(Journal())
        if (j.mowing.isEmpty()) return j
        val carried = j.mowing.map { SoundEvent("mower", it.at, it.lastAt, it.count, it.score) }
        return j.copy(sounds = (carried + j.sounds).sortedBy { it.at }, mowing = emptyList())
    }

    companion object {
        const val BIRD_GAP_MS = 60_000L
        const val BARK_GAP_MS = 30_000L
        const val PLANE_GAP_MS = 10 * 60_000L
        const val SOUND_GAP_MS = 5 * 60_000L
        const val MAX_SOUNDS = 1_000
        const val KEEP_MS = 14 * 24 * 3600_000L
        const val CLIP_KEEP_MS = 14 * 24 * 3600_000L
        private val BEST_SERIALIZER = MapSerializer(String.serializer(), BestClip.serializer())
        const val MAX_BARKS = 300
        const val MAX_PLANES = 500
        const val MAX_SAMPLES = 30
    }
}
