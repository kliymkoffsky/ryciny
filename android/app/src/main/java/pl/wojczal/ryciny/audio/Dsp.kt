package pl.wojczal.ryciny.audio

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

object Dsp {
    // 63-tap windowed-sinc low-pass at 7.2 kHz for the 48 -> 16 kHz decimation.
    private val taps: FloatArray = run {
        val n = 63
        val cutoff = 7_200.0 / 48_000.0
        val h = DoubleArray(n) { i ->
            val m = i - (n - 1) / 2.0
            val sinc = if (m == 0.0) 2 * cutoff else sin(2 * PI * cutoff * m) / (PI * m)
            sinc * (0.42 - 0.5 * cos(2 * PI * i / (n - 1)) + 0.08 * cos(4 * PI * i / (n - 1)))
        }
        val sum = h.sum()
        FloatArray(n) { (h[it] / sum).toFloat() }
    }

    fun decimate48to16(x: FloatArray): FloatArray {
        val out = FloatArray(x.size / 3)
        val half = taps.size / 2
        for (o in out.indices) {
            val c = o * 3
            var acc = 0f
            for (k in taps.indices) {
                val i = c + k - half
                if (i >= 0 && i < x.size) acc += taps[k] * x[i]
            }
            out[o] = acc
        }
        return out
    }

    fun rms(x: FloatArray): Float {
        var s = 0.0
        for (v in x) s += v * v
        return sqrt(s / x.size).toFloat()
    }

    /**
     * Median fundamental of the loud frames, by autocorrelation in 120-1500 Hz.
     * A rough guide to the dog's size: a mastiff's bark sits far lower than a yorkie's.
     */
    fun barkPitch(x: FloatArray, rate: Int = 16_000): Float {
        val frame = 640
        val energies = (0 until x.size / frame).map { f -> rms(x.copyOfRange(f * frame, f * frame + frame)) }
        val loud = energies.maxOrNull() ?: return 0f
        val minLag = rate / 1_500
        val maxLag = rate / 120
        val pitches = energies.indices.filter { energies[it] > loud * 0.4f }.mapNotNull { f ->
            val s = f * frame
            var e0 = 0f
            for (i in s until s + frame) e0 += x[i] * x[i]
            if (e0 <= 0f) return@mapNotNull null
            var best = 0f
            var lag = 0
            for (l in minLag..maxLag) {
                var acc = 0f
                for (i in s until s + frame - l) acc += x[i] * x[i + l]
                val r = acc / e0
                if (r > best) {
                    best = r
                    lag = l
                }
            }
            if (best > 0.35f && lag > 0) rate.toFloat() / lag else null
        }.sorted()
        return if (pitches.isEmpty()) 0f else pitches[pitches.size / 2]
    }

    fun sizeOf(pitchHz: Float) = when {
        pitchHz <= 0f -> "?"
        pitchHz < 380f -> "duży"
        pitchHz < 650f -> "średni"
        else -> "mały"
    }

    fun cosine(a: List<Float>, b: List<Float>): Float {
        var dot = 0f
        var na = 0f
        var nb = 0f
        for (i in a.indices) {
            dot += a[i] * b[i]
            na += a[i] * a[i]
            nb += b[i] * b[i]
        }
        return if (na == 0f || nb == 0f) 0f else dot / (sqrt(na) * sqrt(nb))
    }

    /** 48 kHz to 24 kHz: a two-tap average (a gentle low-pass) and every other sample. */
    fun halve(x: FloatArray): FloatArray = FloatArray(x.size / 2) { i -> (x[2 * i] + x[2 * i + 1]) / 2 }

    fun writeWav(file: File, x: FloatArray, rate: Int) {
        val peak = x.maxOf { abs(it) }.coerceAtLeast(1e-4f)
        val gain = (0.9f / peak).coerceAtMost(8f)
        val data = ByteBuffer.allocate(x.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        x.forEach { data.putShort((it * gain).coerceIn(-1f, 1f).times(32767).toInt().toShort()) }
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36 + x.size * 2); put("WAVE".toByteArray())
            put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1); putInt(rate); putInt(rate * 2)
            putShort(2); putShort(16)
            put("data".toByteArray()); putInt(x.size * 2)
        }
        RandomAccessFile(file, "rw").use {
            it.setLength(0)
            it.write(header.array())
            it.write(data.array())
        }
    }
}
