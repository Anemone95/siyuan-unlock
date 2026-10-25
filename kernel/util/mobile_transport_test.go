package util

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/siyuan-note/siyuan/kernel/server/mobiletransport"
)

func TestRecoveryTLSSetupFailure(t *testing.T) {
	l := mobiletransport.New(net.Listen)
	defer l.Close()
	if err := l.Configure("tcp", "127.0.0.1:0"); err != nil {
		t.Fatal(err)
	}
	_, _, err := ServeMultiplexed(l, http.NotFoundHandler(), "missing-cert", "missing-key", nil, nil)
	if err == nil || l.Snapshot().State != "Failed" {
		t.Fatalf("%v %+v", err, l.Snapshot())
	}
	<-l.Done()
}

func TestRecoveryMultiplexedHelper(t *testing.T) {
	seed := httptest.NewTLSServer(http.NotFoundHandler())
	cert := seed.TLS.Certificates[0]
	seed.Close()
	key, err := x509.MarshalPKCS8PrivateKey(cert.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	certPath, keyPath := filepath.Join(dir, "cert.pem"), filepath.Join(dir, "key.pem")
	os.WriteFile(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert.Certificate[0]}), 0600)
	os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: key}), 0600)
	l := mobiletransport.New(net.Listen)
	l.Configure("tcp", "127.0.0.1:0")
	events := make(chan mobiletransport.Event, 20)
	l.Observe(func(e mobiletransport.Event) { events <- e })
	done := make(chan error, 1)
	go func() {
		_, _, err := ServeMultiplexed(l, http.NotFoundHandler(), certPath, keyPath, nil, nil)
		done <- err
	}()
	for e := range events {
		if e.State == "TransportAccepting" {
			break
		}
	}
	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, ForceAttemptHTTP2: true}}
	defer client.CloseIdleConnections()
	for _, scheme := range []string{"http", "https"} {
		response, err := client.Get(scheme + "://" + l.Addr().String())
		if err != nil {
			t.Fatal(err)
		}
		_, err = io.Copy(io.Discard, response.Body)
		response.Body.Close()
		if err != nil {
			t.Fatal(err)
		}
		if scheme == "https" && response.ProtoMajor != 2 {
			t.Fatal("actual cmux helper did not negotiate HTTP/2")
		}
	}
	half, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer half.Close()
	// 验证真实 helper 的失败观察，并确认存在协议识别等待时 root 与 cmux worker 也能退出。
	observeServingFailure(l, errors.New("child serve failed"))
	<-l.Done()
	<-done
	if l.Snapshot().State != "Failed" {
		t.Fatal(l.Snapshot())
	}
}
