package util

import (
	"crypto/tls"
	"net"
	"net/http"

	"golang.org/x/net/http2"
)

// 可选 listener 能力在共享 serving helper 下管理移动端连接，桌面端沿用原有行为。
type servingLifecycle interface {
	ServingFailed(error)
	ConnState(net.Conn, http.ConnState)
}

func observeServingFailure(ln net.Listener, err error) error {
	if owner, ok := ln.(servingLifecycle); ok {
		owner.ServingFailed(err)
	}
	return err
}

func prepareMultiplexedHTTP(ln net.Listener, plain, secure *http.Server, config *tls.Config) error {
	if owner, ok := ln.(servingLifecycle); ok {
		plain.ConnState = owner.ConnState
		secure.ConnState = owner.ConnState
		secure.ConnContext = plain.ConnContext
		secure.TLSConfig = config
		// 在进入 Accept 并发布可接收状态前完成 HTTP/2 配置。
		if err := http2.ConfigureServer(secure, nil); err != nil {
			owner.ServingFailed(err)
			return err
		}
	}
	return nil
}
