package mobile

import (
	"net"
	"strconv"
	"sync/atomic"

	"github.com/siyuan-note/siyuan/kernel/server"
	"github.com/siyuan-note/siyuan/kernel/server/mobiletransport"
)

// ServingObserver 映射为 Objective-C 协议，Swift 管理其生命周期并显式解绑。
// 回调按顺序执行，并允许重入这些接口。
type ServingObserver interface {
	OnServingEvent(requestID int64, generation int64, state string, detail string)
}

func InstallServingObserver(observer ServingObserver) {
	l := server.EnableMobileRecovery()
	if observer == nil {
		l.Observe(nil)
		return
	}
	l.Observe(func(e mobiletransport.Event) { observer.OnServingEvent(e.RequestID, e.Generation, e.State, e.Detail) })
}

func SetServingDesiredState(active bool, requestID int64) {
	server.EnableMobileRecovery().SetDesired(active, requestID)
}

func RequestServingState() { server.EnableMobileRecovery().Replay() }

// ServingPort 提供冷启动后实际绑定的端口。
func ServingPort() int {
	addr := server.EnableMobileRecovery().Addr()
	if addr == nil {
		return 0
	}
	_, port, err := net.SplitHostPort(addr.String())
	if err != nil {
		return 0
	}
	result, _ := strconv.Atoi(port)
	return result
}

var mobileColdStart atomic.Bool

// StartKernelWithRecovery 负责一次冷启动栈构造，socket 可用性由 listener 的真实状态决定。
func StartKernelWithRecovery(container, appDir, workspaceBaseDir, timezoneID, localIPs, lang, osVer string) {
	server.EnableMobileRecovery()
	if !mobileColdStart.CompareAndSwap(false, true) {
		RequestServingState()
		return
	}
	StartKernel(container, appDir, workspaceBaseDir, timezoneID, localIPs, lang, osVer)
}

func ExitWithRecovery() {
	server.StopMobileRecovery()
	Exit()
}
