package mobiletransport

import (
	"errors"
	"net"
	"sync"
	"testing"
)

type answer struct {
	conn net.Conn
	err  error
}
type fakeListener struct {
	entered chan struct{}
	result  chan answer
	closed  chan struct{}
	once    sync.Once
}

func fake() *fakeListener {
	return &fakeListener{make(chan struct{}, 20), make(chan answer), make(chan struct{}), sync.Once{}}
}
func (f *fakeListener) Accept() (net.Conn, error) {
	f.entered <- struct{}{}
	a := <-f.result
	return a.conn, a.err
}
func (f *fakeListener) Close() error   { f.once.Do(func() { close(f.closed) }); return nil }
func (f *fakeListener) Addr() net.Addr { return &net.TCPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 45678} }
func watch(l *Listener) chan Event {
	e := make(chan Event, 100)
	l.Observe(func(v Event) { e <- v })
	return e
}
func state(e <-chan Event, want string) Event {
	for {
		v := <-e
		if v.State == want {
			return v
		}
	}
}
func finish(t *testing.T, l *Listener) {
	t.Helper()
	l.Close()
	<-l.Done()
	if l.ConnectionCount() != 0 {
		t.Fatal("owned connections remain after Close")
	}
}

func TestPauseLateAcceptAndStablePort(t *testing.T) {
	first, second := fake(), fake()
	binds := make(chan string, 10)
	n := 0
	l := New(func(_, address string) (net.Listener, error) {
		binds <- address
		n++
		if n == 1 {
			return first, nil
		}
		return second, nil
	})
	defer finish(t, l)
	events := watch(l)
	l.SetDesired(true, 1)
	if err := l.Configure("tcp", "127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	accepted := make(chan net.Conn)
	go func() { c, _ := l.Accept(); accepted <- c }()
	<-first.entered
	ready := state(events, "TransportAccepting")
	if ready.RequestID != 1 || ready.Generation != 1 {
		t.Fatal(ready)
	}
	l.SetDesired(false, 2)
	<-first.closed
	state(events, "Paused")
	old, peer := net.Pipe()
	defer peer.Close()
	first.result <- answer{conn: old}
	b := make([]byte, 1)
	if _, err := peer.Read(b); err == nil {
		t.Fatal("late connection survived Pause")
	}
	l.SetDesired(true, 3)
	<-second.entered
	l.SetDesired(true, 3)
	current, remote := net.Pipe()
	defer remote.Close()
	second.result <- answer{conn: current}
	c := <-accepted
	c.Close()
	if <-binds != "127.0.0.1:0" || <-binds != "127.0.0.1:45678" {
		t.Fatal("port changed")
	}
	if n != 2 {
		t.Fatal(n)
	}
}

func TestCancelledBindAndPermanentClose(t *testing.T) {
	first := fake()
	bindStarted, release := make(chan struct{}), make(chan struct{})
	l := New(func(string, string) (net.Listener, error) { close(bindStarted); <-release; return first, nil })
	events := watch(l)
	configured := make(chan error)
	go func() { configured <- l.Configure("tcp", "127.0.0.1:0") }()
	<-bindStarted
	l.SetDesired(false, 1)
	l.SetDesired(true, 2)
	l.SetDesired(false, 3)
	close(release)
	<-configured
	<-first.closed
	state(events, "Paused")
	l.Close()
	<-l.Done()
	l.SetDesired(true, 4)
	if _, err := l.Accept(); !errors.Is(err, net.ErrClosed) {
		t.Fatal(err)
	}
	if l.Snapshot().State != "Stopped" {
		t.Fatal(l.Snapshot())
	}
}

func TestAcceptFailureRequiresCommand(t *testing.T) {
	f := fake()
	l := New(func(string, string) (net.Listener, error) { return f, nil })
	defer finish(t, l)
	events := watch(l)
	l.Configure("tcp", "127.0.0.1:0")
	result := make(chan error)
	go func() { _, err := l.Accept(); result <- err }()
	<-f.entered
	f.result <- answer{err: errors.New("accept")}
	failed := state(events, "Failed")
	if failed.Detail != "accept_failed" {
		t.Fatal(failed)
	}
	<-f.closed
	l.Close()
	if !errors.Is(<-result, net.ErrClosed) {
		t.Fatal("Accept did not exit")
	}
}

func TestListenFailureAndObserverReplayReentry(t *testing.T) {
	l := New(func(string, string) (net.Listener, error) { return nil, errors.New("busy") })
	defer finish(t, l)
	if l.Configure("tcp", "127.0.0.1:0") == nil {
		t.Fatal("missing bind failure")
	}
	done := make(chan Event, 1)
	l.Observe(func(e Event) { l.Observe(nil); l.SetDesired(false, 1); done <- e })
	if e := <-done; e.State != "Failed" {
		t.Fatal(e)
	}
}

func TestConcurrentCommands(t *testing.T) {
	l := New(net.Listen)
	defer finish(t, l)
	if err := l.Configure("tcp", "127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	result := make(chan error)
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				result <- err
				return
			}
			c.Close()
		}
	}()
	var wg sync.WaitGroup
	for i := int64(1); i <= 100; i++ {
		wg.Add(1)
		go func(id int64) { defer wg.Done(); l.SetDesired(id%2 == 0, id) }(i)
	}
	wg.Wait()
	l.Close()
	<-result
	<-l.Done()
	if l.ConnectionCount() != 0 {
		t.Fatal("connection leak")
	}
}

