// SiYuan - From thought to insight, with agents
// Copyright (c) 2020-present, b3log.org

package model

import (
	"os"
	"path/filepath"

	"github.com/88250/gulu"
	"github.com/siyuan-note/filelock"
	"github.com/siyuan-note/logging"
	"github.com/siyuan-note/siyuan/kernel/util"
)

const firstLaunchNoticeVersion = 1

type firstLaunchNoticeState struct {
	AntiResaleNotice int `json:"antiResaleNotice"`
}

func FirstLaunchNoticeAcknowledged() bool {
	statePath := firstLaunchNoticeStatePath()
	data, err := filelock.ReadFile(statePath)
	if err != nil {
		if !os.IsNotExist(err) {
			logging.LogWarnf("read SiYuan Unlock state [%s] failed: %s", statePath, err)
		}
		return false
	}

	state := &firstLaunchNoticeState{}
	if err = gulu.JSON.UnmarshalJSON(data, state); err != nil {
		logging.LogWarnf("parse SiYuan Unlock state [%s] failed: %s", statePath, err)
		return false
	}
	return state.AntiResaleNotice >= firstLaunchNoticeVersion
}

func AcknowledgeFirstLaunchNotice() error {
	state := &firstLaunchNoticeState{AntiResaleNotice: firstLaunchNoticeVersion}
	data, err := gulu.JSON.MarshalIndentJSON(state, "", "  ")
	if err != nil {
		return err
	}

	statePath := firstLaunchNoticeStatePath()
	if err = os.MkdirAll(filepath.Dir(statePath), 0755); err != nil {
		return err
	}
	return filelock.WriteFile(statePath, data)
}

func firstLaunchNoticeStatePath() string {
	return filepath.Join(util.HomeDir, ".config", "siyuan", "siyuan-unlock.json")
}
