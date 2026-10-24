// SiYuan - From thought to insight, with agents
// Copyright (c) 2020-present, b3log.org

package model

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/siyuan-note/siyuan/kernel/util"
)

func TestFirstLaunchNoticeAcknowledgementUsesInstallationHome(t *testing.T) {
	originalHomeDir := util.HomeDir
	originalWorkspaceDir := util.WorkspaceDir
	installationHome := t.TempDir()
	util.HomeDir = installationHome
	util.WorkspaceDir = filepath.Join(t.TempDir(), "workspace-a")
	t.Cleanup(func() {
		util.HomeDir = originalHomeDir
		util.WorkspaceDir = originalWorkspaceDir
	})

	if FirstLaunchNoticeAcknowledged() {
		t.Fatal("new installation was already acknowledged")
	}
	if err := AcknowledgeFirstLaunchNotice(); err != nil {
		t.Fatalf("acknowledge notice failed: %v", err)
	}
	if !FirstLaunchNoticeAcknowledged() {
		t.Fatal("acknowledgement was not persisted")
	}

	util.WorkspaceDir = filepath.Join(t.TempDir(), "workspace-b")
	if !FirstLaunchNoticeAcknowledged() {
		t.Fatal("acknowledgement changed after switching workspace")
	}

	statePath := filepath.Join(installationHome, ".config", "siyuan", "siyuan-unlock.json")
	if _, err := os.Stat(statePath); err != nil {
		t.Fatalf("installation state file missing: %v", err)
	}
}

func TestFirstLaunchNoticeAcknowledgementRepairsInvalidState(t *testing.T) {
	originalHomeDir := util.HomeDir
	util.HomeDir = t.TempDir()
	t.Cleanup(func() { util.HomeDir = originalHomeDir })

	statePath := filepath.Join(util.HomeDir, ".config", "siyuan", "siyuan-unlock.json")
	if err := os.MkdirAll(filepath.Dir(statePath), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(statePath, []byte("invalid"), 0644); err != nil {
		t.Fatal(err)
	}
	if FirstLaunchNoticeAcknowledged() {
		t.Fatal("invalid state was treated as acknowledged")
	}
	if err := AcknowledgeFirstLaunchNotice(); err != nil {
		t.Fatalf("repair invalid state failed: %v", err)
	}
	if !FirstLaunchNoticeAcknowledged() {
		t.Fatal("repaired state was not acknowledged")
	}
}
