package pl.wojczal.ryciny.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.IBinder
import android.util.Log
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import pl.wojczal.ryciny.MainActivity
import pl.wojczal.ryciny.graph
import pl.wojczal.ryciny.ml.BirdNet

/** Keeps the microphone open in the background and feeds 3 s windows to the [Analyzer]. */
class ListenService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            graph.settings.update { it.copy(listen = false) }
            stopSelf()
            return START_NOT_STICKY
        }
        ServiceCompat.startForeground(this, 1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        if (job?.isActive != true) job = scope.launch { listen() }
        return START_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        setListening(false)
        graph.sky.setActive("service", false)
        super.onDestroy()
    }

    private suspend fun listen() {
        val analyzer = graph.analyzer
        graph.sky.setActive("service", true)
        val windows = Channel<Pair<FloatArray, Long>>(1, BufferOverflow.DROP_OLDEST)
        scope.launch {
            // One window behind the microphone, so a recording can take 3 s before and after the detection (9 s).
            var before: FloatArray? = null
            var held: Pair<FloatArray, Long>? = null
            for ((window, at) in windows) {
                held?.let { (w, t) -> runCatching { analyzer.analyze(w, t, before, window) }.onFailure { Log.e(TAG, "analyze", it) } }
                before = held?.first
                held = window to at
            }
        }

        val record = try {
            open()
        } catch (e: SecurityException) {
            setListening(false, "Brak zgody na mikrofon")
            return
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            setListening(false, "Mikrofon niedostępny")
            return
        }
        record.startRecording()
        setListening(true)
        try {
            while (scope.isActive) {
                val window = FloatArray(BirdNet.SAMPLES)
                var filled = 0
                while (filled < window.size && scope.isActive) {
                    val n = record.read(window, filled, window.size - filled, AudioRecord.READ_BLOCKING)
                    if (n < 0) throw IllegalStateException("AudioRecord.read = $n")
                    filled += n
                }
                windows.trySend(window to System.currentTimeMillis())
            }
        } catch (e: Exception) {
            Log.e(TAG, "listen", e)
            setListening(false, e.message)
        } finally {
            record.stop()
            record.release()
        }
    }

    private fun setListening(on: Boolean, error: String? = null) {
        graph.live.value = graph.live.value.copy(listening = on, error = error)
    }

    @Suppress("MissingPermission")
    private fun open(): AudioRecord {
        val audio = getSystemService(AudioManager::class.java)
        // UNPROCESSED skips the speech noise suppression that eats birdsong; not every phone has it.
        val source = if (audio.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true") {
            MediaRecorder.AudioSource.UNPROCESSED
        } else {
            MediaRecorder.AudioSource.VOICE_RECOGNITION
        }
        val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT)
        return AudioRecord(source, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT, maxOf(min, RATE * 4 * 2))
    }

    private fun notification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Nasłuch", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, ListenService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Ryciny nasłuchują")
            .setContentText("Ptaki, psy i samoloty w okolicy")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Zatrzymaj", stop).build())
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "ListenService"
        private const val CHANNEL = "listen"
        private const val ACTION_STOP = "stop"
        const val RATE = 48_000

        fun start(context: Context) {
            context.graph.settings.update { it.copy(listen = true) }
            context.startForegroundService(Intent(context, ListenService::class.java))
        }
        fun stop(context: Context) = context.startService(Intent(context, ListenService::class.java).setAction(ACTION_STOP))
    }
}
