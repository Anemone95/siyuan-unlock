package mobiletransport

import (
	"crypto/tls"
	"net"
	"net/http"
	"sync"

	"github.com/soheilhy/cmux"
)

const activeConnection = http.StateActive

type connection struct {
	net.Conn
	owner       *Listener
	epoch       uint64
	state       http.ConnState
	closing     bool
	multiplexed bool
	once        sync.Once
	err         error
}

func (c *connection) Close() error {
	c.once.Do(func() {
		c.owner.mu.Lock()
		delete(c.owner.connections, c)
		c.owner.mu.Unlock()
		c.err = c.Conn.Close()
	})
	return c.err
}

func tracked(conn net.Conn) *connection {
	switch c := conn.(type) {
	case *connection:
		return c
	case *tls.Conn:
		return tracked(c.NetConn())
	case *cmux.MuxConn:
		return tracked(c.Conn)
	default:
		return nil
	}
}

// ConnState 跟踪协议识别、TLS 握手、HTTP 请求及 WebSocket，活跃请求保留原代次。
// HTTP/1 在请求完成后关闭，已协商的 HTTP/2 保持归属直到对端关闭或内核退出。
func (l *Listener) ConnState(conn net.Conn, state http.ConnState) {
	c := tracked(conn)
	if c == nil {
		return
	}
	l.mu.Lock()
	c.state = state
	if tlsConn, ok := conn.(*tls.Conn); ok && tlsConn.ConnectionState().NegotiatedProtocol == "h2" {
		c.multiplexed = true
	}
	closeConn := c.closing || l.closed || ((!l.desired || c.epoch != l.epoch) && state != http.StateActive && !c.multiplexed)
	if closeConn {
		c.closing = true
	}
	l.mu.Unlock()
	if closeConn {
		c.Close()
	}
}

func (l *Listener) ConnectionCount() int { l.mu.Lock(); defer l.mu.Unlock(); return len(l.connections) }

// MarkHTTP2 保留暂停时已协商的 h2c 连接，保护 StateIdle 之后尚待发送的响应帧。
func (l *Listener) MarkHTTP2(conn net.Conn) {
	if c := tracked(conn); c != nil {
		l.mu.Lock()
		c.multiplexed = true
		l.mu.Unlock()
	}
}
