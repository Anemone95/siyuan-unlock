package model

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/siyuan-note/siyuan/kernel/conf"
	"github.com/siyuan-note/siyuan/kernel/util"
)

func TestUnlockInstallPackageDownloadStaysOff(t *testing.T) {
	oldConf, oldConfDir, oldReadOnly := Conf, util.ConfDir, util.ReadOnly
	t.Cleanup(func() { Conf, util.ConfDir, util.ReadOnly = oldConf, oldConfDir, oldReadOnly })
	Conf, util.ConfDir, util.ReadOnly = NewAppConf(), t.TempDir(), false
	system := conf.NewSystem()
	system.DownloadInstallPkg = true
	Conf.System.Store(system)

	if !skipNewVerInstallPkg() || "" != getNewVerInstallPkgPath(false) {
		t.Fatal("install package download must stay off")
	}
	if Conf.LoadSystem().DownloadInstallPkg {
		t.Fatal("DownloadInstallPkg was not turned off")
	}
	data, err := os.ReadFile(filepath.Join(util.ConfDir, "conf.json"))
	if err != nil || !strings.Contains(string(data), `"downloadInstallPkg": false`) {
		t.Fatalf("turned-off setting was not saved: %v", err)
	}
	snapshot := Conf.LoadSystem()
	skipNewVerInstallPkg()
	if Conf.LoadSystem() != snapshot {
		t.Fatal("a turned-off setting must not be saved again")
	}
}
