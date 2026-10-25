package server

import (
	"context"
	"crypto/tls"
	"io"
	"net"
	"net/http"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/siyuan-note/siyuan/kernel/server/mobiletransport"
	"golang.org/x/net/http2"
)

func TestMobileFactoryDisabled(t *testing.T) {
	if MobileRecoveryEnabled() {
		t.Fatal("feature enabled before bridge installation")
	}
	l, err := listenKernel("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	if _, ok := l.(*net.TCPListener); !ok {
		t.Fatal("desktop listener changed")
	}
}

func TestMobileFactoryColdStartAndReuse(t *testing.T) {
	l := EnableMobileRecovery()
	defer func() { StopMobileRecovery(); mobileTransport.Store(nil) }()
	l.SetDesired(true, 1)
	if l.Addr() != nil {
		t.Fatal("resume constructed cold serving stack")
	}
	got, err := listenKernel("tcp", "127.0.0.1:0")
	if err != nil || got != l {
		t.Fatal(got, err)
	}
	if EnableMobileRecovery() != l {
		t.Fatal("duplicate controller")
	}
	if _, err = listenKernel("tcp", "127.0.0.1:0"); err == nil {
		t.Fatal("duplicate initialization accepted")
	}
}

func TestMobileH2CWritePause(t *testing.T) {
	l := EnableMobileRecovery()
	defer func() { StopMobileRecovery(); mobileTransport.Store(nil) }()
	listener, err := listenKernel("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	started, release := make(chan struct{}), make(chan struct{})
	gin.SetMode(gin.ReleaseMode)
	engine := gin.New()
	engine.UseH2C = true
	installMobileRequests(engine)
	engine.POST("/write", func(c *gin.Context) { close(started); <-release; c.String(200, "committed") })
	s := &http.Server{Handler: engine.Handler()}
	prepareMobileHTTP(s)
	done := make(chan error, 1)
	go func() { done <- s.Serve(listener) }()
	defer func() { s.Close(); <-done }()
	transport := &http2.Transport{AllowHTTP: true, DialTLSContext: func(ctx context.Context, network, address string, _ *tls.Config) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, network, address)
	}}
	defer transport.CloseIdleConnections()
	result := make(chan string, 1)
	go func() {
		resp, err := (&http.Client{Transport: transport}).Post("http://"+l.Addr().String()+"/write", "text/plain", strings.NewReader("write"))
		if err != nil {
			result <- err.Error()
			return
		}
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		result <- string(b)
	}()
	<-started
	events := make(chan mobiletransport.Event, 10)
	l.Observe(func(e mobiletransport.Event) { events <- e })
	l.SetDesired(false, 1)
	for e := range events {
		if e.State == "Paused" {
			break
		}
	}
	close(release)
	if got := <-result; got != "committed" {
		t.Fatal(got)
	}
}
