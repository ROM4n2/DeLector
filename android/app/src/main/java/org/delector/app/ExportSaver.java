package org.delector.app;

import android.annotation.SuppressLint;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.database.sqlite.SQLiteConstraintException;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.util.Log;
import android.webkit.MimeTypeMap;
import android.webkit.URLUtil;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 把 WebView 的下载请求落到用户能看到的地方 —— 不用 DownloadManager。
 *
 * 为什么弃用 DownloadManager（v4.7.3）：
 *
 * 1. 它是系统 DownloadProvider 进程里的一个 Job。Android 16 官方点名
 *    「JobScheduler 配额优化会影响 DownloadManager 调度的任务」，而它在
 *    enqueue() 阶段失败的形态是**同步抛异常**——SecurityException("Unsupported path")、
 *    IllegalArgumentException("Unknown URL content://downloads/my_downloads")、
 *    Android 13+ 缺 POST_NOTIFICATIONS 的通知拦截，全都是 OEM 与版本相关的地雷，
 *    且失败原因只在 logcat 里，用户只能看到一个没有上下文的 Toast。
 * 2. 服务端就跑在本 App 进程里（127.0.0.1:8000），走系统下载服务是绕远路：
 *    多一次跨进程、多一套存储权限与路径校验、多一个可能被停用的系统组件。
 *
 * 换成 App 进程内 HttpURLConnection 自取之后，上面每一条都消失了。
 * 代价是要自己处理落盘、命名与重试 —— 就是这个文件剩下的内容。
 */
public final class ExportSaver {

    private static final String TAG = "DeLectorExport";

    /** 本地服务，连不上就是服务没起来，不用等太久。 */
    private static final int CONNECT_TIMEOUT_MS = 10_000;
    /** export_anki_deck 要写整个牌组，慢的那次是它。 */
    private static final int READ_TIMEOUT_MS = 180_000;
    private static final int BUFFER_BYTES = 64 * 1024;
    private static final int SNIFF_BYTES = 512;
    /** 超过这个尺寸就不再先落临时文件，直接流式写 MediaStore，避开 cacheDir 配额。 */
    private static final long DIRECT_WRITE_THRESHOLD = 32L * 1024 * 1024;
    /** WebView 同一次导航可能回调两次 onDownloadStart，不去重会导出两份。 */
    private static final int DEDUP_WINDOW_MS = 2000;
    private static final int NAME_COLLISION_RETRIES = 5;

    private static final Pattern CD_FILENAME_STAR =
            Pattern.compile("filename\\*=([^']*)''([^;]+)", Pattern.CASE_INSENSITIVE);
    private static final Pattern CD_FILENAME =
            Pattern.compile("filename=([^;]+)", Pattern.CASE_INSENSITIVE);

