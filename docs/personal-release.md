# 个人版本的同步与发布

## 分支结构

| 仓库 | 分支 | 内容 |
| --- | --- | --- |
| [Anemone95/siyuan-unlock](https://github.com/Anemone95/siyuan-unlock) | `master` | 思源正式版 tag + 两个个人提交 |
| [Anemone95/siyuan-ios](https://github.com/Anemone95/siyuan-ios) | `main` | 上游 `main` + 一个 iOS 恢复提交 |

`master` 上的两个个人提交：

1. `SiYuan Unlock: account-free sync and iOS kernel recovery`：全部功能改动，包括免账号同步与 iOS 内核恢复（见 [ios-recovery.md](ios-recovery.md)）。
2. `Rebase onto official releases and publish our build`：两个工作流、账号检查脚本和本文档。

审阅个人改动只需看这两个提交：

- GitHub：`https://github.com/Anemone95/siyuan-unlock/compare/vX.Y.Z...master`
- 每次 rebase 后比较前后两版个人提交：`git range-diff vOLD..OLD_MASTER vNEW..master`

## 自动同步

`personal-sync.yml` 每小时检查官方最新正式 Release。`master` 尚未包含该 tag 时：

1. 把 `master` rebase 到该 tag，把 siyuan-ios 的 `main` rebase 到上游 `main`。
2. 两边都成功后推送 siyuan-ios `main`、`master` 和官方 tag。
3. 任一仓库有冲突时，开 Issue「Rebase onto vX.Y.Z」列出冲突文件；Issue 打开期间同步暂停。

## 发布

`personal-release.yml` 在推送 `master` 时运行测试。该版本还没有个人 Release 时，构建全部平台并发布 `vX.Y.Z-unlock.1`。在 Actions 页面手动运行时构建全部平台：在 `master` 上发布下一个 `vX.Y.Z-unlock.N`，在其他分支上只构建。

| 平台 | 来源 | 产物 |
| --- | --- | --- |
| 桌面 | 上游 `desktop-build.yml`，配置与上游 `cd.yml` 一致 | Linux x64、macOS x64/arm64、Windows x64 |
| Android | 官方 `siyuan-android` 同版本 tag | `top.anemone.siyuan`，用 `KEYSTORE` 签名 |
| iOS | `Anemone95/siyuan-ios` 的 `main` | 未签名 ipa |
| Docker | 上游 `Dockerfile`，复用上游 ONNX 运行库镜像 | `ghcr.io/anemone95/siyuan-unlock`，amd64/arm64/armv7 |

所有平台构建成功后，同一次运行创建 Release、上传产物，并给 Docker 镜像打上发布标签和 `latest`。

## 本地解决冲突

先处理 siyuan-ios，再处理主仓库，因为推送 `master` 会触发发布：

```sh
# siyuan-ios
git fetch upstream main
git rebase upstream/main          # 解决冲突后 git rebase --continue
git push --force-with-lease origin main

# siyuan-unlock
git fetch upstream tag vX.Y.Z
git rebase vX.Y.Z                 # 解决冲突后 git rebase --continue
git push --force-with-lease origin master vX.Y.Z
```

推送后关闭冲突 Issue。

## 凭据

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `UPSTREAM_SYNC_SSH_KEY` | secret | 本仓库的可写 deploy key，推送 rebase 后的 `master` |
| `IOS_SYNC_SSH_KEY` | secret | siyuan-ios 的可写 deploy key，推送 rebase 后的 `main` |
| `KEYSTORE`、`KEYSTORE_PASSWORD` | secret | Android 签名密钥（base64 编码的 jks，别名 `siyuan`） |
| `ANDROID_SIGNING_SHA256` | variable | Android 签名证书的 SHA-256 指纹，构建后核对 |
