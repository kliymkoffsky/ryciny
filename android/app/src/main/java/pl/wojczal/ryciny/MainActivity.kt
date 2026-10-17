package pl.wojczal.ryciny

import android.Manifest
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Book
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import pl.wojczal.ryciny.audio.ListenService
import pl.wojczal.ryciny.planes.AircraftTypes
import pl.wojczal.ryciny.ui.JournalScreen
import pl.wojczal.ryciny.ui.PaperDark
import pl.wojczal.ryciny.ui.PlateScreen
import pl.wojczal.ryciny.ui.RycinyTheme
import pl.wojczal.ryciny.ui.SettingsScreen
import pl.wojczal.ryciny.ui.StatsScreen

class MainActivity : ComponentActivity() {
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        lifecycleScope.launch { graph.place.refresh() }
        if (granted[Manifest.permission.RECORD_AUDIO] == true && graph.settings.value.source != "server" && graph.settings.value.listen) ListenService.start(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        AircraftTypes.load(this)
        val g = graph
        permissions.launch(
            arrayOf(
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.ACCESS_COARSE_LOCATION,
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.POST_NOTIFICATIONS,
            ),
        )
        setContent {
            RycinyTheme {
                val settings by g.settings.flow.collectAsState()
                LaunchedEffect(settings.keepScreenOn) {
                    if (settings.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
                var tab by rememberSaveable { mutableIntStateOf(0) }
                Scaffold(
                    bottomBar = {
                        NavigationBar(containerColor = PaperDark) {
                            listOf(
                                Triple("Rycina", Icons.Default.Image, 0),
                                Triple("Dziennik", Icons.Default.Book, 1),
                                Triple("Statystyki", Icons.Default.BarChart, 3),
                                Triple("Ustawienia", Icons.Default.Settings, 2),
                            ).forEach { (label, icon, i) ->
                                NavigationBarItem(selected = tab == i, onClick = { tab = i }, icon = { Icon(icon, label) }, label = { Text(label) })
                            }
                        }
                    },
                ) { padding ->
                    Box(Modifier.padding(padding)) {
                        when (tab) {
                            0 -> PlateScreen(g)
                            1 -> JournalScreen(g)
                            3 -> StatsScreen(g)
                            else -> SettingsScreen(g)
                        }
                    }
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        graph.sky.setActive("screen", true)
    }

    override fun onStop() {
        graph.sky.setActive("screen", false)
        super.onStop()
    }
}
