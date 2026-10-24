package model

import (
	"net/http"
	"testing"

	"github.com/siyuan-note/siyuan/kernel/conf"
)

func TestUnlockAccountSurvivesCloudAuthenticationFailure(t *testing.T) {
	for _, provider := range []int{conf.ProviderS3, conf.ProviderWebDAV} {
		setupCloudAccountAuthTest(t)
		Conf.Sync.Load().Provider = provider
		user := &conf.User{UserId: "0", UserToken: "token", UserSiYuanOneTimePayStatus: 1}
		Conf.SetUser(user)
		called := false
		mockCloudAuthResponse(t, func(request *http.Request) (*http.Response, error) {
			called = true
			return cloudAuthResponse(request, http.StatusUnauthorized, ""), nil
		})
		if _, err := GetCloudShorthands(1); err == nil || !called {
			t.Fatal("cloud request must still report authentication failure")
		}
		if Conf.GetUser() != user || !IsPaidUser() || !checkSync(false, false, true) || Conf.UserData != "persisted-user" {
			t.Fatalf("cloud authentication failure removed local unlock state for sync provider %d", provider)
		}
	}
}
