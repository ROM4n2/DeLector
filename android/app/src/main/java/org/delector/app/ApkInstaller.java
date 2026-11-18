package org.delector.app;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * APK 安装预检 + PackageInstaller 会话（ADR-0034 D3）。
 *
 * 边界：
 * - 只接受应用私有目录 {@code files/updates/} 下的 .apk，防止任意路径被安装；
 * - 包名、versionCode 严格递增、签名与已安装应用一致，任一不符都拒绝（系统兜底之外的可读原因）；
 * - 安装动作仍由系统确认，这里**没有**任何静默安装代码。
 *
 * 返回码与前端约定：
 * BAD_PATH / BAD_APK / PACKAGE_MISMATCH / VERSION_NOT_INCREASED / SIGNATURE_MISMATCH /
 * NEED_UNKNOWN_SOURCES / SESSION_FAILED / PENDING_USER_ACTION
 */
public final class ApkInstaller {

    private static final String TAG = "DeLectorUpdate";
    private static final String UPDATES_DIR = "updates";

    private ApkInstaller() {
    }

    public static String install(Activity activity, String rawPath) {
        File apk = resolveApk(activity, rawPath);
        if (apk == null) {
            return "BAD_PATH";
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                && !activity.getPackageManager().canRequestPackageInstalls()) {
            openUnknownSourcesSettings(activity);
            return "NEED_UNKNOWN_SOURCES";
        }

        PackageManager pm = activity.getPackageManager();
        PackageInfo archive = pm.getPackageArchiveInfo(apk.getAbsolutePath(), signatureFlags());
        if (archive == null) {
            return "BAD_APK";
        }
        if (!activity.getPackageName().equals(archive.packageName)) {
            return "PACKAGE_MISMATCH";
        }

        PackageInfo installed;
        try {
            installed = pm.getPackageInfo(activity.getPackageName(), signatureFlags());
        } catch (PackageManager.NameNotFoundException error) {
            return "BAD_APK";
        }
        if (versionCode(archive) <= versionCode(installed)) {
            return "VERSION_NOT_INCREASED";
        }
        if (!sameSigner(pm, installed, archive)) {
            return "SIGNATURE_MISMATCH";
        }

        return commitSession(activity, apk);
    }

    private static File resolveApk(Activity activity, String rawPath) {
        if (rawPath == null || rawPath.isEmpty()) {
            return null;
        }
        try {
            File apk = new File(rawPath).getCanonicalFile();
            File updatesDir = new File(activity.getFilesDir(), UPDATES_DIR).getCanonicalFile();
            String prefix = updatesDir.getPath() + File.separator;
            if (!apk.getPath().startsWith(prefix) || !apk.isFile() || !apk.getName().endsWith(".apk")) {
                return null;
            }
            return apk;
        } catch (Exception error) {
            return null;
        }
    }

    private static int signatureFlags() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            return PackageManager.GET_SIGNING_CERTIFICATES;
        }
        return PackageManager.GET_SIGNATURES;
    }

    private static long versionCode(PackageInfo info) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            return info.getLongVersionCode();
        }
        return info.versionCode;
    }

    private static boolean sameSigner(PackageManager pm, PackageInfo installed, PackageInfo archive) {
        try {
            List<String> current = certificateHashes(installed);
            List<String> candidate = certificateHashes(archive);
            return !current.isEmpty() && current.equals(candidate);
        } catch (Exception error) {
            Log.w(TAG, "signature check failed", error);
            return false;
        }
    }

    private static List<String> certificateHashes(PackageInfo info) throws Exception {
        Signature[] signatures;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (info.signingInfo == null) {
                return Collections.emptyList();
            }
            signatures = info.signingInfo.hasMultipleSigners()
                    ? info.signingInfo.getApkContentsSigners()
                    : info.signingInfo.getSigningCertificateHistory();
        } else {
            signatures = info.signatures;
        }
        List<String> hashes = new ArrayList<>();
        if (signatures == null) {
            return hashes;
        }
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        for (Signature signature : signatures) {
            byte[] bytes = digest.digest(signature.toByteArray());
            StringBuilder hex = new StringBuilder();
            for (byte value : bytes) {
                hex.append(String.format("%02x", value));
            }
            hashes.add(hex.toString());
        }
        Collections.sort(hashes);
        return hashes;
    }

    private static String commitSession(Activity activity, File apk) {
        PackageInstaller installer = activity.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params =
                new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(activity.getPackageName());

        int sessionId;
        try {
            sessionId = installer.createSession(params);
        } catch (Exception error) {
            Log.w(TAG, "createSession failed", error);
            return "SESSION_FAILED";
        }

        try (PackageInstaller.Session session = installer.openSession(sessionId)) {
            try (OutputStream out = session.openWrite("base.apk", 0, apk.length());
                    InputStream in = new FileInputStream(apk)) {
                byte[] buffer = new byte[64 * 1024];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                }
                session.fsync(out);
            }
            Intent intent = new Intent(InstallResultReceiver.ACTION_INSTALL_RESULT)
                    .setPackage(activity.getPackageName());
            PendingIntent pending = PendingIntent.getBroadcast(
                    activity, sessionId, intent,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            session.commit(pending.getIntentSender());
        } catch (Exception error) {
            Log.w(TAG, "commit session failed", error);
            return "SESSION_FAILED";
        }
        return "PENDING_USER_ACTION";
    }

    private static void openUnknownSourcesSettings(Activity activity) {
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName()));
            activity.startActivity(intent);
        } catch (Exception error) {
            Log.w(TAG, "cannot open unknown-sources settings", error);
        }
    }
}
