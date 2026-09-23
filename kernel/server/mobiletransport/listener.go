// Package mobiletransport 管理长生命周期 HTTP 服务栈下的 socket。
package mobiletransport

import (
	"errors"
	"log"
	"net"
	"os"
	"sync"
)

// Event 分别描述监听状态、前端连接与编辑确认，Detail 仅包含稳定错误码。
type Event struct {
	RequestID  int64
	Generation int64
	State      string
	Detail     string
}

type delivery struct {
	epoch uint64
	event Event
}

// Listener 在 mu 下确定暂停与连接交付顺序，由 run 串行管理 socket，并在锁外依次投递回调。
type Listener struct {
	trace                                                     bool
	mu                                                        sync.Mutex
	changed                                                   chan struct{}
	wake                                                      chan struct{}
	done                                                      chan struct{}
	listen                                                    func(string, string) (net.Listener, error)
	network, address                                          string
	addr                                                      net.Addr
	configured, initialized, entered, desired, closed, failed bool
	initialErr                                                error
	epoch                                                     uint64
	generation, request                                       int64
	socket                                                    net.Listener
	retired                                                   []net.Listener
	connections                                               map[*connection]struct{}
	latest                                                    Event
	observer                                                  func(Event)
	observerEpoch                                             uint64
	deliveries                                                []delivery
	delivering                                                bool
}

func New(listen func(string, string) (net.Listener, error)) *Listener {
	l := &Listener{trace: os.Getenv("SIYUAN_RECOVERY_TRACE") == "1", listen: listen, changed: make(chan struct{}), wake: make(chan struct{}, 1), done: make(chan struct{}), desired: true, connections: make(map[*connection]struct{})}
	l.latest.State = "Starting"
	go l.run()
	return l
}

func (l *Listener) signalLocked() {
	close(l.changed)
	l.changed = make(chan struct{})
	select {
	case l.wake <- struct{}{}:
	default:
	}
}

func (l *Listener) eventLocked(state, detail string) {
	l.latest = Event{l.request, l.generation, state, detail}
	l.enqueueLocked(l.latest)
}

func (l *Listener) enqueueLocked(e Event) {
	if l.observer == nil {
		return
	}
	l.deliveries = append(l.deliveries, delivery{l.observerEpoch, e})
	if !l.delivering {
		l.delivering = true
		go l.deliver()
	}
}

func (l *Listener) deliver() {
	for {
		l.mu.Lock()
		if len(l.deliveries) == 0 {
			l.delivering = false
			l.mu.Unlock()
			return
		}
		d := l.deliveries[0]
		l.deliveries[0] = delivery{}
		l.deliveries = l.deliveries[1:]
		fn := l.observer
		valid := d.epoch == l.observerEpoch
		l.mu.Unlock()
		if valid && fn != nil {
			if l.trace {
				log.Printf("[recovery] state=%s request=%d generation=%d", d.event.State, d.event.RequestID, d.event.Generation)
			}
			fn(d.event)
		}
	}
}

// Observe 原子登记观察者并重放最新状态，隔离已排队的旧观察者事件。
// 已经执行的回调可在解绑后结束。
func (l *Listener) Observe(fn func(Event)) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.observerEpoch++
	l.observer = fn
	l.deliveries = nil
	l.enqueueLocked(l.latest)
}

func (l *Listener) Snapshot() Event { l.mu.Lock(); defer l.mu.Unlock(); return l.latest }
func (l *Listener) Replay()         { l.mu.Lock(); defer l.mu.Unlock(); l.enqueueLocked(l.latest) }

// Configure 由冷启动工厂调用一次，等待首次绑定和端口分配完成。
func (l *Listener) Configure(network, address string) error {
	l.mu.Lock()
	if l.configured {
		l.mu.Unlock()
		return errors.New("transport already configured")
	}
	l.configured = true
	l.network = network
	l.address = address
	l.signalLocked()
	for !l.initialized && !l.closed {
		ch := l.changed
		l.mu.Unlock()
		<-ch
		l.mu.Lock()
	}
	err := l.initialErr
	if l.closed && err == nil {
		err = net.ErrClosed
	}
	l.mu.Unlock()
	return err
}

// SetDesired 记录生命周期需求，request 为单调递增的原生命令标识。
func (l *Listener) SetDesired(active bool, request int64) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if request <= l.request {
		return
	}
	if l.closed {
		l.request = request
		l.eventLocked(l.latest.State, l.latest.Detail)
		return
	}
	if l.latest.State == "Starting" || l.latest.State == "Pausing" {
		l.enqueueLocked(Event{l.request, l.generation, "Cancelled", "superseded"})
	}
	l.request = request
	if active == l.desired && !l.failed {
		l.eventLocked(l.latest.State, l.latest.Detail)
		return
	}
	l.desired = active
	l.failed = false
	l.epoch++
	if !active {
		l.retireLocked()
		l.eventLocked("Pausing", "")
	} else {
		l.eventLocked("Starting", "")
	}
	l.signalLocked()
}

