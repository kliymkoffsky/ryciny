package pl.wojczal.ryciny.data

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import pl.wojczal.ryciny.audio.Live
import pl.wojczal.ryciny.planes.Airport
import pl.wojczal.ryciny.planes.Plane
import pl.wojczal.ryciny.planes.SkyState
import java.io.File
import java.net.URLEncoder

data class RemoteState(val ok: Boolean = false, val status: String = "", val syncedAt: Long = 0)

/**
 * "Home Assistant" mode: the add-on listens and keeps the journal; this phone only shows it. Every few seconds it
 * pulls the journal (only when changed, by ETag) and the live state, and sends dog tagging back. In "phone" mode
 * (the default) none of this runs and everything works as before.
 */
class Remote(
    private val settings: SettingsStore,
    private val store: Store,
    private val live: MutableStateFlow<Live>,
    private val skyState: (SkyState) -> Unit,
    scope: CoroutineScope,
) {
    private val state = MutableStateFlow(RemoteState())
    val flow: StateFlow<RemoteState> = state
    private var etag: String? = null
    private val outbox = Channel<suspend () -> Unit>(Channel.UNLIMITED)
    private val kick = Channel<Unit>(Channel.CONFLATED)
    private val pulling = kotlinx.coroutines.sync.Mutex()

    val active: Boolean get() = settings.value.source == "server" && settings.value.serverUrl.isNotBlank()
    val base: String get() = settings.value.serverUrl.trim().trimEnd('/').let { if (it.startsWith("http")) it else "http://$it" }

    init {
        scope.launch(Dispatchers.IO) {
            while (true) {
                if (active) runCatching { pulling.withLock { sync() } }.onFailure { fail(it) } else if (store.remote) {
                    store.showLocal()
                    etag = null
                }
                // Every 5 s, or at once after this phone changed something on the server.
                kotlinx.coroutines.withTimeoutOrNull(5_000) { kick.receive() }
            }
        }
        // Writes go out one by one and in order: a new dog before the bark tagged to it.
        scope.launch(Dispatchers.IO) {
            for (job in outbox) runCatching { job() }.onFailure { fail(it) }
        }
    }

    suspend fun check(): String = runCatching {
        val r = Http.exchange("GET", "$base/api/health")
        if (r.code == 200) "połączono z dodatkiem ${json.parseToJsonElement(r.body.decodeToString()).jsonObject["version"]?.jsonPrimitive?.content}"
        else "serwer odpowiedział ${r.code}"
    }.getOrElse { "brak połączenia: ${it.message ?: it.javaClass.simpleName}" }

    private fun fail(e: Throwable) {
        Log.w(TAG, "sync", e)
        state.value = state.value.copy(ok = false, status = "brak połączenia z Home Assistant: ${e.message ?: e.javaClass.simpleName}")
    }

    private suspend fun sync() {
        val r = Http.exchange("GET", "$base/api/journal", headers = etag?.let { mapOf("If-None-Match" to it) } ?: emptyMap())
        when (r.code) {
            200 -> {
                store.showRemote(json.decodeFromString(Journal.serializer(), r.body.decodeToString()))
                etag = r.headers["etag"]
            }
            304 -> Unit
            else -> throw IllegalStateException("serwer odpowiedział ${r.code}")
        }
        val l = Http.exchange("GET", "$base/api/live")
        if (l.code == 200) {
            val o = json.parseToJsonElement(l.body.decodeToString()).jsonObject
            o["live"]?.jsonObject?.let { v ->
                live.value = Live(
                    listening = v.bool("listening") ?: false,
                    level = v.num("level")?.toFloat() ?: 0f,
                    sound = v.str("sound").orEmpty(),
                    at = v["at"]?.jsonPrimitive?.longOrNull ?: 0,
                    error = v.str("error"),
                )
            }
            o["sky"]?.jsonObject?.let { skyState(sky(it)) }
        }
        state.value = RemoteState(ok = true, status = "dane z Home Assistant", syncedAt = System.currentTimeMillis())
    }

    // --- writes ---------------------------------------------------------------------------------------

    fun newDog(id: String, name: String, breed: String, breedEn: String) = send {
        Http.exchange("POST", "$base/api/dogs", buildJsonObject {
            put("id", id); put("name", name); put("breed", breed); put("breedEn", breedEn)
        }.toString())
    }

    fun tagBark(barkId: String, dogId: String) = send {
        Http.exchange("POST", "$base/api/barks/$barkId/tag", buildJsonObject { put("dogId", dogId) }.toString())
    }

    fun editDog(id: String, name: String, breed: String, breedEn: String) = send {
        Http.exchange("PUT", "$base/api/dogs/$id", buildJsonObject {
            put("name", name); put("breed", breed); put("breedEn", breedEn)
        }.toString())
    }

    fun deleteDog(id: String) = send { Http.exchange("DELETE", "$base/api/dogs/$id") }

    /** Hands the phone's own journal (with trained dogs) to the add-on, before switching over. */
    suspend fun importLocal(file: File): String = runCatching {
        val r = Http.exchange("POST", "$base/api/import", file.readText())
        if (r.code == 200) "wysłano Dziennik i psy do Home Assistant" else "serwer odpowiedział ${r.code}"
    }.getOrElse { "błąd: ${it.message}" }

    private fun send(job: suspend () -> Unit) {
        outbox.trySend {
            // No pull in between: one finishing now would bring back the journal from before this change.
            pulling.withLock {
                job()
                etag = null
            }
            kick.trySend(Unit)
        }
    }

    // --- reads for art and clips ---------------------------------------------------------------------

    /** The engraving from the add-on, saved where the phone's own cache keeps it; null while it is still being drawn. */
    suspend fun art(root: File, kind: String, key: String, subject: String, airline: String, prompt: String): File? {
        fun q(s: String) = URLEncoder.encode(s, "UTF-8")
        val r = Http.exchange("GET", "$base/api/art?kind=$kind&key=${q(key)}&subject=${q(subject)}&airline=${q(airline)}&prompt=${q(prompt)}")
        if (r.code != 200) return null
        val rel = r.headers["x-ryciny-file"] ?: return null
        val target = File(root, rel)
        if (!target.canonicalPath.startsWith(root.canonicalPath)) return null
        target.parentFile?.mkdirs()
        target.writeBytes(r.body)
        return target
    }

    /** The add-on's statistics (same numbers as its panel and the public page); null when it cannot be reached. */
    suspend fun stats(): Stats? = runCatching {
        val r = Http.exchange("GET", "$base/api/stats")
        if (r.code == 200) json.decodeFromString(Stats.serializer(), String(r.body)) else null
    }.getOrNull()

    suspend fun clip(name: String, into: File): File? {
        val r = Http.exchange("GET", "$base/api/clips/$name")
        if (r.code != 200) return null
        into.parentFile?.mkdirs()
        into.writeBytes(r.body)
        return into
    }

    private fun sky(o: JsonObject): SkyState {
        fun plane(e: JsonElement?): Plane? {
            val p = e as? JsonObject ?: return null
            fun airport(x: JsonElement?) = (x as? JsonObject)?.let {
                Airport(it.str("iata").orEmpty(), it.str("city").orEmpty(), it.num("lat"), it.num("lon"))
            }
            return Plane(
                hex = p.str("hex").orEmpty(), callsign = p.str("callsign").orEmpty(), typeCode = p.str("typeCode").orEmpty(),
                registration = p.str("registration").orEmpty(), altM = p["altM"]?.jsonPrimitive?.intOrNull,
                onGround = p.bool("onGround") ?: false, distKm = p.num("distKm") ?: 0.0, bearing = p.num("bearing") ?: 0.0,
                track = p.num("track"), speedKmh = p["speedKmh"]?.jsonPrimitive?.intOrNull, climbMs = p.num("climbMs"),
                lat = p.num("lat") ?: 0.0, lon = p.num("lon") ?: 0.0, model = p.str("model").orEmpty(),
                airline = p.str("airline").orEmpty(), airlineIcao = p.str("airlineIcao").orEmpty(),
                origin = airport(p["origin"]), destination = airport(p["destination"]),
            )
        }
        return SkyState(
            planes = o["planes"]?.jsonArray?.mapNotNull { plane(it) }.orEmpty(),
            overhead = plane(o["overhead"]),
            updatedAt = o["updatedAt"]?.jsonPrimitive?.longOrNull ?: 0,
            error = o.str("error"),
            heardAt = o["heardAt"]?.jsonPrimitive?.longOrNull ?: 0,
        )
    }

    private fun JsonObject.str(k: String): String? = (this[k] as? JsonElement)?.takeIf { it !is JsonNull }?.jsonPrimitive?.contentOrNull
    private fun JsonObject.num(k: String): Double? = (this[k] as? JsonElement)?.takeIf { it !is JsonNull }?.jsonPrimitive?.doubleOrNull
    private fun JsonObject.bool(k: String): Boolean? = (this[k] as? JsonElement)?.takeIf { it !is JsonNull }?.jsonPrimitive?.booleanOrNull

    companion object {
        private const val TAG = "Remote"
    }
}
