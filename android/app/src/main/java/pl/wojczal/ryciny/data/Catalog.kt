package pl.wojczal.ryciny.data

import android.content.Context
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer

@Serializable
data class Breed(val pl: String, val en: String)

/** A sound with its own engraving, from shared/sounds.json. */
@Serializable
data class Sound(
    val key: String,
    val now: String,
    val past: String,
    val classes: List<Int>,
    val threshold: Float,
    val prompt: String,
    /** How many windows within a minute must hear it before it counts; guards against one noisy window. */
    val minHits: Int = 1,
    /** Off by default, e.g. sheep in a town where children's voices fake their bleating. */
    val enabled: Boolean = true,
    /** Not counted while a low plane is within 3 km: near an airport a jet's rumble fakes thunder, ships and wind. */
    val notNearPlane: Boolean = false,
    /** "thunder": counted only when the weather has a thunderstorm around. */
    val weather: String = "",
)

@Serializable
private data class SoundFile(val sounds: List<Sound>)

/** Static lists shipped in assets (shared/ in the repo, so the Pi reads the same ones). */
class Catalog(context: Context) {
    val breeds: List<Breed> = json.decodeFromString(
        ListSerializer(Breed.serializer()),
        context.assets.open("dog_breeds.json").bufferedReader().readText(),
    )

    val sounds: List<Sound> = json.decodeFromString(
        SoundFile.serializer(),
        context.assets.open("sounds.json").bufferedReader().readText(),
    ).sounds
    private val soundsByKey = sounds.associateBy { it.key }

    fun sound(key: String): Sound? = soundsByKey[key]

    /** A sound as the settings have it: the user's switch, else its default from sounds.json. */
    fun isOn(key: String, settings: Settings): Boolean = settings.sounds[key] ?: soundsByKey[key]?.enabled ?: false

    /** Only the sounds currently switched on; switched-off ones vanish from the plate and the journal too. */
    fun soundOn(key: String, settings: Settings): Sound? = sound(key)?.takeIf { isOn(key, settings) }

    /** The engraving for one heard sound; a train gets its operator's livery. */
    fun soundArt(sound: Sound, variant: String): pl.wojczal.ryciny.art.ArtRequest =
        if (variant.isBlank()) {
            pl.wojczal.ryciny.art.ArtRequest(pl.wojczal.ryciny.art.Kind.SCENE, sound.key, sound.now, prompt = sound.prompt)
        } else {
            pl.wojczal.ryciny.art.ArtRequest(
                pl.wojczal.ryciny.art.Kind.SCENE, "${sound.key}-$variant", "${sound.now} ($variant)",
                prompt = "${sound.prompt} The train wears the livery of the Polish rail operator $variant (its colours only, no readable lettering).",
            )
        }

    /** Body mass in grams per scientific name, from fugleramme's bird_sizes.csv. */
    val birdMass: Map<String, Double> = context.assets.open("bird_sizes.csv").bufferedReader().readLines().drop(1)
        .mapNotNull { line ->
            val (name, mass) = line.split(',').takeIf { it.size >= 2 } ?: return@mapNotNull null
            mass.toDoubleOrNull()?.let { name.trim('"') to it }
        }.toMap()

    fun breedEn(pl: String) = breeds.firstOrNull { it.pl.equals(pl, ignoreCase = true) }?.en ?: "a $pl dog"

    /** Unknown dogs are drawn as a mongrel of the size their bark suggests. */
    fun mongrel(size: String) = when (size) {
        "duży" -> breeds[2]
        "mały" -> breeds[0]
        else -> breeds[1]
    }
}
