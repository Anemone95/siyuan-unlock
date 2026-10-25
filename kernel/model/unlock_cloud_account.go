package model

import (
	"github.com/88250/gulu"
	"github.com/siyuan-note/siyuan/kernel/conf"
	"github.com/siyuan-note/siyuan/kernel/util"
)

// ActivateLocalSubscriber 设置并保存本地订阅身份，同步等功能无需云端账号即可使用。
func ActivateLocalSubscriber() *conf.User {
	user := &conf.User{
		UserId:                     "0",
		UserName:                   "_",
		UserAvatarURL:              "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
		UserTitles:                 []*conf.UserTitle{},
		UserCreateTime:             "29991231 00:00:00",
		UserSiYuanProExpireTime:    -1,
		UserToken:                  "token",
		UserTokenExpireTime:        "32503593600",
		UserSiYuanSubscriptionType: 1,
		UserSiYuanOneTimePayStatus: 1,
	}
	data, _ := gulu.JSON.MarshalJSON(user)
	cloudAccountMu.Lock()
	defer cloudAccountMu.Unlock()
	Conf.SetUser(user)
	Conf.UserData = util.AESEncrypt(string(data))
	Conf.Save()
	return user
}
