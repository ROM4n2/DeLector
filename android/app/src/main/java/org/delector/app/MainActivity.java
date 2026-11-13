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
import android.os.Process;
import android.os.SystemClock;
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
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
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
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import android.speech.tts.Voice;

public class MainActivity extends AppCompatActivity {
    private WebView webView;
    private LinearLayout splashLayout;
    private TextView statusTextView;
    private Button retryButton;
    private ProgressBar progressBar;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private volatile boolean isServerReady = false;
    /** Python 侧抛异常后服务永远不会就绪，用它让轮询与重载立刻停手并保留错误信息 */
    private volatile String fatalError = null;
    /** 冷启动 TTFD 只上报一次；JS 桥回调来自 WebView 线程，必须原子判定。 */
    private final AtomicBoolean ttfdReported = new AtomicBoolean(false);
    private int reloadAttempts = 0;
    /**
     * 首帧导航是否以失败告终（{@code onReceivedError} 且 isForMainFrame）。
     *
     * 为什么要这个标志：SW 的 network-first 在 fetch 时**不经过** {@code shouldInterceptRequest}
     * （那是 WebView 的网络栈，SW 的 fetch 走的是另一条路），所以「服务还没 listening 就导航」
     * 会拿到 ERR_FAILED —— 页面上根本不是我们的骨架，只剩 Chromium 的错误页。旧的
     * 「已经在应用 origin 上 ⇒ skip_reload」判据分不清「页面正常」与「页面是错误页」，
     * 于是服务就绪后也不重试，用户停在错误页（2026-11-11 模拟器实证：退出重进必现）。
     */
    private volatile boolean mainFrameLoadFailed = false;
    /** 「窗口里没有我们的 JS」只允许补载一次，避免抖动成循环。 */
    private boolean reloadedForMissingPage = false;
    /**
     * debug 注入专用状态（release 恒 false，不参与任何生产判据）：
     * `injectedFirstPollDone` 让 `once` 档只耗尽第一轮；`firstPaintSkipped` 记录「首帧被注入跳过」，
     * 供就绪分支判定必须走 loadUrl —— 否则 revealWebView 会掀开一个从未加载过 URL 的空白 WebView，
     * 「重试生效」与「重试把页面搞白」在截图上就无法区分。
     */
    private boolean injectedFirstPollDone = false;
    private boolean firstPaintSkipped = false;
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
     * 页面在 Python 起来之前先以 8000 为 origin 加载。
     * 静态资源由 {@link #maybeServeAppStatic} 从 APK 的 assets/static 直接交付，
     * `/api/*` 一律不拦、走真实网络，交给 article-store 的退避重试接管。
     *
     * 端口被占时 start.py 会顺延（8002+）；此时就绪轮询会导航到真实端口，
     * 该场景是二次导航，不计入 navCount==1 的样本。
     */
    private static final int APP_PORT = 8000;
    private static final String APP_ORIGIN = "http://127.0.0.1:" + APP_PORT;
    /** 首个内容帧只报一次（commit 可能重复回调）。 */
    private final AtomicBoolean appContentFrameReported = new AtomicBoolean(false);
    /** 就绪钩子只注入一次，避免 onPageFinished 与轮询重复 evaluateJavascript。 */
    private final AtomicBoolean readyHookInjected = new AtomicBoolean(false);

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

    /**
     * 冷启动 TTFD 探针：只记录、不改启动行为。
     *
     * TTFD = 首条 `.article-row` 完成首次绘制的时刻。Web 侧在双 rAF 之后回调，
     * 避免把「innerHTML 已插入但尚未绘制」误记成可见；Java 侧以进程启动为基准算毫秒，
     * 并 reportFullyDrawn() 让系统口径（logcat `Fully drawn`）与之一致。
     *
     * 测量方法与基线见 docs/agents/architecture.md「启动指标 TTFD」。
     */
    public class StartupReportBridge {
        @JavascriptInterface
        public void onFirstArticleVisible(String pageEpochMs) {
            if (!ttfdReported.compareAndSet(false, true)) {
                return;
            }
            long ttfdMs = SystemClock.elapsedRealtime() - Process.getStartElapsedRealtime();
            StartupProbe.markNav("ttfd", pageEpochMs);
            Log.i("DeLector", "TTFD_FIRST_ARTICLE_MS=" + ttfdMs
                    + " TTFD_ROW_EPOCH=" + pageEpochMs);
            mainHandler.post(MainActivity.this::reportFullyDrawn);
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        StartupProbe.mark("activity_create");

        // Keep screen on during study & shadowing
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // 1. Root Container (FrameLayout)
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#FAF8F5"));

        // 2. Setup WebView & Native TTS
        webView = new WebView(this);
        // 注意：这里必须保持 VISIBLE。GONE/INVISIBLE 的 WebView 不绘制、rAF 会被节流，
        // 首帧回调会被推迟；视觉上由后加的 splash 整层遮住（同底色）。
        webView.setVisibility(View.VISIBLE);

        // 只让 debug 包可被 `chrome://inspect` 连上：release 必须保持关闭，
        // 否则任何能连 adb 的机器都拿到了页面状态与 JS 执行权。
        // 用 BuildConfig.DEBUG 而不是裸 true —— 后者会连 release 一起打开，
        // 且没有任何运行期症状，只有 tests/test_android_webview_policy.py 的静态断言能拦住。
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        nativeTTS = new NativeTTSBridge();
        webView.addJavascriptInterface(nativeTTS, "AndroidNativeTTS");
        webView.addJavascriptInterface(new StartupReportBridge(), "DeLectorStartup");

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
            /**
             * 只拦应用 origin 上的静态骨架（{@link #maybeServeAppStatic}）；
             * 返回 null 的请求（尤其 `/api/*`）原样放行给真实网络。
             */
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (request != null && request.getUrl() != null) {
                    WebResourceResponse response = maybeServeAppStatic(request.getUrl());
                    if (response != null) {
                        return response;
                    }
                }
                return super.shouldInterceptRequest(view, request);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                StartupProbe.markNav("page_finished", url);
                // 兜底：正常路径由 onPageCommitVisible 先撤；这里只防「commit 回调缺失」。
                if (isServerReady || isAppOriginUrl(url)) {
                    revealWebView();
                }
                // 兜底：服务在页面 JS 就绪前就已 ready（冷启极快时），就绪轮询那次注入会
                // 因为函数还不存在而落空，这里补一次。
                if (isServerReady && isAppOriginUrl(url)) {
                    notifyServerReadyInPage();
                }
            }

            /**
             * 真实页首帧内容已提交：撤 splash 的正常信号。
             *
             * S1 起真实页在 Python 就绪前就加载，因此不能再用 isServerReady 当撤场条件；
             * 应用 origin 的第一次 commit 后再等一个动画帧，即「可绘制的首帧」。
             * 旧实现是 loadUrl 之后固定 200ms 撤场，慢设备上会在首帧前露出白屏/半成品。
             */
            @Override
            public void onPageCommitVisible(WebView view, String url) {
                StartupProbe.markNav("commit", url);
                if (isAppOriginUrl(url)) {
                    if (appContentFrameReported.compareAndSet(false, true)) {
                        view.postOnAnimation(() -> {
                            StartupProbe.markNav("content_frame", "app_first_content_frame");
                            revealWebView();
                        });
                    }
                    return;
                }
                if (isServerReady && isLocalServerUrl(url)) {
                    view.postOnAnimation(MainActivity.this::revealWebView);
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    // 记住「当前页面是错误页」：服务就绪时必须强制重载，不能因为 URL 已经是
                    // 应用 origin 就当成加载成功（见 mainFrameLoadFailed 的字段注释）。
                    mainFrameLoadFailed = true;
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
        StartupProbe.mark("webview_attached");

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

        progressBar = new ProgressBar(this);
        progressBar.setIndeterminate(true);

        statusTextView = new TextView(this);
        statusTextView.setText("正在启动德语语言学引擎与本地词库...");
        statusTextView.setTextColor(Color.parseColor("#8E8271"));
        statusTextView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        statusTextView.setPadding(0, 24, 0, 0);
        statusTextView.setGravity(Gravity.CENTER);

        // 终态专用的重试按钮：默认隐藏，只在就绪预算耗尽时出现。
        // 不能把点击挂在 statusTextView 上 —— 它开了 setTextIsSelectable(true)（让用户能复制
        // 错误去转述），而可选中文本在首次触摸时进入选择态并吞掉 onClick：2026-11-13 arm64
        // 真机实测，点一次 `poll_begin` 不变、点第二次才重启轮询。
        retryButton = new Button(this);
        retryButton.setText("重试");
        retryButton.setVisibility(View.GONE);

        splashLayout.addView(titleView);
        splashLayout.addView(subtitleView);
        splashLayout.addView(progressBar);
        splashLayout.addView(statusTextView);
        splashLayout.addView(retryButton);

        root.addView(splashLayout, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(root);
        StartupProbe.mark("content_view_set");

        // 不等 Python：先用应用 origin 加载真实页。
        // 静态资源由拦截层从 APK assets/static 交付；/api/* 走真实网络，
        // 首个请求被拒后由 article-store 的退避重试接管（navCount 保持 1）。
        StartupProbe.navZero();
        if (fakeStuckStart()) {
            // 注入态：不发起首帧，splash 会一直留着，终态文案才可见。
            StartupProbe.markNav("loadurl_skipped_for_fault_injection", APP_ORIGIN + "/");
            firstPaintSkipped = true;
        } else {
            StartupProbe.markNav("loadurl_first_paint", APP_ORIGIN + "/");
            webView.loadUrl(APP_ORIGIN + "/");
        }

        // 4. Background Initialization (Assets Extraction + Python Server Launch)
        StartupProbe.mark("server_thread_spawn");
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
        StartupProbe.mark("init_begin");
        try {
            // A. Copy assets to internal storage if needed
            File dataDir = getFilesDir();
            File staticDir = new File(dataDir, "static");
            syncStaticAssets(dataDir, staticDir);
            StartupProbe.mark("assets_sync_done");

            // B. 清掉上一轮残留的端口文件：否则 8000 被占后可能先读到旧端口再轮询失败。
            File portFile = new File(dataDir, PORT_FILE_NAME);
            if (portFile.exists() && !portFile.delete()) {
                Log.w("DeLector", "无法清理上一轮的端口文件: " + portFile);
            }

            // C. Start Chaquopy Python runtime
            StartupProbe.mark("python_start_begin");
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            StartupProbe.mark("python_start_done");

            Python py = Python.getInstance();
            PyObject osModule = py.getModule("os");
            osModule.get("environ").callAttr("__setitem__", "DELECTOR_DATA_DIR", dataDir.getAbsolutePath());
            osModule.get("environ").callAttr("__setitem__", "STATIC_DIR", staticDir.getAbsolutePath());
            // 让 Python 把真实端口写进这个文件：8000 被占时它会顺延（start.py:_android_ready）。
            osModule.get("environ").callAttr("__setitem__", PORT_FILE_ENV, portFile.getAbsolutePath());

            // D. Start server in background thread
            new Thread(() -> {
                try {
                    StartupProbe.mark("python_main_invoked");
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

    /** 是否应用自身 origin（S1 的静态承载路径）。 */
    private boolean isAppOriginUrl(String url) {
        return url != null && url.startsWith(APP_ORIGIN + "/");
    }

    /**
     * 把应用 origin 上的页面骨架从 APK 的 assets/static 直接交付。
     *
     * 只认 `/`、`/style.css`、`/js/*` 三类静态请求；其余（尤其 `/api/*`）
     * 一律返回 null 交给真实网络，绝不在本地伪造接口响应。
     * 返回的响应带 `Cache-Control: no-cache`，避免 WebView 的 HTTP 缓存
     * 把上一版 APK 的静态资源冒充成本次结果（SW 侧另有 network-first 兜底）。
     */
    private WebResourceResponse maybeServeAppStatic(Uri uri) {
        if (uri == null || !"http".equals(uri.getScheme())) {
            return null;
        }
        if (!"127.0.0.1".equals(uri.getHost()) || uri.getPort() != APP_PORT) {
            return null;
        }
        String path = uri.getPath();
        if (path == null) {
            return null;
        }
        String assetPath;
        if ("/".equals(path) || "/index.html".equals(path)) {
            assetPath = "static/index.html";
        } else if ("/style.css".equals(path)) {
            assetPath = "static/style.css";
        } else if (path.startsWith("/js/")) {
            assetPath = "static" + path;
        } else {
            return null; // /api/* 与其余请求必须走真实网络
        }
        try {
            InputStream stream = getAssets().open(assetPath);
            WebResourceResponse response = new WebResourceResponse(
                    mimeTypeFor(assetPath), "UTF-8", stream);
            Map<String, String> headers = new HashMap<>();
            headers.put("Cache-Control", "no-cache");
            response.setResponseHeaders(headers);
            return response;
        } catch (IOException e) {
            // 资产缺失时退回真实网络，让页面明确失败，而不是拿到空响应。
            return null;
        }
    }

    private static String mimeTypeFor(String assetPath) {
        if (assetPath.endsWith(".html")) {
            return "text/html";
        }
        if (assetPath.endsWith(".css")) {
            return "text/css";
        }
        return "text/javascript";
    }

    /**
     * 把「服务已就绪」告诉页面（仅新路径）。页面侧只做两件事：
     * ① 打断退避等待、立刻重试一次（复用 store.retryIfWaiting，不是第二套重试）；
     * ② 补注册 Service Worker（页面在 Python 就绪前加载，load 时的注册必然失败）。
     *
     * 必须在 UI 线程调用。函数还不存在（页面 JS 尚未执行）时把幂等标记复位，
     * 交给 onPageFinished 的兜底再补一次，不在这里写轮询。
     */
    private void notifyServerReadyInPage() {
        if (!readyHookInjected.compareAndSet(false, true)) {
            return;
        }
        final String js = "(function(){try{return window.notifyServerReady"
                + " ? String(window.notifyServerReady()) : 'missing';}catch(e){return 'err';}})()";
        webView.evaluateJavascript(js, value -> {
            StartupProbe.markNav("ready_notify", value);
            // 'missing'（不是我们的页面）/ 'err'（页面 JS 抛异常）/ null 都要复位 CAS：
            // 否则这个一次性标记会让 onPageFinished 的兜底注入永远不再发生，失败无终态。
            if (value == null || "\"missing\"".equals(value) || "\"err\"".equals(value)) {
                readyHookInjected.set(false);
                if (!reloadedForMissingPage && serverPort > 0) {
                    scheduleMissingPageCheck();
                }
            }
        });
    }

    /**
     * 就绪信号注入后发现窗口里没有我们的 JS 时，隔一拍再确认一次；仍没有就补载一次。
     *
     * 为什么不直接重载：页面可能只是还在解析（慢设备/大页面），立刻重载会白跑一次导航。
     * 为什么不靠 {@code pageFinished}：Chromium 的错误页**不会**触发 onPageFinished
     * （2026-11-11 模拟器实测：整轮 logcat 没有 page_finished），所以无法用它区分
     * 「还在加载」与「页面就是错误页」。改用「同一条探针再问一次」加一拍延迟来区分。
     */
    private void scheduleMissingPageCheck() {
        mainHandler.postDelayed(() -> {
            if (!isServerReady || reloadedForMissingPage || serverPort <= 0) {
                return;
            }
            final String probe = "(function(){try{return window.notifyServerReady"
                    + " ? String(window.notifyServerReady()) : 'missing';}catch(e){return 'err';}})()";
            webView.evaluateJavascript(probe, value -> {
                if (!"\"missing\"".equals(value) || reloadedForMissingPage) {
                    return;
                }
                reloadedForMissingPage = true;
                StartupProbe.markNav("loadurl_retry_missing_page", serverBaseUrl(serverPort));
                webView.loadUrl(serverBaseUrl(serverPort));
            });
        }, 1500);
    }

    /**
     * debug 包的故障注入开关：模拟「服务进程起来了但 HTTP 永不就绪」。
     *
     * 两档，都只在 BuildConfig.DEBUG 下生效（release 由 R8 折叠掉整段，正式产物不含）：
     * - `delector_fake_stuck=true`：每一轮轮询都耗尽预算 ⇒ 终态常驻，用来点验终态文案与按钮；
     * - `delector_fake_stuck_once=true`：只**第一轮**耗尽；点「重试」启动的第二轮走真实预算
     *   ⇒ 页面会真的加载出来，「重试是否重启了轮询」因此可被观察验证。
     *
     * 为什么需要 once 档：`fake_stuck` 下点击后必然立刻再耗尽，截图与 UI 在「点了没反应」
     * 和「点了但立刻又失败」之间无法区分（2026-11-13 arm64 真机点检的实际卡点）。
     *
     * 用法：
     *   adb shell am start -n org.delector.app/.MainActivity --ez delector_fake_stuck true
     *   adb shell am start -n org.delector.app/.MainActivity --ez delector_fake_stuck_once true
     */
    private boolean fakeStuckStart() {
        return BuildConfig.DEBUG && (getIntent().getBooleanExtra("delector_fake_stuck", false)
                || getIntent().getBooleanExtra("delector_fake_stuck_once", false));
    }

    /** 永远不就绪档：点重试也只会在终态里打转。 */
    private boolean fakeStuckAlways() {
        return BuildConfig.DEBUG && getIntent().getBooleanExtra("delector_fake_stuck", false);
    }

    /** 只第一轮耗尽档：第二轮（重试）恢复正常预算。 */
    private boolean fakeStuckFirstPollOnly() {
        return BuildConfig.DEBUG && getIntent().getBooleanExtra("delector_fake_stuck_once", false);
    }

    /**
     * 撤掉 splash、露出 WebView。只允许 UI 线程调用（WebViewClient 回调 / postOnAnimation）。
     * 用「幂等 + 只改可见性」保证重复调用安全，不引入任何新的计时假设。
     *
     * WebView 常驻 VISIBLE（GONE/INVISIBLE 不绘制、rAF 被节流，首帧会推迟），所以幂等标记
     * 改看 splash 的可见性。
     */
    private void revealWebView() {
        if (splashLayout.getVisibility() != View.VISIBLE) {
            return;
        }
        StartupProbe.markNav("reveal", "splash_hidden");
        splashLayout.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
    }

    /** 只认端口文件给出的那个本地服务地址，避免把超时/外链页面的 commit 当成首屏。 */
    private boolean isLocalServerUrl(String url) {
        return serverPort > 0 && url != null && url.startsWith(serverBaseUrl(serverPort));
    }

    private void pollServerReadiness(File dataDir) {
        StartupProbe.mark("poll_begin");
        // 注入态把预算置 0（等价于「等到预算用完也没起来」）；正常路径仍走策略类，
        // 守卫 test_main_activity_uses_policy_instead_of_literals 要求这一行必须在此方法体内。
        // 注入态第一轮把预算置 0（等价于「等到预算用完也没起来」）；`once` 档在点「重试」
        // 触发的第二轮恢复真实预算，于是能观察到「终态 → 真实页面」的翻转。
        // 注意 MUST 保留 StartupReadinessPolicy.maxAttempts() 在本方法体内（接线守卫要求）。
        final boolean injectedZeroBudget =
                fakeStuckAlways() || (fakeStuckFirstPollOnly() && !injectedFirstPollDone);
        injectedFirstPollDone = true;
        final int attempts = injectedZeroBudget ? 0 : StartupReadinessPolicy.maxAttempts();
        for (int i = 0; i < attempts; i++) {
            if (fatalError != null) {
                return; // 服务不可能再就绪，别用超时文案盖掉真实错误
            }
            // 端口文件由 Python 在选定端口、组好 server 后写入；拿到前只等，不猜 8000。
            if (serverPort <= 0) {
                serverPort = readServerPort(dataDir);
                if (serverPort > 0) {
                    StartupProbe.mark("port_file_read");
                }
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

                    if (StartupReadinessPolicy.isReadyStatus(code)) {
                        StartupProbe.mark("settings_200");
                        isServerReady = true;
                        final int readyPort = serverPort;
                        mainHandler.post(() -> {
                            if (readyPort == APP_PORT && !mainFrameLoadFailed && !firstPaintSkipped) {
                                // 页面已在应用 origin 上加载：不再导航，接管交给 store 的重试。
                                // 这里只补一次状态（splash 通常已被首个内容帧撤掉）。
                                // `firstPaintSkipped` 只可能来自 debug 注入：那时首帧没发起，
                                // 走这条分支会 revealWebView 掀开空白页，必须落到下面的 loadUrl。
                                StartupProbe.markNav("skip_reload", "app_origin_ready");
                                statusTextView.setText("服务已就绪");
                                revealWebView();
                                // 就绪信号驱动：打断退避等待里的下一次重试，别让末档 1600ms
                                // 把接管拖到就绪点之后 ~0.7s；顺带补注册 SW（页面加载时注册已失败）。
                                notifyServerReadyInPage();
                                return;
                            }
                            statusTextView.setText("服务已就绪，正在加载工作台...");
                            // 两条路都会到这里：① 端口顺延（8000 被占）；② 首帧导航失败后强制重载
                            // （此时页面是 Chromium 错误页，必须重来一次）。两者都是二次导航，
                            // 不计入 navCount==1。
                            final boolean retryAfterError = mainFrameLoadFailed;
                            mainFrameLoadFailed = false;
                            StartupProbe.navZero();
                            StartupProbe.markNav(
                                    retryAfterError ? "loadurl_retry_after_error" : "loadurl",
                                    serverBaseUrl(readyPort));
                            webView.loadUrl(serverBaseUrl(readyPort));
                        });
                        return;
                    }
                } catch (Exception ignored) {
                }
            }

            try {
                // 前 50 次 120ms 快轮询（服务正常约 2.3s 就绪），之后退回 600ms；
                // 总预算与改造前 60×600ms 一致，超时语义不变。
                Thread.sleep(StartupReadinessPolicy.pollIntervalMs(i));
            } catch (InterruptedException ignored) {
            }
        }

        if (fatalError != null) {
            return;
        }
        final int timeoutPort = serverPort;
        mainHandler.post(() -> {
            // 预算已耗尽：Java 侧不再轮询，必须给「可见终态 + 可点重试」，不能假进行中。
            progressBar.setVisibility(View.GONE);
            statusTextView.setTextIsSelectable(true);
            // 文案保持可选中（用户要能把错误转述给开发者），但点击交给独立 Button：
            // 可选中文本会吞掉首次触摸的 onClick，挂在它身上的重试等于要点两下才生效。
            statusTextView.setText(timeoutPort > 0
                    ? "服务启动超时（端口 " + timeoutPort + "），已停止连接。"
                    : "服务启动超时，已停止连接。");
            retryButton.setVisibility(View.VISIBLE);
            retryButton.setOnClickListener(v -> {
                retryButton.setOnClickListener(null);
                retryButton.setVisibility(View.GONE);
                statusTextView.setText("正在重新连接本地服务...");
                progressBar.setVisibility(View.VISIBLE);
                new Thread(() -> pollServerReadiness(getFilesDir())).start();
            });
            if (timeoutPort > 0 && timeoutPort != APP_PORT) {
                // 页面已在 8000 上加载时不再二次导航：留在快照 + 重试 UI 上。
                StartupProbe.navZero();
                StartupProbe.markNav("loadurl_timeout", serverBaseUrl(timeoutPort));
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
