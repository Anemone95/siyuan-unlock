package util

import (
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/olahol/melody"
)

func TestRecoverySessionIdentity(t *testing.T) {
	for _, id := range []string{"main", "auth"} {
		t.Run(id, func(t *testing.T) {
			old := &melody.Session{Request: httptest.NewRequest("GET", "http://local/ws?app=recovery-test&id="+id+"&type=main", nil)}
			next := &melody.Session{Request: old.Request}
			AddPushChan(old)
			AddPushChan(next)
			RemovePushChan(old)
			table := &sessions
			if id == "auth" {
				table = &authSessions
			}
			app, ok := table.Load("recovery-test")
			if !ok {
				t.Fatal("old disconnect deleted new app")
			}
			got, ok := app.(*sync.Map).Load(id)
			if !ok || got != next {
				t.Fatal("old disconnect deleted new session")
			}
			RemovePushChan(next)
		})
	}
}
