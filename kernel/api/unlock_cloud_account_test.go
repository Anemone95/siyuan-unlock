package api

import (
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/siyuan-note/siyuan/kernel/conf"
	"github.com/siyuan-note/siyuan/kernel/model"
	"github.com/siyuan-note/siyuan/kernel/util"
)

func TestUnlockGetCloudUserPersistsIdentity(t *testing.T) {
	oldConf, oldDir, oldReadOnly := model.Conf, util.ConfDir, util.ReadOnly
	t.Cleanup(func() { model.Conf, util.ConfDir, util.ReadOnly = oldConf, oldDir, oldReadOnly })
	model.Conf, util.ConfDir, util.ReadOnly = model.NewAppConf(), t.TempDir(), false

	for _, role := range []model.Role{model.RoleReader, model.RoleEditor, model.RoleAdministrator} {
		recorder := httptest.NewRecorder()
		context, _ := gin.CreateTestContext(recorder)
		context.Set(model.RoleContextKey, role)
		context.Request = httptest.NewRequest(http.MethodPost, "/api/setting/getCloudUser", strings.NewReader(`{}`))
		getCloudUser(context)
		requireAPIContract(t, http.MethodPost, "/api/setting/getCloudUser", recorder)
		var response struct {
			Code int        `json:"code"`
			Data *conf.User `json:"data"`
		}
		if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil || response.Code != 0 {
			t.Fatalf("getCloudUser failed: %s, %v", recorder.Body.String(), err)
		}
		if role != model.RoleAdministrator {
			if response.Data != nil || model.Conf.GetUser() != nil || model.Conf.UserData != "" {
				t.Fatal("non-admin request must not create or expose the local identity")
			}
			continue
		}
		if response.Data == nil || response.Data.UserId != "0" || response.Data.UserSiYuanOneTimePayStatus != 1 || !model.IsPaidUser() {
			t.Fatal("admin boot request did not restore account-free sync")
		}
	}

	data, err := os.ReadFile(filepath.Join(util.ConfDir, "conf.json"))
	if err != nil {
		t.Fatalf("local identity was not saved: %v", err)
	}
	var saved struct {
		UserData string `json:"userData"`
	}
	if err = json.Unmarshal(data, &saved); err != nil || saved.UserData == "" {
		t.Fatalf("saved configuration has no local identity: %v", err)
	}
	data, err = hex.DecodeString(string(util.AESDecrypt(saved.UserData)))
	if err != nil {
		t.Fatal(err)
	}
	var restored conf.User
	if err = json.Unmarshal(data, &restored); err != nil || restored.UserId != "0" ||
		restored.UserToken != "token" || restored.UserSiYuanOneTimePayStatus != 1 {
		t.Fatalf("persisted local identity cannot survive restart: %v", err)
	}
}
