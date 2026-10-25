package util

import (
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/olahol/melody"
)

func pushSession(id string) *melody.Session {
	return &melody.Session{Request: httptest.NewRequest("GET", "http://local/ws?app=outer-race-test&id="+id+"&type=main", nil)}
}

func TestPushSessionOuterRemovalVersusStore(t *testing.T) {
	// 两种合法写入顺序均须保持新 session 可从外层表访问，覆盖原 app 表为空的情况。
	for i := 0; i < 1000; i++ {
		old, next := pushSession("old"), pushSession("new")
		AddPushChan(old)
		start := make(chan struct{})
		var wg sync.WaitGroup
		wg.Add(2)
		go func() { defer wg.Done(); <-start; RemovePushChan(old) }()
		go func() { defer wg.Done(); <-start; AddPushChan(next) }()
		close(start)
		wg.Wait()
		app, ok := sessions.Load("outer-race-test")
		if !ok {
			t.Fatal("outer removal detached new session")
		}
		if got, ok := app.(*sync.Map).Load("new"); !ok || got != next {
			t.Fatal("new session unreachable")
		}
		RemovePushChan(next)
		if _, ok := sessions.Load("outer-race-test"); ok {
			t.Fatal("empty app retained")
		}
	}
}
