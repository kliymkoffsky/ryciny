package pl.wojczal.ryciny.ui

import android.media.MediaPlayer
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import pl.wojczal.ryciny.Graph
import pl.wojczal.ryciny.art.ArtRequest
import pl.wojczal.ryciny.art.Kind
import pl.wojczal.ryciny.data.Bark
import pl.wojczal.ryciny.data.Sound
import pl.wojczal.ryciny.data.PlanePass
import pl.wojczal.ryciny.planes.art
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import java.io.File

private sealed interface Entry { val at: Long }
private data class BirdEntry(val name: String, val sci: String, val conf: Float, val count: Int, override val at: Long) : Entry
private data class SoundEntry(val sound: Sound, val event: pl.wojczal.ryciny.data.SoundEvent, val from: Long, override val at: Long) : Entry
private data class BarkEntry(val bark: Bark, val dog: String?, override val at: Long) : Entry
private data class PlaneEntry(val pass: PlanePass, val title: String, val detail: String, val heard: Boolean, override val at: Long) : Entry

/** Everything heard and seen, newest first; unknown barks can be tagged here. */
@Composable
fun JournalScreen(g: Graph) {
    val journal by g.store.flow.collectAsState()
    var filter by remember { mutableStateOf("all") }
    var tagging by remember { mutableStateOf<Bark?>(null) }
    var viewing by remember { mutableStateOf<Int?>(null) }
    val dogs = journal.dogs.associateBy { it.id }
    val entries = buildList<Entry> {
        if (filter in setOf("all", "birds")) journal.birds.forEach { add(BirdEntry(it.name, it.sci, it.conf, it.count, it.lastAt)) }
        if (filter in setOf("all", "dogs")) journal.barks.forEach { add(BarkEntry(it, it.dogId?.let { id -> dogs[id]?.let { d -> "${d.name} (${d.breed})" } }, it.lastAt)) }
        if (filter in setOf("all", "sounds")) journal.sounds.forEach { e ->
            g.catalog.soundOn(e.key, g.settings.value)?.let { add(SoundEntry(it, e, e.at, e.lastAt)) }
        }
        val onlyHeard = g.settings.value.onlyHeardPlanes
        if (filter in setOf("all", "planes")) journal.planes.filter { it.heard || !onlyHeard }.forEach {
            add(PlaneEntry(it, "${it.title} · ${it.callsign}", listOf(it.airline, it.route, "${km(it.minDistKm.toDouble())}" + (it.minAltM?.let { a -> ", $a m" } ?: "")).filter { s -> s.isNotBlank() }.joinToString(" · "), it.heard, it.lastAt))
        }
    }.sortedByDescending { it.at }.take(400)

    Column(Modifier.fillMaxSize().paper().padding(horizontal = 18.dp, vertical = 16.dp)) {
        Caption("Dziennik", size = 24, italic = false, modifier = Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("all" to "wszystko", "birds" to "ptaki", "dogs" to "psy", "planes" to "samoloty", "sounds" to "dźwięki").forEach { (k, label) ->
                FilterChip(selected = filter == k, onClick = { filter = k }, label = { Text(label) })
            }
        }
        LazyColumn(Modifier.fillMaxSize()) {
            if (filter == "dogs") item { KnownDogs(g) }
            itemsIndexed(entries) { i, e ->
                val open = { viewing = i }
                when (e) {
                    is SoundEntry -> Line(
                        hhmm(e.at),
                        if (e.event.title.isBlank()) e.sound.past else "${e.sound.past}: ${e.event.title}",
                        listOf("${hhmm(e.from)}–${hhmm(e.at)}", e.event.subtitle).filter { it.isNotBlank() }.joinToString(" · "),
                        g.catalog.soundArt(e.sound, e.event.variant), fetch = false, onClick = open,
                    )
                    is BirdEntry -> Line(
                        hhmm(e.at), e.name.replaceFirstChar { it.uppercase() },
                        "${e.sci} · ${(e.conf * 100).toInt()}%" + if (e.count > 1) " · ${e.count}×" else "",
                        ArtRequest(Kind.BIRD, e.sci, e.sci), fetch = true, onClick = open,
                    )
                    // A plane's engraving is paid for, so it is made on a tap, not by scrolling past.
                    is PlaneEntry -> Line(
                        hhmm(e.at), e.title, e.detail + if (e.heard) " · słyszany" else "",
                        e.pass.art(), fetch = false, onClick = open,
                    )
                    is BarkEntry -> BarkLine(g, e.bark, e.dog, onClick = open) { tagging = e.bark }
                }
                HorizontalDivider(color = InkSoft.copy(alpha = 0.2f))
            }
        }
    }
    tagging?.let { bark -> TagDialog(g, bark) { tagging = null } }
    viewing?.let { start -> if (entries.isNotEmpty()) Viewer(g, entries, start.coerceAtMost(entries.size - 1), { tagging = it }) { viewing = null } }
}

