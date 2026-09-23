# 官方源码与个人发布流程

## 当前仓库

| 用途 | GitHub 仓库 | 本地目录 | 基线 |
| --- | --- | --- | --- |
| 主源码 | [Anemone95/siyuan-unlock](https://github.com/Anemone95/siyuan-unlock)，直接 fork `siyuan-note/siyuan` | `/Users/wenyuan/Work/siyuan-unlock` | `60a4387cc1ce0cd0c7a61c2343e5a6a020758c0a`，3.8.5 |
| iOS 壳 | [Anemone95/siyuan-ios](https://github.com/Anemone95/siyuan-ios)，直接 fork `siyuan-note/siyuan-ios` | `/Users/wenyuan/Work/siyuan-ios` | `7604e5893ee06d5cebe50861e2736c9249701fd8` |
| 解锁补丁 | [appdev/siyuan-unlock](https://github.com/appdev/siyuan-unlock) | 构建时单独获取 | 初始核验提交 `4256ee734d7fa3a7309f4e64082f223f1faba70c` |

两个本地仓库均有独立 Git 对象库。`origin` 指向个人 fork，`upstream` 指向对应官方源码；主仓库另有 `unlock` remote 指向补丁提供方。个人恢复功能直接维护在源码及新增模块中，`git diff` 展示实际改动。

## 同步顺序

在当前修改完成评审并保存为提交后，主仓库执行：

```sh
git fetch upstream
git merge upstream/master
```

iOS 仓库执行：

```sh
git fetch upstream
git merge upstream/main
```

已发布的主分支采用 merge 保留历史。个人尚未发布的开发分支可用 rebase 整理提交。同步后运行恢复、session、前端和绑定测试，再由维护者发布自己的源码提交。

补丁提供方单独更新：

```sh
git ls-remote unlock refs/heads/master
```

审查新的补丁提交，将完整 SHA 写入 `scripts/personal-build-inputs.json`。该文件统一记录解锁补丁、个人 iOS 壳和官方 Android 壳的提交；同步壳源码后也更新对应条目。主源码沿官方历史维护，构建输入随提交一起评审。

## 构建与发布入口

GitHub Actions 的入口为 `Release our SiYuan source`，定义在 `.github/workflows/personal-release.yml`。输入为：

| 参数 | 内容 |
| --- | --- |
| `version` | 当前源码的版本，例如 `v3.8.5`，与 `app/package.json` 校验一致 |
| `release_tag` | 个人发布标签，例如 `v3.8.5-unlock.1`，指向本次个人源码提交 |
| `unlock_ref` | 可选，覆盖配置文件中的解锁补丁提交 |
| `ios_ref` | 可选，覆盖个人 iOS 壳的完整提交 SHA |
| `android_ref` | 可选，覆盖官方 Android 壳的完整提交 SHA |

入口校验版本、提交格式和 Android 签名配置，创建与当前源码提交关联的草稿 Release。草稿中记录所有源码提交及 Android 证书指纹，相同输入可复用草稿；现有标签指向其他提交、草稿来源不一致或已经发布时，构建会明确报错。同标签的发布工作流串行执行。

桌面、Android、iOS 工作流将产物上传为 Actions artifacts；Docker 构建独立的版本标签。最终任务在所有平台成功后核对来源记录、壳提交和签名指纹，汇总文件到 Release，再提升容器 `latest` 并发布草稿。失败构建保留草稿，GitHub 的重新运行失败任务可继续同一次发布。

每个平台先检出当前个人仓库的 `github.sha`，再通过共同的 composite action 检出固定补丁提交。`scripts/prepare-personal-build.py` 在独立构建目录复制源码，校验前端与内核版本一致，依次执行五个补丁的 `git apply --check` 和 `git apply`。补丁直接从 Git 对象读取，保证 Windows 换行转换下的哈希一致。它记录源码提交、补丁提交、各补丁哈希、版本和包管理器版本；移动端工作流追加壳提交和 Android 签名指纹。发布资产包含这些来源记录。

本地可以在保留未提交源码修改的情况下验证相同准备步骤：

```sh
python3 scripts/prepare-personal-build.py \
  --source . \
  --patch-repo /path/to/pinned-unlock-checkout \
  --destination /path/to/new-build-directory/siyuan \
  --version v3.8.5
```

构建输入中的 `source_edits` 记录本地改动的文件哈希。GitHub 上已提交源码的干净检出对应空映射。

## 平台接入

| 工作流 | 保留的产物及校验 |
| --- | --- |
| `personal-desktop.yml` | Linux x64/arm64、macOS x64/arm64、Windows x64；Linux 静态 PIE 校验和 `.deb` 包 |
| `personal-android.yml` | 官方包名与 AppDev 包名的 arm64 APK；固定补丁源中的 Android 两个补丁；实际 APK 包名校验 |
| `personal-ios.yml` | 使用 macOS 15 / Xcode 26.2 构建；Swift 状态测试；完整 unsigned IPA；核验 `ShorthandShare.appex` 存在 |
| `personal-docker.yml` | Linux amd64/arm64/armv7 镜像；发布到 `ghcr.io/anemone95/siyuan-unlock`，全部构建成功后提升 `latest` |

Go 和 gomobile 版本来自源码 `go.mod`，pnpm 版本来自 `app/package.json`，前端安装使用冻结的锁文件。Android 使用 JDK 17、SDK 36、Build Tools 36.0.0 和 NDK 28.2.13676358；Windows 显式配置 MinGW GCC 和固定版本的 goversioninfo。解锁账户与同步校验来自同一补丁提交；恢复和 session 测试来自个人源码。iOS IPA 可按设备证书和 App Group 配置签名，保留分享扩展。

## 签名、CI 与验证

Android 的固定自签名发布密钥已配置为 `KEYSTORE`、`KEYSTORE_PASSWORD` 两个 secrets，公钥指纹保存在 `ANDROID_SIGNING_SHA256` 仓库变量中。流水线使用 apksigner 核验两种包名的 APK 都由同一证书签名。主密钥位于本机仓库外的 `~/.config/siyuan-unlock/android/siyuan-release.jks`，后续升级沿用该密钥。[Android 签名说明](https://developer.android.com/studio/publish/app-signing)

GHCR 使用当前仓库的 `GITHUB_TOKEN` 和 `packages: write` 权限，镜像通过 OCI source 标签关联当前仓库。[GitHub 容器发布说明](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)

容器的 Go/CGo 编译阶段在构建机原生架构上运行，通过固定镜像摘要的 [xx 工具](https://github.com/tonistiigi/xx#go--cgo) 生成 amd64、arm64 和 arm/v7 内核。构建时验证二进制目标架构，并在每个最终镜像内执行 `kernel --version`，检查实际加载与运行。

`personal-check.yml` 在主分支推送和 PR 上执行 Python 发布工具测试、workflow 静态检查、真实解锁补丁与账户校验、Go race、前端协议和 lint，并复用完整 iOS 构建来产生可下载的测试 IPA。此 CI 使用只读仓库权限。

手动运行该检查并勾选 `full_build`，还会构建桌面、自签名 Android 和三种架构的容器镜像。产物保存在 Actions artifacts，容器构建采用本地缓存输出，用于四平台发布前验证。

`personal-android.yml` 和 `personal-docker.yml` 也提供独立手动入口，使用同样的版本和固定提交参数，分别验证 Android 工具链与签名、三种架构的容器构建。Docker 独立入口仅执行构建验证。手动全平台检查与推送检查使用不同的并发组，允许正在运行的完整构建保留结果。

本地核验包括：17 项发布工具回归、12 项前端测试、Go race、Swift 场景与页面状态测试、完整 workflow actionlint，以及两个真实 Android 补丁。GitHub 上已实测草稿创建、同输入复用、混合输入拒绝和文件上传，并清理了测试草稿及资产。完整四平台 Release 通过手动入口发布；iOS 最新场景改动的真机覆盖见 [ios-recovery.md](ios-recovery.md)。
