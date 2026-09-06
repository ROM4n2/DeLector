//go:build windows

package pythonsvc

import "os/exec"

// terminateProc windows 平台终止实现（Phase2b T1 关闭语义平台分治）：
// Windows 无 SIGTERM，Kill（TerminateProcess）为最接近的终止语义，
// 保持 2a 既有行为不动。收尾兜底分两路：ctx 取消路径由 exec.Cmd.WaitDelay
// 保证（见 supervisor.go realStartProc，Go 1.20+ 机制）；手动 cancel 路径
// 由 awaitExit 超时分支调 killProc（同为 Kill，对已退出进程的无害错误由
// 调用方丢弃）。
func terminateProc(cmd *exec.Cmd) error {
	return cmd.Process.Kill()
}

// killProc windows 平台强杀实现：与 terminateProc 同为 Kill
// （TerminateProcess），供 awaitExit 超时分支统一调用。
func killProc(cmd *exec.Cmd) error {
	return cmd.Process.Kill()
}
