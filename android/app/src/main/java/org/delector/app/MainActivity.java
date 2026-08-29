package org.delector.app;

import android.annotation.SuppressLint;
import android.app.DownloadManager;
import android.content.Intent;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Set;
import android.speech.tts.Voice;

public class MainActivity extends AppCompatActivity {
    private WebView webView;
    private LinearLayout splashLayout;
    private TextView statusTextView;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private volatile boolean isServerReady = false;
    /** Python 侧抛异常后服务永远不会就绪，用它让轮询与重载立刻停手并保留错误信息 */
    private volatile String fatalError = null;
    private int reloadAttempts = 0;
    private long lastBackPressTime = 0;
    private NativeTTSBridge nativeTTS;
    private ValueCallback<Uri[]> filePathCallback;
    private static final int FILE_CHOOSER_REQUEST_CODE = 1001;

    public class NativeTTSBridge {
        private TextToSpeech tts;
        private volatile boolean isInitialized = false;

        public NativeTTSBridge() {
            tts = new TextToSpeech(getApplicationContext(), status -> {
                if (status == TextToSpeech.SUCCESS) {
                    isInitialized = trySelectGermanVoice();
                }
            });
        }

        /**
         * 挑一个能说德语的 voice：先试德语 Locale，不行就遍历已装语音找德语能力的。
         * 国内机型常没有 Google TTS 德语 Locale 条目，但引擎可能带德语语音（getVoices() API 21+）。
         */
        private boolean trySelectGermanVoice() {
            int result = tts.setLanguage(Locale.GERMAN);
            if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                result = tts.setLanguage(Locale.GERMANY);
            }
            if (result != TextToSpeech.LANG_MISSING_DATA && result != TextToSpeech.LANG_NOT_SUPPORTED) {
                return true;
            }
            Set<Voice> voices = tts.getVoices();
            if (voices != null) {
                for (Voice v : voices) {
                    Locale loc = v.getLocale();
                    if (loc != null && "de".equalsIgnoreCase(loc.getLanguage())) {
                        if (tts.setVoice(v) == TextToSpeech.SUCCESS) {
                            return true;
                        }
                    }
                }
            }
            return false;
        }

