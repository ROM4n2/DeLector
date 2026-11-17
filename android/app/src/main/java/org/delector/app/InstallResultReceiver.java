package org.delector.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.util.Log;

/**
 * PackageInstaller 会话结果接收器（ADR-0034 D3）。
 *
 * 只在安装失败时留日志：成功时系统会替换/结束本进程，无需应用侧收尾。
 * STATUS_PENDING_USER_ACTION 必须把系统确认 Activity 拉起来，否则会话会一直悬着。
 */
public final class InstallResultReceiver extends BroadcastReceiver {

    public static final String ACTION_INSTALL_RESULT = "org.delector.app.INSTALL_RESULT";
    private static final String TAG = "DeLectorUpdate";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) {
            return;
        }
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(confirm);
            }
            return;
        }
        if (status != PackageInstaller.STATUS_SUCCESS) {
            String message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            Log.w(TAG, "package install failed: status=" + status + " message=" + message);
        }
    }
}