func (l *Listener) retireLocked() {
	if l.socket != nil {
		l.retired = append(l.retired, l.socket)
		l.socket = nil
	}
}

// Fail 终止已损坏的 HTTP/cmux 服务栈，绑定和 Accept 失败则等待后续显式命令恢复。
func (l *Listener) Fail(detail string) {
	l.mu.Lock()
	if l.closed && l.failed {
		l.mu.Unlock()
		return
	}
	l.failed = true
	l.closed = true
	l.epoch++
	l.retireLocked()
	l.eventLocked("Failed", detail)
	l.signalLocked()
	l.mu.Unlock()
}

func (l *Listener) Close() error {
	l.mu.Lock()
	if !l.closed {
		l.closed = true
		l.epoch++
		l.retireLocked()
		l.eventLocked("Stopped", "")
		l.signalLocked()
	}
	l.mu.Unlock()
	return nil
}

// Done 在归属 socket 与连接清理完成后关闭，供后台执行上下文等待最终退出。
func (l *Listener) Done() <-chan struct{} { return l.done }
func (l *Listener) Addr() net.Addr        { l.mu.Lock(); defer l.mu.Unlock(); return l.addr }

func (l *Listener) run() {
	defer close(l.done)
	for range l.wake {
		l.mu.Lock()
		cycleEpoch := l.epoch
		wasClosed := l.closed
		retired := l.retired
		l.retired = nil
		var closing []*connection
		for c := range l.connections {
			if l.closed || ((!l.desired || c.epoch != l.epoch) && c.state != activeConnection && !c.multiplexed) {
				c.closing = true
				closing = append(closing, c)
			}
		}
		l.mu.Unlock()
		for _, s := range retired {
			s.Close()
			l.traceEvent("listener_closed", cycleEpoch)
		}
		for _, c := range closing {
			c.Close()
		}
		l.mu.Lock()
		if wasClosed {
			l.mu.Unlock()
			return
		}
		if l.closed || len(l.retired) > 0 {
			l.signalLocked()
			l.mu.Unlock()
			continue
		}
		if !l.desired && l.initialized {
			if l.latest.State != "Paused" {
				l.eventLocked("Paused", "")
			}
			l.mu.Unlock()
			continue
		}
		if !l.configured || l.socket != nil || l.failed {
			l.mu.Unlock()
			continue
		}
		epoch, network, address := l.epoch, l.network, l.address
		l.generation++
		l.mu.Unlock()
		socket, err := l.listen(network, address)
		l.traceEvent("listen_return", epoch)
		l.mu.Lock()
		if !l.initialized {
			l.initialized = true
			l.initialErr = err
			if err == nil {
				l.addr = socket.Addr()
				l.address = l.addr.String()
			}
		}
		if l.closed || epoch != l.epoch || !l.desired {
			l.signalLocked()
			l.mu.Unlock()
			if socket != nil {
				socket.Close()
			}
			continue
		}
		if err != nil {
			l.failed = true
			l.eventLocked("Failed", "listen_failed")
		} else {
			l.socket = socket
			if l.entered {
				l.eventLocked("TransportAccepting", "")
			}
		}
		l.signalLocked()
		l.mu.Unlock()
	}
}

func (l *Listener) Accept() (net.Conn, error) {
	for {
		l.mu.Lock()
		if l.closed {
			l.mu.Unlock()
			return nil, net.ErrClosed
		}
		l.entered = true
		socket, epoch := l.socket, l.epoch
		if socket == nil {
			ch := l.changed
			l.mu.Unlock()
			<-ch
			continue
		}
		if l.latest.State != "TransportAccepting" {
			l.eventLocked("TransportAccepting", "")
		}
		l.mu.Unlock()
		l.traceEvent("accept_enter", epoch)
		conn, err := socket.Accept()
		l.traceEvent("accept_return", epoch)
		l.mu.Lock()
		if l.closed || socket != l.socket || epoch != l.epoch {
			l.mu.Unlock()
			if conn != nil {
				conn.Close()
			}
			continue
		}
		if err != nil {
			l.failed = true
			l.epoch++
			l.retireLocked()
			l.eventLocked("Failed", "accept_failed")
			l.signalLocked()
			l.mu.Unlock()
			continue
		}
		// 此处确定成功交付顺序，随后发生的 Pause 撤销后续连接的交付资格。
		c := &connection{Conn: conn, owner: l, epoch: epoch}
		l.connections[c] = struct{}{}
		l.mu.Unlock()
		return c, nil
	}
}

func (l *Listener) traceEvent(action string, epoch uint64) {
	if l.trace {
		log.Printf("[recovery] event=%s commandEpoch=%d", action, epoch)
	}
}
