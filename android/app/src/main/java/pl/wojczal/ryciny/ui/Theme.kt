package pl.wojczal.ryciny.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.Image
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.ImageShader
import androidx.compose.ui.graphics.ShaderBrush
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import pl.wojczal.ryciny.R
import pl.wojczal.ryciny.art.ArtRequest
import pl.wojczal.ryciny.graph
import kotlin.random.Random

val Paper = Color(0xFFF3EAD7)
val PaperDark = Color(0xFFE6D9BC)
val Ink = Color(0xFF2B2118)
val InkSoft = Color(0xFF6B5B4A)
val Rubric = Color(0xFF9C3B2A)

val Garamond = FontFamily(
    Font(R.font.garamond, FontWeight.Normal),
    Font(R.font.garamond, FontWeight.SemiBold),
    Font(R.font.garamond_italic, FontWeight.Normal, FontStyle.Italic),
)

@Composable
fun RycinyTheme(content: @Composable () -> Unit) {
    val base = MaterialTheme.typography
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Rubric, onPrimary = Paper, background = Paper, surface = Paper, onSurface = Ink,
            onBackground = Ink, surfaceVariant = PaperDark, onSurfaceVariant = InkSoft, secondaryContainer = PaperDark,
            surfaceContainer = PaperDark, surfaceContainerHigh = Paper, outline = InkSoft,
        ),
        typography = base.copy(
            bodyLarge = base.bodyLarge.copy(fontFamily = Garamond, fontSize = 18.sp),
            bodyMedium = base.bodyMedium.copy(fontFamily = Garamond, fontSize = 16.sp),
            bodySmall = base.bodySmall.copy(fontFamily = Garamond, fontSize = 14.sp),
            titleLarge = base.titleLarge.copy(fontFamily = Garamond, fontSize = 26.sp),
            titleMedium = base.titleMedium.copy(fontFamily = Garamond, fontSize = 20.sp),
            labelLarge = base.labelLarge.copy(fontFamily = Garamond, fontSize = 16.sp),
            labelMedium = base.labelMedium.copy(fontFamily = Garamond, fontSize = 14.sp),
        ),
        content = content,
    )
}

/** Laid paper: a warm sheet with fibre speckle, so plates read as printed rather than on a screen. */
private val grain: ImageBitmap by lazy {
    val size = 192
    val rnd = Random(7)
    val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
    for (y in 0 until size) for (x in 0 until size) {
        val n = rnd.nextInt(-9, 10) + if (y % 6 == 0) -3 else 0
        bmp.setPixel(x, y, android.graphics.Color.rgb(243 + n / 2, 234 + n / 2, 215 + n))
    }
    bmp.asImageBitmap()
}

fun Modifier.paper(): Modifier = this
    .background(Paper)
    .drawBehind {
        drawRect(ShaderBrush(ImageShader(grain, TileMode.Repeated, TileMode.Repeated)))
        val inset = 10.dp.toPx()
        drawRect(Ink.copy(alpha = 0.55f), Offset(inset, inset), size.copy(size.width - inset * 2, size.height - inset * 2),
            style = androidx.compose.ui.graphics.drawscope.Stroke(1.2f))
        val inner = inset + 4.dp.toPx()
        drawRect(Ink.copy(alpha = 0.35f), Offset(inner, inner), size.copy(size.width - inner * 2, size.height - inner * 2),
            style = androidx.compose.ui.graphics.drawscope.Stroke(0.6f))
    }

val Italic = TextStyle(fontFamily = Garamond, fontStyle = FontStyle.Italic)

@Composable
fun Caption(text: String, size: Int = 17, color: Color = Ink, italic: Boolean = true, modifier: Modifier = Modifier) {
    Text(
        text,
        modifier = modifier,
        style = (if (italic) Italic else TextStyle(fontFamily = Garamond)).copy(fontSize = size.sp, color = color, textAlign = TextAlign.Center),
    )
}

/** Ornamental rule between sections of the plate. */
@Composable
fun Rule(label: String) {
    Box(Modifier.fillMaxWidth().padding(vertical = 10.dp), contentAlignment = Alignment.Center) {
        Box(Modifier.fillMaxWidth(0.8f).height(1.dp).background(Ink.copy(alpha = 0.4f)))
        Text(
            "  $label  ",
            modifier = Modifier.background(Paper).wrapContentSize(),
            style = TextStyle(fontFamily = Garamond, fontSize = 14.sp, letterSpacing = 3.sp, color = InkSoft),
        )
    }
}

