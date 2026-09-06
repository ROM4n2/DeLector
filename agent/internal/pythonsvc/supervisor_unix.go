//go:build unix

package pythonsvc

import (
	"os/exec"
	"syscall"
)

// terminateProc unix 平台终止实现（Phase2b T1 关闭语义平台分治）：先发
// SIGTERM 优雅关闭，让托管 Python 完成在途请求与资源收尾；发送失败
// （如进程已退出）回退 Kill 强杀。SIGTERM 后的最终强杀兜底分两路：
// ctx 取消路径由 exec.Cmd.WaitDelay 保证（见 supervisor.go realStartProc，
// Go 1.20+ 机制）；Stop/terminate 手动 cancel 路径（不取消 ctx）由
// awaitExit 超时分支调 killProc 强杀——两段式闭环 SIGTERM → StopTimeout
// → Kill，进程无视 SIGTERM 时不再无限等待。
func terminateProc(cmd *exec.Cmd) error {
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		return cmd.Process.Kill()
	}
	return nil
}

// killProc unix 平台强杀实现：无条件 Kill，供 awaitExit 超时分支在
// SIGTERM 未生效（StopTimeout 耗尽）时作最终兜底。
func killProc(cmd *exec.Cmd) error {
	return cmd.Process.Kill()
}
