# 官方源码与个人发布流程

## 当前仓库

| 用途 | GitHub 仓库 | 本地目录 | 基线 |
| --- | --- | --- | --- |
| 主源码 | [Anemone95/siyuan-unlock](https://github.com/Anemone95/siyuan-unlock)，直接 fork `siyuan-note/siyuan` | `/Users/wenyuan/Work/siyuan-unlock` | `60a4387cc1ce0cd0c7a61c2343e5a6a020758c0a`，3.8.5 |
| iOS 壳 | [Anemone95/siyuan-ios](https://github.com/Anemone95/siyuan-ios)，直接 fork `siyuan-note/siyuan-ios` | `/Users/wenyuan/Work/siyuan-ios` | `7604e5893ee06d5cebe50861e2736c9249701fd8` |
| 解锁补丁 | [appdev/siyuan-unlock](https://github.com/appdev/siyuan-unlock) | 构建时单独获取 | 初始核验提交 `4256ee734d7fa3a7309f4e64082f223f1faba70c` |

两个本地仓库均有独立 Git 对象库。`origin` 指向个人 fork，`upstream` 指向对应官方源码；主仓库另有 `unlock` remote 指向补丁提供方。个人恢复功能直接维护在源码及新增模块中，`git diff` 展示实际改动。

## 自动跟随正式版本

`Sync official release and publish` 工作流定义在 `.github/workflows/personal-upstream.yml`，每小时第 17 分钟检查官方最新正式 Release，也支持手动启动和 `check_only` 预览。

1. 读取官方 Release 的 `tag_name`，解析 tag 的真实提交，包括 annotated tag。
2. 在干净检出中将该 tag 合并到个人 `master`，保留个人修改，并核对合并后的源码版本。
3. 将 Android 壳固定到同版本 tag 的提交；iOS 壳与解锁补丁沿用配置文件中的已审核提交。
4. 在独立目录检查并应用固定解锁补丁，验证前端与内核版本一致。
5. 原子推送 `master` 和个人发布标签 `vX.Y.Z-unlock.1`，以普通快进检查保护远端并发修改。
6. 以个人发布标签作为 `workflow_dispatch` 的 ref，启动四平台构建。所有平台校验通过后公开 Release。

已有个人 Release、草稿或发布标签的版本会跳过。真实的 Git 合并冲突交给 Copilot 创建修复 PR，维护者确认合并后继续同步。移动端 tag 缺失、补丁不兼容或并发推送冲突会报告失败；维护者处理后可重新执行同步。已有发布任务使用 GitHub 的重新运行失败任务继续；若已推送标签但 dispatch 未成功，可针对该标签手动启动：

```sh
gh workflow run personal-release.yml --ref vX.Y.Z-unlock.1 -f version=vX.Y.Z -f release_tag=vX.Y.Z-unlock.1
```

自动 Git 推送使用仅授权本仓库的写入 deploy key，私钥保存在 `UPSTREAM_SYNC_SSH_KEY` Actions secret 中。工作流调度使用 `GITHUB_TOKEN` 的 `actions: write` 权限。[GitHub 工作流触发规则](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)

2026-09-23 核验时，官方 `v3.8.5` tag 与个人源码基线均为 `60a4387cc1ce0cd0c7a61c2343e5a6a020758c0a`；该基线后的提交均为个人恢复功能和发布流程修改。

## Copilot 冲突处理

`scripts/personal-copilot.py` 使用 GitHub 原生 Copilot cloud agent。同步检测到未合并文件后，会把版本、准确 tag 提交、个人基线和冲突文件写入 Issue，分配给 Copilot，并要求生成供维护者审核的修复 PR。同一上游提交复用已有任务；已关闭任务保留记录，由维护者从既有代理任务或 PR 继续处理。修复过程保留事件驱动恢复、编辑状态与 session 身份语义。

仓库的 Issues 已启用，Copilot 已出现在可分配代理列表。自动分配需要仓库 secret `COPILOT_AGENT_TOKEN`，保存仅选择本仓库的 fine-grained 用户令牌，授予 Metadata 读取权限，以及 Actions、Contents、Issues、Pull requests 读写权限。该用户需要拥有可用的 Copilot cloud agent 订阅及仓库访问权。[GitHub Copilot API 的认证要求](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-via-the-api)

配置后，手动运行同步工作流并选中 `check_only`，会核验该令牌对应的 Copilot 账户和仓库访问。Copilot PR 的 CI 按 GitHub 设置执行，默认情况下维护者在 PR 中批准工作流运行；检查和人工评审完成后合并，下一次同步检查接续四平台发布。[GitHub Copilot 的 PR 工作流规则](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github#managing-github-actions-workflow-runs)

## 手动同步与固定依赖

手动同步也使用目标正式版本的 tag。当前修改完成评审并保存为提交后，以 `v3.8.5` 为例执行，升级时替换为实际 Release tag：

```sh
git fetch upstream tag v3.8.5
git merge --no-ff v3.8.5
```

已发布的主分支采用 merge 保留历史。iOS 壳独立审查并同步所需上游提交，随后更新主仓库中的固定 SHA。同步后运行恢复、session、前端和绑定测试。

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

人工补充草稿说明时，使用 `gh release edit <release_tag> --notes-file <file>`，并保留正文中的 `siyuan-build-inputs` 来源标记。GitHub CLI 会在更新请求中保留标签；通过 REST API 更新草稿时同时传递准确的 `tag_name`，并回读核对标签与源码提交。

桌面、Android、iOS 工作流将产物上传为 Actions artifacts；Docker 构建独立的版本标签。最终任务在所有平台成功后核对来源记录、壳提交和签名指纹，汇总安装包到 Release，再提升容器 `latest` 并发布草稿。Release 正文使用英文，附件保留应用安装包；JSON 来源记录保存在 Actions artifacts 中。失败构建保留草稿，GitHub 的重新运行失败任务可继续同一次发布。

每个平台先检出当前个人仓库的 `github.sha`，再通过共同的 composite action 检出固定补丁提交。`scripts/prepare-personal-build.py` 在独立构建目录复制源码，校验前端与内核版本一致，依次执行五个补丁的 `git apply --check` 和 `git apply`。补丁直接从 Git 对象读取，保证 Windows 换行转换下的哈希一致。它记录源码提交、补丁提交、各补丁哈希、版本和包管理器版本；移动端工作流追加壳提交和 Android 签名指纹。这些来源记录由最终发布任务校验，并保留为 Actions artifacts。

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

本地核验包括：37 项发布、上游同步与 Copilot 分配回归、12 项前端测试、Go race、Swift 场景与页面状态测试、完整 workflow actionlint，以及两个真实 Android 补丁。同步回归覆盖上游分支领先 tag、保留个人修改、annotated tag、重复发布、补丁失败和并发推送保护；Copilot 回归覆盖实际冲突上下文、任务去重、外部 Issue 隔离、缺失令牌和分配失败。GitHub 上已实测草稿创建、同输入复用、混合输入拒绝和文件上传，并清理了测试草稿及资产。完整四平台 Release 支持手动入口和上游正式版自动同步入口；iOS 最新场景改动的真机覆盖见 [ios-recovery.md](ios-recovery.md)。