@Composable
private fun Line(
    time: String,
    title: String,
    detail: String,
    art: ArtRequest,
    fetch: Boolean,
    onClick: (() -> Unit)? = null,
    trailing: @Composable () -> Unit = {},
) {
    Row(
        Modifier.fillMaxWidth().let { if (onClick != null) it.clickable(onClick = onClick) else it }.padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Thumb(art, fetch, Modifier.padding(end = 12.dp))
        Column(Modifier.weight(1f)) {
            Text(title)
            Text("$time · $detail", style = Italic.copy(fontSize = 14.sp), color = InkSoft)
        }
        trailing()
    }
}



@Composable
private fun barkTitle(bark: Bark, dog: String?) = dog ?: ("Szczekanie — nieznany pies" + if (bark.size != "?") ", raczej ${bark.size}" else "")

private fun barkDetail(bark: Bark, dog: String?): String {
    val pitch = if (bark.pitchHz > 0) " · ok. ${bark.pitchHz.toInt()} Hz" else ""
    val match = if (dog != null && bark.similarity < 1f) " · podobieństwo ${(bark.similarity * 100).toInt()}%" else ""
    return "${bark.count}× · pewność ${(bark.score * 100).toInt()}%$pitch$match"
}

private fun barkArt(g: Graph, bark: Bark): ArtRequest {
    val known = bark.dogId?.let { id -> g.store.value.dogs.firstOrNull { it.id == id } }
    val breed = known?.let { it.breed to it.breedEn } ?: g.catalog.mongrel(bark.size).let { it.pl to it.en }
    return ArtRequest(Kind.DOG, breed.first, breed.second)
}

@Composable
private fun BarkButtons(g: Graph, bark: Bark, dog: String?, onTag: () -> Unit) {
    bark.clip?.let { name ->
        IconButton(onClick = { playClip(g, name) }) { Icon(Icons.Default.PlayArrow, "Odtwórz") }
    }
    TextButton(onClick = onTag) { Text(if (dog == null) "Kto to?" else "Zmień") }
}

@Composable
private fun BarkLine(g: Graph, bark: Bark, dog: String?, onClick: () -> Unit, onTag: () -> Unit) {
    Line(hhmm(bark.at), barkTitle(bark, dog), barkDetail(bark, dog), barkArt(g, bark), fetch = false, onClick = onClick) {
        BarkButtons(g, bark, dog, onTag)
    }
}

private fun playClip(g: Graph, name: String) {
    val local = File(g.store.clips, name)
    if (local.exists() || !g.store.remote) {
        play(local)
    } else {
        // Home Assistant mode: the clip lives on the add-on.
        g.scope.launch { g.remote.clip(name, File(g.context.cacheDir, "clips/$name"))?.let { f -> withContext(Dispatchers.Main) { play(f) } } }
    }
}

private var player: MediaPlayer? = null

private fun play(file: File) {
    if (!file.exists()) return
    player?.release()
    player = MediaPlayer().apply {
        setDataSource(file.path)
        setOnCompletionListener { it.release(); if (player === it) player = null }
        prepare()
        start()
    }
}