        @JavascriptInterface
        public boolean speak(String text, float rate) {
            if (tts != null && isInitialized && text != null && !text.trim().isEmpty()) {
                tts.setSpeechRate(rate);
                int res = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null,
                        "delector_speech_" + System.currentTimeMillis());
                return res == TextToSpeech.SUCCESS;
            }
            return false;
        }

        @JavascriptInterface
        public boolean isReady() {
            return isInitialized;
        }

        @JavascriptInterface
        public void stop() {
            if (tts != null) {
                tts.stop();
            }
        }

        public void shutdown() {
            if (tts != null) {
                tts.stop();
                tts.shutdown();
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Keep screen on during study & shadowing
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // 1. Root Container (FrameLayout)
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#FAF8F5"));

        // 2. Setup WebView & Native TTS
        webView = new WebView(this);
        webView.setVisibility(View.GONE);
        nativeTTS = new NativeTTSBridge();
        webView.addJavascriptInterface(nativeTTS, "AndroidNativeTTS");

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback,
                    FileChooserParams fileChooserParams) {
                if (MainActivity.this.filePathCallback != null) {
                    MainActivity.this.filePathCallback.onReceiveValue(null);
                    MainActivity.this.filePathCallback = null;
                }
                MainActivity.this.filePathCallback = filePathCallback;

                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                String[] mimetypes = { "text/plain", "text/markdown", "text/*", "image/svg+xml", "image/*",
                        "application/json", "application/octet-stream" };
                if (fileChooserParams != null && fileChooserParams.getAcceptTypes() != null
                        && fileChooserParams.getAcceptTypes().length > 0
                        && !fileChooserParams.getAcceptTypes()[0].isEmpty()) {
                    intent.putExtra(Intent.EXTRA_MIME_TYPES, fileChooserParams.getAcceptTypes());
                } else {
                    intent.putExtra(Intent.EXTRA_MIME_TYPES, mimetypes);
                }

                try {
                    startActivityForResult(Intent.createChooser(intent, "选择文件"), FILE_CHOOSER_REQUEST_CODE);
                } catch (Exception e) {
                    MainActivity.this.filePathCallback = null;
                    Toast.makeText(MainActivity.this, "无法打开文件选择器: " + e.getMessage(), Toast.LENGTH_SHORT).show();
                    return false;
                }
                return true;
            }
        });

        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setAllowContentAccess(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);

        // Native Download Listener for Anki APKG, Study Guide HTML, JSON Backups
        webView.setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            try {
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                String filename = URLUtil.guessFileName(url, contentDisposition, mimetype);
                if (filename == null || filename.isEmpty() || filename.equals("downloadfile")) {
                    filename = "DeLector_Export_" + System.currentTimeMillis()
                            + (url.contains("apkg") ? ".apkg" : ".json");
                }
                request.setMimeType(mimetype);
                request.addRequestHeader("User-Agent", userAgent);
                request.setDescription("DeLector 德语学术导出资产");
                request.setTitle(filename);
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);

                DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                if (dm != null) {
                    dm.enqueue(request);
                    Toast.makeText(MainActivity.this, "已保存至系统「下载」目录: " + filename, Toast.LENGTH_LONG).show();
                }
            } catch (Exception e) {
                Toast.makeText(MainActivity.this, "下载异常: " + e.getMessage(), Toast.LENGTH_SHORT).show();
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                if (isServerReady) {
                    splashLayout.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    checkAndReloadServer();
                }
            }
        });

        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        // 3. Setup Splash / Loading View
        splashLayout = new LinearLayout(this);
        splashLayout.setOrientation(LinearLayout.VERTICAL);
        splashLayout.setGravity(Gravity.CENTER);
        splashLayout.setBackgroundColor(Color.parseColor("#FAF8F5"));
        splashLayout.setPadding(48, 48, 48, 48);

        TextView titleView = new TextView(this);
        titleView.setText("DeLector");
        titleView.setTextColor(Color.parseColor("#1B1E28"));
        titleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 36);
        titleView.setTypeface(null, android.graphics.Typeface.BOLD);
        titleView.setGravity(Gravity.CENTER);

        TextView subtitleView = new TextView(this);
        subtitleView.setText("德语欧标精读与备考工作台");
        subtitleView.setTextColor(Color.parseColor("#7A6854"));
        subtitleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        subtitleView.setPadding(0, 12, 0, 36);
        subtitleView.setGravity(Gravity.CENTER);

        ProgressBar progressBar = new ProgressBar(this);
        progressBar.setIndeterminate(true);

        statusTextView = new TextView(this);
        statusTextView.setText("正在启动德语语言学引擎与本地词库...");
        statusTextView.setTextColor(Color.parseColor("#8E8271"));
        statusTextView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        statusTextView.setPadding(0, 24, 0, 0);
        statusTextView.setGravity(Gravity.CENTER);

        splashLayout.addView(titleView);
        splashLayout.addView(subtitleView);
        splashLayout.addView(progressBar);
        splashLayout.addView(statusTextView);

        root.addView(splashLayout, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(root);

        // 4. Background Initialization (Assets Extraction + Python Server Launch)
        new Thread(this::initAndStartServer).start();
    }

    private void initAndStartServer() {
        try {
            // A. Copy assets to internal storage if needed
            File dataDir = getFilesDir();
            File staticDir = new File(dataDir, "static");
            syncStaticAssets(dataDir, staticDir);

            // B. Start Chaquopy Python runtime
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }

            Python py = Python.getInstance();
            PyObject osModule = py.getModule("os");
            osModule.get("environ").callAttr("__setitem__", "DELECTOR_DATA_DIR", dataDir.getAbsolutePath());
            osModule.get("environ").callAttr("__setitem__", "STATIC_DIR", staticDir.getAbsolutePath());

            // C. Start server in background thread
            new Thread(() -> {
                try {
                    py.getModule("start").callAttr("main");
                } catch (Throwable t) {
                    t.printStackTrace();
                    reportFatal("Python 引擎异常", t);
                }
            }).start();

            // D. Poll for server readiness
            pollServerReadiness();

        } catch (Throwable t) {
            // Throwable 而非 Exception：Python.start() 载入原生库失败抛的是 UnsatisfiedLinkError
            t.printStackTrace();
            reportFatal("启动异常", t);
        }
    }

    /**
     * 记录不可恢复的失败并把完整信息留在屏幕上。
     * 之前的实现只 setText，随后会被"服务启动超时"覆盖，导致真实的 Python traceback 永远看不到。
     */
    private void reportFatal(String stage, Throwable t) {
        fatalError = stage + ": " + t;
        mainHandler.post(() -> {
            statusTextView.setTextIsSelectable(true);
            statusTextView.setText(fatalError + "\n\n请把这段信息反馈给开发者（adb logcat 有完整堆栈）。");
        });
    }

    private void pollServerReadiness() {
        for (int i = 0; i < 60; i++) {
            if (fatalError != null) {
                return; // 服务不可能再就绪，别用超时文案盖掉真实错误
            }
            try {
                URL url = new URL("http://127.0.0.1:8000/api/settings");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setConnectTimeout(800);
                conn.setReadTimeout(800);
                conn.setRequestMethod("GET");
                int code = conn.getResponseCode();
                conn.disconnect();

                if (code >= 200 && code < 400) {
                    isServerReady = true;
                    mainHandler.post(() -> {
                        statusTextView.setText("服务已就绪，正在加载工作台...");
                        webView.loadUrl("http://127.0.0.1:8000");
                        splashLayout.postDelayed(() -> {
                            splashLayout.setVisibility(View.GONE);
                            webView.setVisibility(View.VISIBLE);
                        }, 200);
                    });
                    return;
                }
            } catch (Exception ignored) {
            }

            try {
                Thread.sleep(600);
            } catch (InterruptedException ignored) {
            }
        }

        if (fatalError != null) {
            return;
        }
        mainHandler.post(() -> {
            statusTextView.setText("服务启动超时，正在重试连接...");
            webView.loadUrl("http://127.0.0.1:8000");
        });
    }

    private void checkAndReloadServer() {
        // 上限防止服务真的起不来时无限 reload（每秒一次，永不停止）
        if (isServerReady || fatalError != null || ++reloadAttempts > 10) {
            if (!isServerReady && fatalError == null) {
                mainHandler.post(() -> {
                    splashLayout.setVisibility(View.VISIBLE);
                    webView.setVisibility(View.GONE);
                    statusTextView.setTextIsSelectable(true);
                    statusTextView.setText("本地服务无法连接（127.0.0.1:8000）。\n请用 adb logcat 查看 python.stderr 中的堆栈。");
                });
            }
            return;
        }
        mainHandler.postDelayed(() -> webView.loadUrl("http://127.0.0.1:8000"), 1000);
    }

    private void copyAssetFolder(String srcName, File dstDir) {
        try {
            AssetManager assetManager = getAssets();
            String[] fileList = assetManager.list(srcName);
            if (fileList == null || fileList.length == 0) {
                // Copy single file
                copyAssetFile(srcName, dstDir);
            } else {
                if (!dstDir.exists()) {
                    dstDir.mkdirs();
                }
                for (String filename : fileList) {
                    String subSrc = srcName.isEmpty() ? filename : srcName + "/" + filename;
                    File subDst = new File(dstDir, filename);
                    String[] subList = assetManager.list(subSrc);
                    if (subList != null && subList.length > 0) {
                        copyAssetFolder(subSrc, subDst);
                    } else {
                        copyAssetFile(subSrc, subDst);
                    }
                }
            }
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private void copyAssetFile(String srcPath, File dstFile) {
        if (dstFile.exists() && dstFile.length() > 0) {
            return; // Already copied
        }
        File parent = dstFile.getParentFile();
        if (parent != null && !parent.exists()) {
            parent.mkdirs();
        }
        try (InputStream in = getAssets().open(srcPath);
                OutputStream out = new FileOutputStream(dstFile)) {
            byte[] buf = new byte[8192];
            int len;
            while ((len = in.read(buf)) > 0) {
                out.write(buf, 0, len);
            }
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    /**
     * 版本感知解包 (v4.4.5)。
     *
     * APK 覆盖安装不清空 getFilesDir()，而 copyAssetFile() 见到目标已存在就跳过，
     * 于是升级后旧的 HTML/CSS/JS 永远不被覆盖。更麻烦的是新增文件仍会照常拷入，
     * 设备最终停在"新旧混合"状态——比全旧更难排查，因为版本自洽性没了。
     * 这也是为什么用户只有卸载重装才能看到新前端：卸载才会清 filesDir。
     *
     * 前端的 ?v= 查询串对此无效：磁盘上那份文件本身就是旧的，
     * 请求 URL 和响应内容是一对自洽的旧配对，浏览器没有任何理由怀疑。
     *
     * 用版本标记文件做闸门：versionCode 一致走原来的跳过快路径（冷启动不多做 I/O），
     * 不一致就把整个 static/ 删掉重解包。
     */
    private void syncStaticAssets(File dataDir, File staticDir) {
        String expected = String.valueOf(BuildConfig.VERSION_CODE);
        File marker = new File(dataDir, "static.version");

        if (expected.equals(readVersionMarker(marker))) {
            copyAssetFolder("static", staticDir); // 快路径：只补缺失文件
            return;
        }

        // 版本对不上（升级 / 降级 / 标记丢失）→ 整目录重来，不做逐文件比对：
        // 资产才几 MB，而漏掉一个文件的代价是又一次"卸载重装才好"。
        deleteStaticDir(dataDir, staticDir);
        copyAssetFolder("static", staticDir);

        // 只在解包确实产出了入口文件时才写标记。copyAssetFolder 把 IOException
        // 咽进 printStackTrace，没有返回值可信，所以宁可下次启动重试一遍，
        // 也不要把一次半途失败的解包记成"已是最新"。
        if (new File(staticDir, "index.html").exists()) {
            writeVersionMarker(marker, expected);
        }
    }

    private String readVersionMarker(File marker) {
        if (!marker.isFile()) {
            return null;
        }
        try (InputStream in = new FileInputStream(marker)) {
            byte[] buf = new byte[32];
            int len = in.read(buf);
            if (len <= 0) {
                return null;
            }
            return new String(buf, 0, len, StandardCharsets.UTF_8).trim();
        } catch (IOException e) {
            e.printStackTrace();
            return null; // 读不出来就当版本不匹配，重解包是安全的那一侧
        }
    }

    private void writeVersionMarker(File marker, String versionCode) {
        try (OutputStream out = new FileOutputStream(marker)) {
            out.write(versionCode.getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    /**
     * 只删 filesDir/static/，别的一律不碰。
     *
     * delector.db 和 progress.db 就躺在 filesDir 根目录、与 static/ 平级，
     * 装着用户全部学习数据（文章、词卡语法卡、笔记、FSRS 进度、统计）。
     * 删错一级 = 不可恢复地清空这些。所以这里硬编码校验目标身份，
     * 不接受任何调用方传进来的路径。
     */
    private void deleteStaticDir(File dataDir, File staticDir) {
        if (!staticDir.exists()) {
            return;
        }
        File expected = new File(dataDir, "static");
        if (!staticDir.getAbsolutePath().equals(expected.getAbsolutePath())) {
            return; // 身份不符，宁可不清理也不误删
        }
        deleteRecursively(staticDir);
    }

    private static void deleteRecursively(File target) {
        File[] children = target.listFiles();
        if (children != null) {
            for (File child : children) {
                deleteRecursively(child);
            }
        }
        target.delete();
    }

    @Override
    public void onBackPressed() {
        if (webView == null || !isServerReady) {
            super.onBackPressed();
            return;
        }

        String jsCheck = "(function() {" +
                "  var modal = document.querySelector('#modal-overlay.open, #settings-overlay.open, .modal-overlay.open, #quiz-overlay:not(.hidden), #cloze-modal:not(.hidden), #polish-overlay:not(.hidden), #version-preview-overlay:not(.hidden)');"
                +
                "  if (modal) {" +
                "    if (window.closeModal) window.closeModal();" +
                "    if (window.closeSettingsModal) window.closeSettingsModal();" +
                "    if (window.closeQuizOverlay) window.closeQuizOverlay();" +
                "    if (window.closeClozeModal) window.closeClozeModal();" +
                "    if (window.closePolishOverlay) window.closePolishOverlay();" +
                "    if (window.closeVersionPreview) window.closeVersionPreview();" +
                "    return 'modal';" +
                "  }" +
                "  var drawer = document.querySelector('#drawer.open, #syntax-drawer.open, #writer-panel.open');" +
                "  if (drawer) {" +
                "    if (window.closeDrawer) window.closeDrawer();" +
                "    if (window.closeSyntaxDrawer) window.closeSyntaxDrawer();" +
                "    if (window.closeWriterMobilePanel) window.closeWriterMobilePanel();" +
                "    return 'drawer';" +
                "  }" +
                "  var activeView = document.querySelector('.view.active');" +
                "  if (activeView && activeView.id !== 'view-home') {" +
                "    if (window.show) window.show('home');" +
                "    return 'view';" +
                "  }" +
                "  return 'none';" +
                "})()";

        webView.evaluateJavascript(jsCheck, result -> {
            if (result != null && (result.contains("modal") || result.contains("drawer") || result.contains("view"))) {
                return;
            }
            long now = System.currentTimeMillis();
            if (now - lastBackPressTime < 2000) {
                finish();
            } else {
                lastBackPressTime = now;
                Toast.makeText(MainActivity.this, "再按一次退出 DeLector", Toast.LENGTH_SHORT).show();
            }
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_REQUEST_CODE) {
            if (filePathCallback != null) {
                Uri[] results = null;
                if (resultCode == RESULT_OK && data != null) {
                    Uri dataUri = data.getData();
                    if (dataUri != null) {
                        results = new Uri[] { dataUri };
                    }
                }
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
        }
    }

    @Override
    protected void onDestroy() {
        if (nativeTTS != null) {
            nativeTTS.shutdown();
        }
        super.onDestroy();
    }
}
