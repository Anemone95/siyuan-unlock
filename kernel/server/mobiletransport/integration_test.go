package mobiletransport

import (
	"crypto/tls"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gorilla/websocket"
	"github.com/soheilhy/cmux"
	"golang.org/x/net/http2"
)

func TestHTTPAndWebSocketRounds(t *testing.T) {
	l := New(net.Listen)
	events := watch(l)
	if err := l.Configure("tcp", "127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	started, release := make(chan struct{}), make(chan struct{})
	writes := make(chan string, 1)
	wsDone := make(chan struct{}, 20)
	mux := http.NewServeMux()
	mux.HandleFunc("/write", func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-release
		b, _ := io.ReadAll(r.Body)
		writes <- string(b)
		w.Write([]byte("committed"))
	})
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		c, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer c.Close()
		defer func() { wsDone <- struct{}{} }()
		for {
			if _, _, err = c.ReadMessage(); err != nil {
				return
			}
		}
	})
	s := &http.Server{Handler: mux, ConnState: l.ConnState}
	served := make(chan error, 1)
	go func() { served <- s.Serve(l) }()
	defer func() { finish(t, l); s.Close(); <-served }()
	state(events, "TransportAccepting")
	url := "http://" + l.Addr().String()
	result := make(chan string, 1)
	go func() {
		resp, err := http.Post(url+"/write", "text/plain", strings.NewReader("once"))
		if err != nil {
			result <- err.Error()
			return
		}
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		result <- string(b)
	}()
	<-started
	l.SetDesired(false, 1)
	state(events, "Paused")
	close(release)
	if <-writes != "once" || <-result != "committed" {
		t.Fatal("active write interrupted")
	}
	for i := int64(0); i < 10; i++ {
		l.SetDesired(true, 2+i*2)
		state(events, "TransportAccepting")
		c, _, err := websocket.DefaultDialer.Dial("ws://"+l.Addr().String()+"/ws", nil)
		if err != nil {
			t.Fatal(err)
		}
		l.SetDesired(false, 3+i*2)
		state(events, "Paused")
		<-wsDone
		c.Close()
		if n := l.ConnectionCount(); n != 0 {
			t.Fatalf("round %d retained %d connections", i, n)
		}
	}
}

func TestCMuxHalfOpenTLSAndHTTP2(t *testing.T) {
	certServer := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	config := certServer.TLS.Clone()
	certServer.Close()
	config.NextProtos = []string{"h2", "http/1.1"}
	l := New(net.Listen)
	events := watch(l)
	l.Configure("tcp", "127.0.0.1:0")
	m := cmux.New(l)
	tlsL := m.Match(cmux.TLS())
	plainL := m.Match(cmux.Any())
	started, release := make(chan struct{}), make(chan struct{})
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/write" {
			close(started)
			<-release
		}
		w.Write([]byte(r.Proto))
	})
	plain := &http.Server{Handler: handler, ConnState: l.ConnState}
	secure := &http.Server{Handler: handler, ConnState: l.ConnState, TLSConfig: config}
	http2.ConfigureServer(secure, &http2.Server{})
	done := make(chan error, 3)
	go func() { done <- plain.Serve(plainL) }()
	go func() { done <- secure.Serve(tls.NewListener(tlsL, config)) }()
	go func() { done <- m.Serve() }()
	defer func() {
		finish(t, l)
		plain.Close()
		secure.Close()
		for i := 0; i < 3; i++ {
			<-done
		}
	}()
	state(events, "TransportAccepting")
	half, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer half.Close()
	handshake, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer handshake.Close()
	if _, err = handshake.Write([]byte{22, 3, 1}); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, ForceAttemptHTTP2: true}}
	defer client.CloseIdleConnections()
	resp, err := client.Get("https://" + l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if string(b) != "HTTP/2.0" {
		t.Fatalf("HTTP/2 not exercised: %s", b)
	}
	result := make(chan error, 1)
	go func() {
		resp, err := client.Post("https://"+l.Addr().String()+"/write", "text/plain", strings.NewReader("write"))
		if err == nil {
			_, err = io.ReadAll(resp.Body)
			resp.Body.Close()
		}
		result <- err
	}()
	<-started
	l.SetDesired(false, 1)
	state(events, "Paused")
	one := make([]byte, 1)
	if _, err := half.Read(one); err == nil {
		t.Fatal("sniff survived pause")
	}
	if _, err := handshake.Read(one); err == nil {
		t.Fatal("partial TLS handshake survived pause")
	}
	close(release)
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	l.SetDesired(true, 2)
	state(events, "TransportAccepting")
	resp, err = client.Get("http://" + l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
}
