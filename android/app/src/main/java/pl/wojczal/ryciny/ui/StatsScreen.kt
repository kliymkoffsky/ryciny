package pl.wojczal.ryciny.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import pl.wojczal.ryciny.Graph
import pl.wojczal.ryciny.art.ArtRequest
import pl.wojczal.ryciny.art.Kind
import android.media.MediaPlayer
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import pl.wojczal.ryciny.data.BestClip
import pl.wojczal.ryciny.data.Stats
import pl.wojczal.ryciny.data.localStats

/** The same numbers as the add-on's panel and the public page: from the add-on, or counted on the phone alone. */
@Composable
fun StatsScreen(g: Graph) {
    val journal by g.store.flow.collectAsState()
    val settings by g.settings.flow.collectAsState()
    val fromServer = settings.source == "server"
    val remote by produceState<Stats?>(null, fromServer) {
        while (fromServer) {
            g.remote.stats()?.let { value = it }
            delay(60_000)
        }
    }
    val s = if (fromServer) remote else localStats(journal, { g.catalog.soundOn(it, settings) != null })

    LazyColumn(Modifier.fillMaxSize().paper().padding(horizontal = 18.dp, vertical = 16.dp)) {
        item { Caption("Statystyki", size = 24, italic = false, modifier = Modifier.fillMaxWidth()) }
        if (s == null) {
            item { Caption("Czekam na dane z Home Assistant…", color = InkSoft, modifier = Modifier.fillMaxWidth().padding(40.dp)) }
            return@LazyColumn
        }
        val b = s.birds
        item {
            Heading("Ptaki")
            Numbers(b.today to "gatunków dziś", b.week to "gatunków w 7 dni", b.month to "gatunków w 30 dni")
            Heading("Szansa usłyszenia teraz (${s.hour}:00–${s.hour + 1}:00)")
            Caption("Na ilu z ${s.daysObserved} ostatnich dni nasłuchu ptak odezwał się o tej godzinie.", size = 14, color = InkSoft)
            if (b.chanceNow.isEmpty()) Caption("O tej godzinie jeszcze nic nie było słychać.", size = 15, color = InkSoft)
        }
        items(b.chanceNow) { c -> BirdBar(c.sci, c.name, c.now, "${(c.now * 100).toInt()}%", confNote(c.conf), g, b.best[c.sci]) }
        item { Heading("Szansa usłyszenia w ciągu dnia") }
        items(b.chanceDay) { c -> BirdBar(c.sci, c.name, c.day, "${(c.day * 100).toInt()}%", "najczęściej ok. ${c.bestHour}:00" + c.conf.let { if (it != null) " · " + confNote(it) else "" }, g, b.best[c.sci]) }
        item { Heading("Najczęściej słyszane (7 dni)") }
        val max = (b.top.maxOfOrNull { it.count } ?: 1).coerceAtLeast(1)
        items(b.top) { t -> BirdBar(t.sci, t.name, t.count.toFloat() / max, "${t.count}×", confNote(t.conf), g, b.best[t.sci]) }
        item {
            Heading("Średnia pewność BirdNET (30 dni)")
            Caption("Jak bardzo model był pewny, że to ten gatunek, średnio ze wszystkich wykryć. Niska średnia przy rzadkim gatunku to znak, że mogła to być pomyłka.", size = 14, color = InkSoft)
        }
        items(b.confidence) { c -> BirdBar(c.sci, c.name, c.conf, "${(c.conf * 100).toInt()}%", "${c.count} wykryć", g, b.best[c.sci]) }
        item {
            Heading("Ptaki według godziny (7 dni)")
            Hours(b.hours)
            Heading("Samoloty")
            Numbers(s.planes.today to "usłyszanych dziś", s.planes.week to "w 7 dni", s.planes.airlinesToday to "linii lotniczych dziś")
            Heading("Dźwięki okolicy")
            Numbers(s.sounds.kindsToday to "rodzajów dziś", s.sounds.trainsToday to "pociągów dziś", s.sounds.week to "zdarzeń w 7 dni")
            Spacer(Modifier.height(24.dp))
        }
    }
}

private var player: MediaPlayer? = null

private fun playBest(g: Graph, name: String) {
    g.scope.launch {
        val f = g.remote.clip(name, File(g.context.cacheDir, "best/$name"), best = true) ?: return@launch
        withContext(Dispatchers.Main) {
            player?.release()
            player = MediaPlayer().apply {
                setDataSource(f.path)
                setOnCompletionListener { it.release(); if (player === it) player = null }
                prepare()
                start()
            }
        }
    }
}

private fun day(t: Long): String = java.text.SimpleDateFormat("d MMM", PL).format(java.util.Date(t))

private fun confNote(conf: Float?) = conf?.let { "śr. pewność BirdNET ${(it * 100).toInt()}%" } ?: ""

@Composable
private fun Heading(text: String) {
    Spacer(Modifier.height(16.dp))
    Text(text, color = Rubric, fontSize = 20.sp)
    Spacer(Modifier.height(6.dp))
}

@Composable
private fun Numbers(vararg items: Pair<Int, String>) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEach { (n, label) ->
            Column(
                Modifier.weight(1f).border(1.dp, InkSoft.copy(alpha = 0.3f)).padding(8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("$n", color = Rubric, fontSize = 26.sp)
                Caption(label, size = 13, italic = false)
            }
        }
    }
}

@Composable
private fun BirdBar(sci: String, name: String, share: Float, value: String, note: String = "", g: Graph? = null, best: BestClip? = null) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Thumb(ArtRequest(Kind.BIRD, sci, sci), fetch = true, Modifier.padding(end = 10.dp), size = 44.dp)
        Column(Modifier.weight(1f)) {
            Text(name.replaceFirstChar { it.uppercase() })
            if (note.isNotBlank()) Text(note, style = Italic.copy(fontSize = 13.sp), color = InkSoft)
            if (best != null && g != null) {
                // The add-on keeps each species' most confident recording for good.
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("najlepsze nagranie: ${(best.conf * 100).toInt()}%, ${day(best.at)}", style = Italic.copy(fontSize = 13.sp), color = InkSoft)
                    IconButton(onClick = { playBest(g, best.clip) }, modifier = Modifier.size(32.dp)) { Icon(Icons.Default.PlayArrow, "Odsłuchaj najlepsze nagranie") }
                }
            }
            Box(Modifier.fillMaxWidth(share.coerceIn(0.03f, 1f)).height(6.dp).background(Rubric.copy(alpha = 0.75f)))
        }
        Text(value, modifier = Modifier.padding(start = 10.dp))
    }
    HorizontalDivider(color = InkSoft.copy(alpha = 0.15f))
}

@Composable
private fun Hours(hours: List<Int>) {
    val max = (hours.maxOrNull() ?: 1).coerceAtLeast(1)
    Row(Modifier.fillMaxWidth().height(80.dp), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.Bottom) {
        hours.forEach { n ->
            Box(Modifier.weight(1f).fillMaxHeight((n.toFloat() / max).coerceAtLeast(0.01f)).background(Rubric.copy(alpha = 0.7f)))
        }
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        listOf("0:00", "6:00", "12:00", "18:00", "23:00").forEach { Text(it, fontSize = 12.sp, color = InkSoft) }
    }
}
