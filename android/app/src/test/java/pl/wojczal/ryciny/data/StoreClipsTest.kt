package pl.wojczal.ryciny.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

/** The phone alone keeps recordings the way the add-on does: the best of each event, and each species' best for good. */
class StoreClipsTest {
    @Test
    fun recordingsOfEventsAndTheBestOfEachSpecies() {
        val dir = Files.createTempDirectory("ryciny").toFile()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        try {
            val s = Store(dir, scope)
            val t = System.currentTimeMillis()
            s.addBird("Anser albifrons", "gęś białoczelna", 0.97f, t) { it.writeText("best") }
            val first = s.value.birds.last().clip!!
            s.addBird("Anser albifrons", "gęś białoczelna", 0.80f, t + 1_000) { it.writeText("worse") }
            assertEquals(first, s.value.birds.last().clip)
            val best = s.best.value.getValue("Anser albifrons")
            assertEquals(0.97f, best.conf)
            assertEquals("best", java.io.File(s.bestDir, best.clip).readText())

            s.addSound("talking", t, 0.9f)
            assertNull(s.value.sounds.last().clip)
            s.addSound("train", t, 0.5f) { it.writeText("train") }
            assertTrue(java.io.File(s.clips, s.value.sounds.last().clip!!).exists())

            s.addBird("Anser albifrons", "gęś białoczelna", 0.99f, t + 2_000) { it.writeText("better") }
            val better = s.best.value.getValue("Anser albifrons")
            assertNotEquals(best.clip, better.clip)
            assertEquals(1, s.bestDir.listFiles()!!.size)
            assertEquals(better, Store(dir, scope).best.value["Anser albifrons"])
        } finally {
            scope.cancel()
            dir.deleteRecursively()
        }
    }
}
