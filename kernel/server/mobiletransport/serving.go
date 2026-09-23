package mobiletransport

import (
	"errors"
	"net"
	"net/http"

	"github.com/soheilhy/cmux"
)

// ServingFailed 观察 HTTP/HTTPS 子服务的返回，正常最终关闭保持 Stopped 状态。
func (l *Listener) ServingFailed(err error) {
	if err == nil || errors.Is(err, http.ErrServerClosed) || errors.Is(err, net.ErrClosed) || errors.Is(err, cmux.ErrListenerClosed) || errors.Is(err, cmux.ErrServerClosed) {
		return
	}
	l.Fail("serving_stack_failed")
}
