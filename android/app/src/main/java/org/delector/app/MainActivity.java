package org.delector.app;

import android.annotation.SuppressLint;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
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
    /** Python 侧选定并由 {@link #PORT_FILE_ENV} 回传的监听端口；0 表示还没拿到。 */
    private volatile int serverPort = 0;
    private static final String PORT_FILE_NAME = "server-port.txt";
    /** 与 start.py 的 PORT_FILE_ENV 保持同一字符串，缺一不可（由 pytest 静态守卫钉住）。 */
    private static final String PORT_FILE_ENV = "DELECTOR_PORT_FILE";

    /**
     * 导出结果的出口。回调发生在 ExportSaver 的单线程池上，所以一律 post 回主线程。
     * 失败时除 Toast 外还写剪贴板：没有 adb logcat 的场合，剪贴板是用户唯一能把
     * 完整错误转述给开发者的通道（Android 11+ 起第三方文件管理器访问不到
     * /Android/data/，写诊断日志文件这条路是断的）。
     */
    private final ExportSaver.Reporter exportReporter = new ExportSaver.Reporter() {
        @Override
        public void onSuccess(String message) {
            mainHandler.post(() ->
                    Toast.makeText(MainActivity.this, message, Toast.LENGTH_LONG).show());
        }

        @Override
        public void onFailure(String url, int httpCode, Throwable error) {
            ExportSaver.logFailure(url, httpCode, error);   // 万一哪天能拿到 logcat，堆栈还在
            String msg = buildExportErrorMessage(url, httpCode, error);
            mainHandler.post(() -> {
                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                copyToClipboard(msg);
            });
        }
    };

    /** 四行结构化错误：接口 / HTTP 码 / 异常类名 + 原因，一眼能定位到根因。 */
    private static String buildExportErrorMessage(String url, int httpCode, Throwable error) {
        String path = "(未知)";
        try {
            String p = Uri.parse(url).getPath();          // 丢掉 host/port
            if (p != null) {
                // token 只留前 6 位：既看得出是备份还是 workbench，又不整段泄露
                path = p.replaceAll("([0-9A-Za-z_-]{6})[0-9A-Za-z_-]{10,}", "$1…");
            }
        } catch (Throwable ignored) {
        }
        String reason = error.getMessage();
        if (reason == null) {
            reason = "";
        } else if (reason.length() > 120) {
            reason = reason.substring(0, 120) + "…";
        }
        return "下载失败\n"
                + "接口: " + path + "\n"
                + "HTTP: " + (httpCode > 0 ? String.valueOf(httpCode) : "无响应") + "\n"
                + "错误: " + error.getClass().getSimpleName()
                + (reason.isEmpty() ? "" : " | " + reason);
    }

    private void copyToClipboard(String text) {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
            if (cm != null) {
                cm.setPrimaryClip(ClipData.newPlainText("DeLector 下载错误", text));
            }
        } catch (Throwable t) {
            Log.w("DeLector", "剪贴板不可用，错误信息只留在 Toast 里", t);
        }
    }

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

        // 只让 debug 包可被 `chrome://inspect` 连上：release 必须保持关闭，
        // 否则任何能连 adb 的机器都拿到了页面状态与 JS 执行权。
        // 用 BuildConfig.DEBUG 而不是裸 true —— 后者会连 release 一起打开，
        // 且没有任何运行期症状，只有 tests/test_android_webview_policy.py 的静态断言能拦住。
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
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

        // 四个导出入口（备份 JSON / Workbench JSON / Anki .apkg / 学习指南 .md）
        // 全走这一个回调。落盘交给 ExportSaver：App 进程内自己发 HTTP 请求再写
        // MediaStore，不再经系统 DownloadManager —— 后者在 Android 16 上会在
        // enqueue() 直接抛异常，且失败原因只在 logcat 里。
        webView.setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) ->
                ExportSaver.start(this, url, userAgent, contentDisposition, mimetype, exportReporter));

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

            /**
             * 所有导航的统一出口：站内（回环 / 相对路径 / file://）留在 WebView，
             * 外站 http(s) 与 mailto: 交给系统 App。判定本身在 WebUrlPolicy。
             *
             * 两个重载都要覆写：API 24+ 走 WebResourceRequest，旧路径（以及
             * target="_blank" 在未开多窗口支持时）会落到 String 版本。
             */
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (request == null || request.getUrl() == null) {
                    return false;
                }
                return handleExternalNavigation(request.getUrl().toString());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleExternalNavigation(url);
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

    /**
     * 外链的实际交付点。返回 true 表示这次导航已被消费，WebView 不再加载。
     *
     * 判定在 WebUrlPolicy（纯 Java、可单测），这里只负责"交给谁"。
     * Intent 解析失败（设备没装浏览器 / 邮件 App）时静默吞掉并记日志：此时返回 false
     * 会让 WebView 去加载一个它本来就打不开的地址，把工作台替换成错误页 ——
     * 比"点了没反应"更糟，而且会打断正在进行的阅读状态。
     */
    private boolean handleExternalNavigation(String url) {
        if (!WebUrlPolicy.shouldOpenExternally(url)) {
            return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Throwable t) {
            Log.w("DeLector", "没有可处理该链接的应用: " + url, t);
        }
        return true;
    }

    private void initAndStartServer() {
        try {
            // A. Copy assets to internal storage if needed
            File dataDir = getFilesDir();
            File staticDir = new File(dataDir, "static");
            syncStaticAssets(dataDir, staticDir);

            // B. 清掉上一轮残留的端口文件：否则 8000 被占后可能先读到旧端口再轮询失败。
            File portFile = new File(dataDir, PORT_FILE_NAME);
            if (portFile.exists() && !portFile.delete()) {
                Log.w("DeLector", "无法清理上一轮的端口文件: " + portFile);
            }

            // C. Start Chaquopy Python runtime
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }

            Python py = Python.getInstance();
            PyObject osModule = py.getModule("os");
            osModule.get("environ").callAttr("__setitem__", "DELECTOR_DATA_DIR", dataDir.getAbsolutePath());
            osModule.get("environ").callAttr("__setitem__", "STATIC_DIR", staticDir.getAbsolutePath());
            // 让 Python 把真实端口写进这个文件：8000 被占时它会顺延（start.py:_android_ready）。
            osModule.get("environ").callAttr("__setitem__", PORT_FILE_ENV, portFile.getAbsolutePath());

            // D. Start server in background thread
            new Thread(() -> {
                try {
                    py.getModule("start").callAttr("main");
                } catch (Throwable t) {
                    t.printStackTrace();
                    reportFatal("Python 引擎异常", t);
                }
            }).start();

            // E. Poll for server readiness
            pollServerReadiness(dataDir);

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

    /**
     * 从 Python 写下的端口文件里取真实监听端口。
     * 8000 被别的程序占用时 start.py 会顺延到 8002+，这里必须跟着走，不能写死。
     */
    private int readServerPort(File dataDir) {
        File file = new File(dataDir, PORT_FILE_NAME);
        try (FileInputStream in = new FileInputStream(file)) {
            byte[] buf = new byte[(int) Math.min(file.length(), 16)];
            int n = in.read(buf);
            if (n <= 0) {
                return 0;
            }
            int port = Integer.parseInt(new String(buf, 0, n, StandardCharsets.US_ASCII).trim());
            return (port > 0 && port <= 65535) ? port : 0;
        } catch (Exception ignored) {
            return 0;
        }
    }

    private String serverBaseUrl(int port) {
        return "http://127.0.0.1:" + port;
    }

    private void pollServerReadiness(File dataDir) {
        for (int i = 0; i < 60; i++) {
            if (fatalError != null) {
                return; // 服务不可能再就绪，别用超时文案盖掉真实错误
            }
            // 端口文件由 Python 在选定端口、组好 server 后写入；拿到前只等，不猜 8000。
            if (serverPort <= 0) {
                serverPort = readServerPort(dataDir);
            }
            if (serverPort > 0) {
                try {
                    URL url = new URL(serverBaseUrl(serverPort) + "/api/settings");
                    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                    conn.setConnectTimeout(800);
                    conn.setReadTimeout(800);
                    conn.setRequestMethod("GET");
                    int code = conn.getResponseCode();
                    conn.disconnect();

                    if (code >= 200 && code < 400) {
                        isServerReady = true;
                        final int readyPort = serverPort;
                        mainHandler.post(() -> {
                            statusTextView.setText("服务已就绪，正在加载工作台...");
                            webView.loadUrl(serverBaseUrl(readyPort));
                            splashLayout.postDelayed(() -> {
                                splashLayout.setVisibility(View.GONE);
                                webView.setVisibility(View.VISIBLE);
                            }, 200);
                        });
                        return;
                    }
                } catch (Exception ignored) {
                }
            }

            try {
                Thread.sleep(600);
            } catch (InterruptedException ignored) {
            }
        }

        if (fatalError != null) {
            return;
        }
        final int timeoutPort = serverPort;
        mainHandler.post(() -> {
            statusTextView.setText(timeoutPort > 0
                    ? "服务启动超时（端口 " + timeoutPort + "），正在重试连接..."
                    : "服务启动超时，正在重试连接...");
            if (timeoutPort > 0) {
                webView.loadUrl(serverBaseUrl(timeoutPort));
            }
        });
    }

    private void checkAndReloadServer() {
        // 上限防止服务真的起不来时无限 reload（每秒一次，永不停止）
        if (isServerReady || fatalError != null || ++reloadAttempts > 10) {
            if (!isServerReady && fatalError == null) {
                final int failedPort = serverPort;
                mainHandler.post(() -> {
                    splashLayout.setVisibility(View.VISIBLE);
                    webView.setVisibility(View.GONE);
                    statusTextView.setTextIsSelectable(true);
                    statusTextView.setText("本地服务无法连接（127.0.0.1"
                            + (failedPort > 0 ? ":" + failedPort : "")
                            + "）。\n请用 adb logcat 查看 python.stderr 中的堆栈。");
                });
            }
            return;
        }
        if (serverPort <= 0) {
            serverPort = readServerPort(getFilesDir());
        }
        final int reloadPort = serverPort;
        if (reloadPort <= 0) {
            // 端口还没交出来（Python 仍在启动）：不加载 0 端口，留给下一轮重试。
            mainHandler.postDelayed(this::checkAndReloadServer, 1000);
            return;
        }
        mainHandler.postDelayed(() -> webView.loadUrl(serverBaseUrl(reloadPort)), 1000);
    }

    private void copyAssetFolder(String srcName, File dstDir) throws IOException {
        AssetManager assetManager = getAssets();
        String[] fileList = assetManager.list(srcName);
        if (fileList == null || fileList.length == 0) {
            // Copy single file
            copyAssetFile(srcName, dstDir);
            return;
        }
        if (!dstDir.exists() && !dstDir.mkdirs()) {
            throw new IOException("无法创建目录：" + dstDir);
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

    private void copyAssetFile(String srcPath, File dstFile) throws IOException {
        if (dstFile.exists() && dstFile.length() > 0) {
            return; // Already copied
        }
        File parent = dstFile.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("无法创建目录：" + parent);
        }
        try (InputStream in = getAssets().open(srcPath);
                OutputStream out = new FileOutputStream(dstFile)) {
            byte[] buf = new byte[8192];
            int len;
            while ((len = in.read(buf)) > 0) {
                out.write(buf, 0, len);
            }
        }
    }

    /**
     * 版本 + 内容指纹感知解包（静态资源自证）。
     *
     * APK 覆盖安装不清空 getFilesDir()，而 copyAssetFile() 见到目标已存在就跳过，
     * 于是升级后旧的 HTML/CSS/JS 永远不被覆盖。更麻烦的是新增文件仍会照常拷入，
     * 设备最终停在"新旧混合"状态——比全旧更难排查，因为版本自洽性没了。
     *
     * 只比 versionCode 不够：debug/本地包的 versionCode 常年不变，内容却可能已改。
     * 所以 marker 写成 {@code versionCode + ":" + 资产内容指纹}；指纹来自构建期
     * 写入 APK 的 {@code static/asset-fingerprint.txt}。旧包没有该文件时退回纯
     * versionCode 语义，避免每次启动都失配重解包。
     *
     * 解包安全：先完整解到兄弟暂存目录，校验入口文件后再整体换入；任何一步失败
     * 都保留旧目录并记录到 {@code static.version.error}，绝不把 static/ 留在半成品。
     * 只碰 filesDir/static 及其暂存/备份目录，用户数据库一律不碰。
     */
    private void syncStaticAssets(File dataDir, File staticDir) {
        if (!isCanonicalStaticDir(dataDir, staticDir)) {
            Log.w("DeLector", "静态资源目录身份不符，拒绝解包：" + staticDir);
            return;
        }

        File staging = new File(dataDir, ".delector-static.unpack");
        File backup = new File(dataDir, ".delector-static.old");
        // 上次换入过程中被杀：static 可能暂时不在，先恢复备份再继续，避免把唯一副本删掉。
        recoverStaticDir(staticDir, staging, backup);

        String fingerprint = readBundledAssetsFingerprint();
        String expected = fingerprint.isEmpty()
                ? String.valueOf(BuildConfig.VERSION_CODE)
                : BuildConfig.VERSION_CODE + ":" + fingerprint;
        File marker = new File(dataDir, "static.version");

        if (expected.equals(readVersionMarker(marker))) {
            // 快路径：只补缺失文件；补齐失败也不影响现有目录。
            try {
                copyAssetFolder("static", staticDir);
            } catch (IOException e) {
                Log.w("DeLector", "快路径补齐静态资源失败，继续使用现有目录", e);
            }
            return;
        }

        try {
            copyAssetFolder("static", staging);
            File entry = new File(staging, "index.html");
            if (!entry.isFile() || entry.length() == 0) {
                throw new IOException("解包结果缺少 index.html");
            }

            // 新目录已经完整，才动旧目录。先把旧目录移开，再换入新目录；
            // 换入失败时把旧目录搬回来，保证「至少还能跑旧前端」。
            if (staticDir.exists() && !staticDir.renameTo(backup)) {
                throw new IOException("无法移开旧静态目录");
            }
            if (!staging.renameTo(staticDir)) {
                if (backup.exists() && !backup.renameTo(staticDir)) {
                    Log.e("DeLector", "恢复旧静态目录失败，备份保留在 " + backup);
                }
                throw new IOException("无法启用新静态目录");
            }
            deleteRecursively(backup);
            writeVersionMarker(marker, expected);
            clearUnpackError(dataDir);
        } catch (IOException | RuntimeException e) {
            deleteRecursively(staging);
            recordUnpackError(dataDir, expected, e);
            Log.e("DeLector", "静态资源解包失败，继续使用旧目录", e);
        }
    }

    /** 读构建期写入 APK 的静态资源内容指纹；旧包没有该文件时返回空串。 */
    private String readBundledAssetsFingerprint() {
        try (InputStream in = getAssets().open("static/asset-fingerprint.txt")) {
            byte[] buf = new byte[64];
            int len = in.read(buf);
            if (len <= 0) {
                return "";
            }
            return new String(buf, 0, len, StandardCharsets.UTF_8).trim();
        } catch (IOException e) {
            return ""; // 旧包没有指纹文件：退回纯 versionCode 语义
        }
    }

    private String readVersionMarker(File marker) {
        if (!marker.isFile()) {
            return null;
        }
        try (InputStream in = new FileInputStream(marker)) {
            byte[] buf = new byte[64];
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

    private void writeVersionMarker(File marker, String expected) {
        try (OutputStream out = new FileOutputStream(marker)) {
            out.write(expected.getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    /** 换入中断后的恢复：static 缺失就先把备份搬回来，备份搬不回来就绝不删它。 */
    private void recoverStaticDir(File staticDir, File staging, File backup) {
        if (!staticDir.exists() && backup.exists()) {
            if (backup.renameTo(staticDir)) {
                Log.w("DeLector", "已从备份恢复旧静态目录");
            } else {
                Log.e("DeLector", "无法从备份恢复静态目录，保留备份：" + backup);
                return;
            }
        }
        deleteRecursively(staging);
        if (staticDir.exists()) {
            deleteRecursively(backup);
        }
    }

    /** 失败原因落在 filesDir 根目录；只写我们自己命名的文件。 */
    private void recordUnpackError(File dataDir, String expected, Exception error) {
        File errorFile = new File(dataDir, "static.version.error");
        String detail = "expected=" + expected
                + "\ntime=" + System.currentTimeMillis()
                + "\nerror=" + error.getClass().getSimpleName() + ": " + error.getMessage();
        try (OutputStream out = new FileOutputStream(errorFile)) {
            out.write(detail.getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            Log.w("DeLector", "写入解包失败原因失败", e);
        }
    }

    private void clearUnpackError(File dataDir) {
        File errorFile = new File(dataDir, "static.version.error");
        if (errorFile.exists() && !errorFile.delete()) {
            Log.w("DeLector", "无法清理旧的解包失败记录：" + errorFile);
        }
    }

    private static boolean isCanonicalStaticDir(File dataDir, File staticDir) {
        File expected = new File(dataDir, "static");
        return staticDir.getAbsolutePath().equals(expected.getAbsolutePath());
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
