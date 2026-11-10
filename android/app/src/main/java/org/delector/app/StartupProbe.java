package org.delector.app;

import android.os.Process;
import android.os.SystemClock;
import android.util.Log;

/**
 * 启动分段埋点（S0）：**只写日志，不参与任何控制流**。
 *
 * 移除方式：删掉本文件 + 所有 `StartupProbe.` 调用点即可回到原状；release 构建（非 debug）下全部静默。
 *
 * 两条零点互不混淆：
 * - `t_proc_ms` = 自 `Process.getStartElapsedRealtime()` 起（进程零点）；
 * - `t_nav_ms`  = 自最近一次 `navZero()`（即将 `loadUrl` 的那一刻）起（导航零点）。
 */
final class StartupProbe {
    private static final String TAG = "DeLectorProbe";
    private static final boolean ON = BuildConfig.DEBUG;

    private static volatile long navZeroElapsed = -1L;

    private StartupProbe() {}

    /** 进程零点事件。 */
    static void mark(String event) {
        if (!ON) {
            return;
        }
        Log.i(TAG, "PROBE ev=" + event + " t_proc_ms=" + sinceProcess());
    }

    /** 记录导航零点：调用点必须紧贴 `loadUrl(...)` 之前。 */
    static void navZero() {
        if (!ON) {
            return;
        }
        navZeroElapsed = SystemClock.elapsedRealtime();
    }

    /** 导航零点事件；`detail` 写 URL 或短标记，便于区分壳页/真实页。 */
    static void markNav(String event, String detail) {
        if (!ON) {
            return;
        }
        long nav = navZeroElapsed;
        long now = SystemClock.elapsedRealtime();
        Log.i(TAG, "PROBE ev=" + event
                + " t_proc_ms=" + (now - Process.getStartElapsedRealtime())
                + " t_nav_ms=" + (nav < 0 ? -1 : now - nav)
                + " detail=" + detail);
    }

    private static long sinceProcess() {
        return SystemClock.elapsedRealtime() - Process.getStartElapsedRealtime();
    }
}