    /** 单线程串行：服务端是单 worker uvicorn + GIL，两个大导出并发只会互相拖慢。
     *  static 保证 Activity 因旋转等原因重建时队列不丢。 */
    private static final ExecutorService EXEC = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "delector-export");
        t.setPriority(Thread.NORM_PRIORITY - 1);
        return t;
    });

    private static String lastUrl;
    private static long lastStartMs;

    private ExportSaver() {
    }

    public interface Reporter {
        /** 已经在主线程上，可以直接弹 Toast。 */
        void onSuccess(String message);

        /** 已经在主线程上，可以直接弹 Toast。 */
        void onFailure(String url, int httpCode, Throwable error);
    }

    public static synchronized void start(Context context, String url, String userAgent,
                                          String contentDisposition, String mimeType,
                                          Reporter reporter) {
        if (url == null || url.isEmpty()) {
            reporter.onFailure(url, -1, new IOException("下载 URL 为空"));
            return;
        }
        long now = System.currentTimeMillis();
        if (url.equals(lastUrl) && now - lastStartMs < DEDUP_WINDOW_MS) {
            return;
        }
        lastUrl = url;
        lastStartMs = now;

        final Context appCtx = context.getApplicationContext();
        final String name = pickFileName(url, contentDisposition, mimeType);
        final String mime = TextUtils.isEmpty(mimeType) ? "application/octet-stream" : mimeType;
        EXEC.execute(() -> new Job(appCtx, url, userAgent, name, mime, reporter).run());
    }

    /** 一次导出的全部状态。Runnable 而不是内部类方法：状态集中，清理路径只有一处。 */
    private static final class Job implements Runnable {
        private final Context ctx;
        private final String url;
        private final String userAgent;
        private final String name;
        private final String mime;
        private final Reporter reporter;

        /** 已插入但还没 publish 的 MediaStore 行。非空意味着外层 catch 必须删掉它，
         *  否则会留下一行 IS_PENDING=1、对其他应用不可见的孤儿。成功路径清成 null。 */
        private PendingRow pendingRow;

        Job(Context ctx, String url, String userAgent, String name, String mime, Reporter reporter) {
            this.ctx = ctx;
            this.url = url;
            this.userAgent = userAgent;
            this.name = name;
            this.mime = mime;
            this.reporter = reporter;
        }

        @Override
        public void run() {
            HttpURLConnection conn = null;
            File tmp = null;
            int code = -1;
            try {
                conn = openConnection();
                code = conn.getResponseCode();
                if (code < 200 || code >= 300) {
                    String reason = conn.getResponseMessage();
                    throw new IOException("HTTP " + code + (reason == null ? "" : " " + reason));
                }
                final String respType = conn.getHeaderField("Content-Type");
                final long declared = conn.getContentLength();

                if (Build.VERSION.SDK_INT >= 29 && declared > DIRECT_WRITE_THRESHOLD) {
                    // 超大文件：不能先落临时文件（cacheDir 配额），只能直写 + 写后复验。
                    // 全程不再用 try/catch 包：清理统一交给最外层 catch，
                    // 否则 throw t 的精确重抛会把 IOException 泄漏进 Runnable.run()。
                    PendingRow row = insertPending(name, mime);
                    pendingRow = row;
                    writeAndPublish(row, new BufferedInputStream(conn.getInputStream(), BUFFER_BYTES));
                    verifySaved(row, respType);
                    pendingRow = null;                 // 成功，所有权已交出
                    reporter.onSuccess("已保存到「下载」目录: " + row.name);
                    return;
                }

                tmp = File.createTempFile("dl_", ".bin", ctx.getCacheDir());
                Sniff sniff = new Sniff();
                long total = 0;
                try (InputStream in = new BufferedInputStream(conn.getInputStream(), BUFFER_BYTES);
                     OutputStream out = new FileOutputStream(tmp)) {
                    total = copyWithSniff(in, out, sniff);
                }
                if (total == 0) {
                    throw new IOException("服务端返回了 0 字节");
                }
                // 先判定内容再建 MediaStore 行：顺序反了会在 IS_PENDING=1 期间被杀时
                // 留下一个永久不可见、且无 READ 权限根本扫不出来清理的孤儿行。
                String bad = checkContent(sniff, name, respType);
                if (bad != null) {
                    throw new IOException(bad);
                }

                if (Build.VERSION.SDK_INT >= 29) {
                    PendingRow row = insertPending(name, mime);
                    pendingRow = row;
                    try (InputStream in = new FileInputStream(tmp)) {
                        writeAndPublish(row, in);
                    }
                    pendingRow = null;                 // 成功，所有权已交出
                    reporter.onSuccess("已保存到「下载」目录: " + row.name
                            + "（" + Math.max(1, total / 1024) + " KB）");
                } else {
                    File dst = saveToAppExternalDir(tmp, name);
                    reporter.onSuccess("已保存: " + dst.getAbsolutePath()
                            + "（" + Math.max(1, total / 1024) + " KB）");
                }
            } catch (Throwable t) {
                if (pendingRow != null) {
                    deleteRow(pendingRow.uri);
                }
                reporter.onFailure(url, code, t);
            } finally {
                if (tmp != null) {
                    tmp.delete();
                }
                if (conn != null) {
                    conn.disconnect();
                }
            }
        }

        private HttpURLConnection openConnection() throws IOException {
            HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setInstanceFollowRedirects(true);
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Accept", "*/*");
            // 别让系统 HTTP 缓存把上一次的 404 错误体喂给我们
            conn.setRequestProperty("Cache-Control", "no-cache");
            if (userAgent != null) {
                conn.setRequestProperty("User-Agent", userAgent);
            }
            return conn;
        }

        /** 已插入、但 IS_PENDING 仍为 1 的 MediaStore 行，以及最终使用的显示名。 */
        private static final class PendingRow {
            final Uri uri;
            final String name;

            PendingRow(Uri uri, String name) {
                this.uri = uri;
                this.name = name;
            }
        }

        @SuppressLint("NewApi")
        private PendingRow insertPending(String displayName, String mimeType) throws IOException {
            ContentResolver r = ctx.getContentResolver();
            IOException last = null;
            for (int i = 0; i < NAME_COLLISION_RETRIES; i++) {
                String candidate = (i == 0) ? displayName : addSuffix(displayName, " (" + (i + 1) + ")");
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.Downloads.DISPLAY_NAME, candidate);
                cv.put(MediaStore.Downloads.MIME_TYPE, mimeType);
                cv.put(MediaStore.Downloads.IS_PENDING, 1);
                // 故意不设 RELATIVE_PATH：部分早期 Android 10 版本与 OEM 对
                // Download/ 子目录的校验不一致，会让 insert 直接抛
                // IllegalArgumentException。不设时默认落在 Download/，与旧行为一致。
                try {
                    Uri uri = r.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                    if (uri != null) {
                        return new PendingRow(uri, candidate);
                    }
                    last = new IOException("MediaStore.insert 返回 null（存储未挂载？）");
                } catch (SQLiteConstraintException | IllegalStateException
                        | IllegalArgumentException e) {
                    // 同名冲突（前两者）或列值被拒（后者）：换后缀重试。
                    // 换名字就能成功的一类失败，不该让整次导出挂掉。
                    last = new IOException("MediaStore 创建文件失败: " + e.getMessage());
                }
            }
            throw last != null ? last : new IOException("MediaStore 创建文件失败");
        }

        /** 顺序是硬约束：写完 → 关流 → 才把 IS_PENDING 置 0。
         *  流没关就 update，某些版本会静默影响 0 行，文件永远对其他应用不可见。 */
        @SuppressLint("NewApi")
        private void writeAndPublish(PendingRow row, InputStream in) throws IOException {
            ContentResolver r = ctx.getContentResolver();
            try (OutputStream out = r.openOutputStream(row.uri, "w")) {
                if (out == null) {
                    throw new IOException("openOutputStream 返回 null（存储未挂载？）");
                }
                copy(in, out);
                out.flush();
            }
            ContentValues done = new ContentValues();
            done.put(MediaStore.Downloads.IS_PENDING, 0);
            if (r.update(row.uri, done, null, null) != 1) {
                throw new IOException("IS_PENDING 复位失败（0 行受影响）");
            }
        }

        /** 直写路径没有嗅探机会，写完后开回来读前若干字节验一遍。 */
        @SuppressLint("NewApi")
        private void verifySaved(PendingRow row, String respType) throws IOException {
            Sniff sniff = new Sniff();
            try (InputStream in = ctx.getContentResolver().openInputStream(row.uri)) {
                if (in == null) {
                    throw new IOException("写后校验失败：无法读回刚保存的文件");
                }
                sniff.len = in.read(sniff.head);
                if (sniff.len < 0) {
                    sniff.len = 0;
                }
            }
            String bad = checkContent(sniff, row.name, respType);
            if (bad != null) {
                throw new IOException(bad);
            }
        }

        private void deleteRow(Uri uri) {
            try {
                ctx.getContentResolver().delete(uri, null, null);
            } catch (Throwable ignored) {
                // 清理失败没有补救手段，至少不能让它盖掉真正的失败原因
            }
        }

        /** API 19+ 零权限、无对话框。只服务 API 24-28 这台极小的存量设备。 */
        private File saveToAppExternalDir(File tmp, String displayName) throws IOException {
            File dir = ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
            if (dir == null) {
                throw new IOException("外部存储不可用");
            }
            if (!dir.exists() && !dir.mkdirs()) {
                throw new IOException("无法创建目录: " + dir);
            }
            File dst = new File(dir, displayName);
            try (InputStream in = new FileInputStream(tmp);
                 OutputStream out = new FileOutputStream(dst)) {
                copy(in, out);
                out.flush();
            }
            return dst;
        }
    }

    // ── 内容自检 ──────────────────────────────────────────────────────────────

    private static final class Sniff {
        final byte[] head = new byte[SNIFF_BYTES];
        int len;
    }

    /** 返回 null 表示内容正常；非 null 是要直接给用户看的原因。 */
    static String checkContent(Sniff sniff, String displayName, String respType) {
        if (sniff.len == 0) {
            return "内容异常: 服务端返回空文件";
        }
        String head = new String(sniff.head, 0, Math.min(sniff.len, SNIFF_BYTES),
                StandardCharsets.UTF_8).trim();
        String lower = displayName.toLowerCase(Locale.US);

        // (1) FastAPI 的 HTTPException 体 —— token 失效/过期时拿到的就是它。
        //     这是本自检存在的主要理由：那份 JSON 会被毫不知情地存成「备份」。
        if (head.startsWith("{\"detail\"") || (head.startsWith("{") && head.contains("\"detail\""))) {
            return "内容异常: 服务端返回的是错误 JSON（下载链接已失效），请重新导出";
        }
        // (2) 扩展名与响应 Content-Type 不符：.apkg/.md 却收到 JSON，同样是错误体
        String ct = (respType == null) ? "" : respType.toLowerCase(Locale.US).split(";")[0].trim();
        if (!ct.isEmpty() && ct.startsWith("application/json")
                && (lower.endsWith(".apkg") || lower.endsWith(".md"))) {
            int dot = lower.lastIndexOf('.');
            return "内容异常: 期望 " + lower.substring(dot) + " 却收到 application/json（HTTP 错误体）";
        }
        // (3) 魔数：Anki 包本质是 zip
        if (lower.endsWith(".apkg")) {
            boolean zip = sniff.len >= 4
                    && (sniff.head[0] & 0xFF) == 0x50
                    && (sniff.head[1] & 0xFF) == 0x4B
                    && (sniff.head[2] & 0xFF) == 0x03
                    && (sniff.head[3] & 0xFF) == 0x04;
            if (!zip) {
                return "内容异常: Anki 包不是有效的 ZIP（前 4 字节不是 PK\\x03\\x04）";
            }
        }
        // (4) JSON 首字符
        if (lower.endsWith(".json")) {
            char c = head.isEmpty() ? ' ' : head.charAt(0);
            if (c != '{' && c != '[') {
                return "内容异常: JSON 首字符是 '" + c + "'";
            }
        }
        return null;
    }

    // ── 文件名 ────────────────────────────────────────────────────────────────

    /**
     * URLUtil.guessFileName 只做第二选择。它在本项目会失效：
     * /api/backup/download/&lt;token&gt; 的末段是 URL-safe base64，没有点号，
     * guessUrl 拿到的就是 token 本身。所以自己解析 Content-Disposition 优先。
     */
    static String pickFileName(String url, String contentDisposition, String mimeType) {
        String n = parseContentDispositionFilename(contentDisposition);
        if (isBlank(n)) {
            n = URLUtil.guessFileName(url, contentDisposition, mimeType);
        }
        if (isBlank(n) || "downloadfile".equals(n) || n.indexOf('.') < 0) {
            String path = (url == null) ? null : Uri.parse(url).getPath();
            if (path != null) {
                String last = path.substring(path.lastIndexOf('/') + 1);
                if (last.indexOf('.') > 0) {
                    n = last;
                }
            }
        }
        if (isBlank(n) || n.indexOf('.') < 0) {
            n = "DeLector_Export_"
                    + new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date())
                    + guessExtension(url, mimeType);
        }
        return sanitizeFileName(n);
    }

    static String parseContentDispositionFilename(String contentDisposition) {
        if (contentDisposition == null) {
            return null;
        }
        // RFC 5987: filename*=UTF-8''%E5%A4%87%E4%BB%BD.json
        Matcher m = CD_FILENAME_STAR.matcher(contentDisposition);
        if (m.find()) {
            try {
                return java.net.URLDecoder.decode(m.group(2).trim(), "UTF-8");
            } catch (Exception ignored) {
                // 落到下面的普通形式
            }
        }
        // 普通形式: filename=xxx.json 或 filename="xxx.json"
        m = CD_FILENAME.matcher(contentDisposition);
        if (m.find()) {
            String v = m.group(1).trim();
            if (v.length() >= 2 && v.charAt(0) == '"' && v.charAt(v.length() - 1) == '"') {
                v = v.substring(1, v.length() - 1);
            }
            v = v.trim();
            return v.isEmpty() ? null : v;
        }
        return null;
    }

    /** ext4/sdcardfs 只禁 '/'，但外置 SD 常是 exFAT/FAT32，Windows 保留字符一并换掉。 */
    static String sanitizeFileName(String raw) {
        String n = raw.replaceAll("[\\\\/:*?\"<>|\\u0000-\\u001F]", "_");
        n = n.replaceAll("^\\.+", "").replaceAll("[.\\s]+$", "");
        if (n.isEmpty() || ".".equals(n) || "..".equals(n)) {
            n = "delector_export";
        }
        if (n.length() > 120) {          // 给 255 字节限制留足余量
            int dot = n.lastIndexOf('.');
            String ext = (dot > 0) ? n.substring(dot) : "";
            n = n.substring(0, Math.max(1, 120 - ext.length())) + ext;
        }
        return n;
    }

    static String guessExtension(String url, String mimeType) {
        String bare = (mimeType == null) ? "" : mimeType.split(";")[0].trim();
        String ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(bare);
        if (ext != null && !ext.isEmpty()) {
            return "." + ext;
        }
        String p = (url == null) ? "" : url.toLowerCase(Locale.US);
        if (p.contains("apkg")) {
            return ".apkg";
        }
        if (p.contains("backup")) {
            return ".json";
        }
        if (p.contains("guide")) {
            return ".md";
        }
        return ".bin";
    }

    static String addSuffix(String name, String suffix) {
        int dot = name.lastIndexOf('.');
        if (dot > 0) {
            return name.substring(0, dot) + suffix + name.substring(dot);
        }
        return name + suffix;
    }

    // ── 工具 ──────────────────────────────────────────────────────────────────

    private static long copyWithSniff(InputStream in, OutputStream out, Sniff sniff)
            throws IOException {
        byte[] buf = new byte[BUFFER_BYTES];
        long total = 0;
        int n;
        while ((n = in.read(buf)) > 0) {
            if (sniff.len < sniff.head.length) {
                int keep = Math.min(n, sniff.head.length - sniff.len);
                System.arraycopy(buf, 0, sniff.head, sniff.len, keep);
                sniff.len += keep;
            }
            out.write(buf, 0, n);
            total += n;
        }
        out.flush();
        return total;
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[BUFFER_BYTES];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
        }
        out.flush();
    }

    private static boolean isBlank(String s) {
        return s == null || s.trim().isEmpty();
    }

    /** 给调用方在 Toast 之外留一条能拿到 logcat 时的线索。 */
    static void logFailure(String url, int httpCode, Throwable t) {
        Log.e(TAG, "export failed: url=" + url + " http=" + httpCode, t);
    }
}