/** An engraving, fetched or generated on first sight and cached for good. */
@Composable
fun Engraving(request: ArtRequest, height: Dp, modifier: Modifier = Modifier, placeholder: String = "rycina w przygotowaniu…") {
    val art = LocalContext.current.graph.art
    val version by art.version.collectAsState()
    val image by produceState<ImageBitmap?>(initialValue = remember(request.key) { null }, request, version) {
        val file = art.cached(request) ?: art.load(request)
        value = file?.let { f -> withContext(Dispatchers.IO) { BitmapFactory.decodeFile(f.path)?.asImageBitmap() } }
    }
    val bmp = image
    // In Home Assistant mode the add-on may have a prepared animation of this subject: six frames, played in a loop.
    val graph = LocalContext.current.graph
    val context = LocalContext.current
    val moving by produceState<Pair<ImageBitmap, Long>?>(null, request.kind, request.key, graph.store.remote) {
        value = if (!graph.store.remote) null else graph.remote.animation(context.cacheDir, request.kind.name, request.key)?.let { a ->
            withContext(Dispatchers.IO) { BitmapFactory.decodeFile(a.sprite.path)?.asImageBitmap() }?.let { it to a.frameMs }
        }
    }
    val anim = moving
    if (anim != null && !reducedMotion()) {
        val (sprite, frameMs) = anim
        val frame by produceState(0, sprite) { while (true) { delay(frameMs); value = (value + 1) % 6 } }
        val fw = sprite.width / 6
        // Fit like the still image: the full height, the width from the frame's proportions, centred.
        Box(modifier.height(height), contentAlignment = Alignment.Center) {
            androidx.compose.foundation.Canvas(
                Modifier.fillMaxHeight().aspectRatio(fw.toFloat() / sprite.height, matchHeightConstraintsFirst = true),
            ) {
                drawImage(
                    sprite,
                    srcOffset = androidx.compose.ui.unit.IntOffset(frame * fw, 0),
                    srcSize = androidx.compose.ui.unit.IntSize(fw, sprite.height),
                    dstSize = androidx.compose.ui.unit.IntSize(size.width.toInt(), size.height.toInt()),
                )
            }
        }
    } else if (bmp != null) {
        Image(bmp, contentDescription = request.subject, contentScale = ContentScale.Fit, modifier = modifier.height(height))
    } else {
        Box(modifier.height(height), contentAlignment = Alignment.Center) {
            Caption(placeholder, size = 14, color = InkSoft)
        }
    }
}

/** The system's "remove animations" setting: then engravings stay still. */
@Composable
private fun reducedMotion(): Boolean {
    val resolver = LocalContext.current.contentResolver
    return remember { android.provider.Settings.Global.getFloat(resolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }
}

private val thumbs = android.util.LruCache<String, ImageBitmap>(120)

private fun decodeThumb(path: String, px: Int): ImageBitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(path, bounds)
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= px * 2) sample *= 2
    return BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })?.asImageBitmap()
}

/**
 * A small engraving for a journal row. Shows only what is already on the phone, so scrolling the
 * journal never orders a paid picture; [fetch] lets free ones (fugleramme's bird plates) download.
 */
@Composable
fun Thumb(request: ArtRequest, fetch: Boolean, modifier: Modifier = Modifier, size: Dp = 56.dp) {
    val art = LocalContext.current.graph.art
    val version by art.version.collectAsState()
    val px = with(androidx.compose.ui.platform.LocalDensity.current) { size.roundToPx() }
    val image by produceState<ImageBitmap?>(null, request, version) {
        val file = art.cached(request) ?: if (fetch) art.load(request) else null
        value = file?.let { f ->
            thumbs.get(f.path) ?: withContext(Dispatchers.IO) { decodeThumb(f.path, px) }?.also { thumbs.put(f.path, it) }
        }
    }
    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        val bmp = image
        if (bmp != null) {
            Image(bmp, contentDescription = request.subject, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
        } else {
            Box(Modifier.size(size * 0.6f).border(0.8.dp, InkSoft.copy(alpha = 0.3f)))
        }
    }
}