/** Tag a bark: an existing dog, or a new one named with its breed. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TagDialog(g: Graph, bark: Bark, onDone: () -> Unit) {
    val dogs = g.store.value.dogs
    var name by remember { mutableStateOf("") }
    var breed by remember { mutableStateOf(g.catalog.mongrel(bark.size).pl) }
    var open by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDone,
        title = { Text("Kto szczekał?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (dogs.isNotEmpty()) {
                    Text("Znane psy:", color = InkSoft)
                    dogs.forEach { d ->
                        TextButton(onClick = { g.store.tagBark(bark.id, d.id); onDone() }) { Text("${d.name} — ${d.breed}") }
                    }
                    HorizontalDivider()
                }
                Text("Nowy pies:", color = InkSoft)
                OutlinedTextField(name, { name = it }, label = { Text("Imię lub opis, np. „Burek zza płotu”") }, singleLine = true)
                ExposedDropdownMenuBox(expanded = open, onExpandedChange = { open = it }) {
                    OutlinedTextField(
                        breed, { breed = it },
                        label = { Text("Rasa") },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
                        modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryEditable),
                        singleLine = true,
                    )
                    ExposedDropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                        g.catalog.breeds.filter { breed.isBlank() || it.pl.contains(breed, true) || breed == g.catalog.mongrel(bark.size).pl }
                            .forEach { b -> DropdownMenuItem(text = { Text(b.pl) }, onClick = { breed = b.pl; open = false }) }
                    }
                }
                Text(
                    "Rasy nie da się poznać po samym szczekaniu. Aplikacja zapamięta brzmienie tego psa " +
                        "i następnym razem rozpozna go sama.",
                    style = Italic, color = InkSoft,
                )
            }
        },
        confirmButton = {
            TextButton(enabled = breed.isNotBlank(), onClick = {
                val id = g.store.newDog(name.ifBlank { breed }, breed, g.catalog.breedEn(breed))
                g.store.tagBark(bark.id, id)
                onDone()
            }) { Text("Zapisz nowego psa") }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Anuluj") } },
    )
}

/** One entry full screen with its engraving; swipe (or ‹ ›) for the newer and older ones. */
@Composable
private fun Viewer(g: Graph, entries: List<Entry>, start: Int, onTag: (Bark) -> Unit, onDone: () -> Unit) {
    val pager = rememberPagerState(initialPage = start) { entries.size }
    val scope = rememberCoroutineScope()
    Dialog(onDismissRequest = onDone, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxSize().paper().padding(horizontal = 20.dp, vertical = 18.dp)) {
            // A plane's engraving is generated only for the page actually shown, not for its neighbours.
            HorizontalPager(pager, Modifier.weight(1f).fillMaxWidth(), beyondViewportPageCount = 0) { i ->
                entries.getOrNull(i)?.let { Page(g, it, onTag) }
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                TextButton(enabled = pager.currentPage > 0, onClick = { scope.launch { pager.animateScrollToPage(pager.currentPage - 1) } }) { Text("‹ nowsze") }
                Caption("${pager.currentPage + 1} z ${entries.size}", size = 14, color = InkSoft, modifier = Modifier.weight(1f))
                TextButton(enabled = pager.currentPage < entries.size - 1, onClick = { scope.launch { pager.animateScrollToPage(pager.currentPage + 1) } }) { Text("starsze ›") }
            }
            TextButton(onClick = onDone, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text("Zamknij") }
        }
    }
}

@Composable
private fun Page(g: Graph, e: Entry, onTag: (Bark) -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(top = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        when (e) {
            is BirdEntry -> {
                Engraving(ArtRequest(Kind.BIRD, e.sci, e.sci), height = 340.dp, modifier = Modifier.fillMaxWidth())
                Caption(e.name.replaceFirstChar { it.uppercase() }, size = 28, italic = false)
                Caption(e.sci, size = 19)
                Caption("${hhmm(e.at)} · pewność ${(e.conf * 100).toInt()}%" + if (e.count > 1) " · ${e.count}×" else "", size = 15, color = InkSoft)
            }
            is SoundEntry -> {
                Engraving(g.catalog.soundArt(e.sound, e.event.variant), height = 340.dp, modifier = Modifier.fillMaxWidth())
                Caption(e.sound.past, size = 28, italic = false)
                if (e.event.title.isNotBlank()) Caption(e.event.title, size = 20)
                if (e.event.subtitle.isNotBlank()) Caption(e.event.subtitle, size = 17, italic = false)
                Caption("${hhmm(e.from)}–${hhmm(e.at)}", size = 15, color = InkSoft)
            }
            is PlaneEntry -> {
                val p = e.pass
                Engraving(p.art(), height = 260.dp, modifier = Modifier.fillMaxWidth(), placeholder = "rycina w przygotowaniu… (ok. pół minuty)")
                Caption(p.title, size = 28)
                Caption(listOf(p.airline, p.callsign).filter { it.isNotBlank() }.joinToString(" · "), size = 17)
                if (p.route.isNotBlank()) Caption(p.route, size = 19, italic = false)
                Caption(
                    (if (e.heard) "słychać było o " else "przeleciał o ") + hhmm(p.at) + ", najbliżej ${km(p.minDistKm.toDouble())}" +
                        (p.minAltM?.let { ", wys. ${String.format(PL, "%,d", it)} m" } ?: ""),
                    size = 15, color = InkSoft,
                )
            }
            is BarkEntry -> {
                Engraving(barkArt(g, e.bark), height = 320.dp, modifier = Modifier.fillMaxWidth())
                Caption(barkTitle(e.bark, e.dog), size = 26, italic = false)
                Caption("${hhmm(e.at)} · ${barkDetail(e.bark, e.dog)}", size = 15, color = InkSoft)
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) { BarkButtons(g, e.bark, e.dog) { onTag(e.bark) } }
            }
        }
    }
}
