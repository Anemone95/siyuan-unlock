package server

import (
	"context"
	"net"
	"net/http"
	"sync/atomic"

	"github.com/gin-gonic/gin"
	"github.com/siyuan-note/siyuan/kernel/server/mobiletransport"
)

var mobileTransport atomic.Pointer[mobiletransport.Listener]

type mobileConnectionKey struct{}

// EnableMobileRecovery 由 iOS 桥在冷启动前安装。
func EnableMobileRecovery() *mobiletransport.Listener {
	if current := mobileTransport.Load(); current != nil {
		return current
	}
	candidate := mobiletransport.New(net.Listen)
	if mobileTransport.CompareAndSwap(nil, candidate) {
		return candidate
	}
	candidate.Close()
	return mobileTransport.Load()
}

func listenKernel(network, address string) (net.Listener, error) {
	if l := mobileTransport.Load(); l != nil {
		if err := l.Configure(network, address); err != nil {
			return nil, err
		}
		return l, nil
	}
	return net.Listen(network, address)
}

func mobileServingFailed(detail string) bool {
	if l := mobileTransport.Load(); l != nil {
		l.Fail(detail)
		return true
	}
	return false
}

func prepareMobileHTTP(s *http.Server) {
	if l := mobileTransport.Load(); l != nil {
		s.ConnState = l.ConnState
		s.ConnContext = func(ctx context.Context, conn net.Conn) context.Context {
			return context.WithValue(ctx, mobileConnectionKey{}, conn)
		}
	}
}

func installMobileRequests(engine *gin.Engine) {
	if l := mobileTransport.Load(); l != nil {
		engine.Use(func(c *gin.Context) {
			if c.Request.ProtoMajor == 2 {
				if conn, ok := c.Request.Context().Value(mobileConnectionKey{}).(net.Conn); ok {
					l.MarkHTTP2(conn)
				}
			}
			c.Next()
		})
	}
}

func StopMobileRecovery() {
	if l := mobileTransport.Load(); l != nil {
		l.Close()
		<-l.Done()
	}
}
func MobileRecoveryEnabled() bool { return mobileTransport.Load() != nil }
func mobileServeReturned(err error) bool {
	if l := mobileTransport.Load(); l != nil {
		l.ServingFailed(err)
		return true
	}
	return false
}