func TestOccupiedPortAndCloseDuringBind(t *testing.T) {
	occupied, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer occupied.Close()
	l := New(net.Listen)
	if err = l.Configure("tcp", occupied.Addr().String()); err == nil {
		t.Fatal("occupied port accepted")
	}
	if l.Snapshot().State != "Failed" {
		t.Fatal(l.Snapshot())
	}
	finish(t, l)
	started, release := make(chan struct{}), make(chan struct{})
	late := fake()
	l = New(func(string, string) (net.Listener, error) { close(started); <-release; return late, nil })
	configured := make(chan error, 1)
	go func() { configured <- l.Configure("tcp", "127.0.0.1:0") }()
	<-started
	l.Close()
	l.SetDesired(true, 100)
	close(release)
	if err = <-configured; !errors.Is(err, net.ErrClosed) {
		t.Fatal(err)
	}
	<-l.Done()
	<-late.closed
}

func TestObserverDetachDiscardsQueuedEvents(t *testing.T) {
	l := New(net.Listen)
	defer finish(t, l)
	entered, release, oldDone := make(chan struct{}), make(chan struct{}), make(chan struct{})
	l.Observe(func(Event) { close(entered); <-release; close(oldDone) })
	<-entered
	l.SetDesired(false, 1)
	replacement := make(chan Event, 10)
	l.Observe(nil)
	l.Observe(func(e Event) { replacement <- e })
	close(release)
	<-oldDone
	if e := <-replacement; e.RequestID != 1 {
		t.Fatal(e)
	}
}

func TestCloseWakesEveryWaiter(t *testing.T) {
	l := New(net.Listen)
	results := make(chan error, 8)
	for i := 0; i < 8; i++ {
		go func() { _, err := l.Accept(); results <- err }()
	}
	l.Close()
	for i := 0; i < 8; i++ {
		if err := <-results; !errors.Is(err, net.ErrClosed) {
			t.Fatal(err)
		}
	}
	<-l.Done()
}

func TestTerminalFailureReplaysToNewRequests(t *testing.T) {
	l := New(net.Listen)
	l.Close()
	<-l.Done()
	l.ServingFailed(errors.New("unexpected child error after listener close"))
	l.SetDesired(true, 9)
	e := l.Snapshot()
	if e.State != "Failed" || e.RequestID != 9 || e.Detail != "serving_stack_failed" {
		t.Fatal(e)
	}
	if _, err := l.Accept(); !errors.Is(err, net.ErrClosed) {
		t.Fatal(err)
	}
}
