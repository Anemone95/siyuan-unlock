# 发布流水线与恢复代码评审

评审日期：2026-09-23。主源码基于官方 3.8.5，iOS 与解锁补丁的固定提交由 `scripts/personal-build-inputs.json` 管理。

## 已修正的问题

| 问题 | 修正与证据 |
| --- | --- |
| 相同 Model 关闭后再次显式连接，残留 callback 元数据使新 socket 缺少登记 | 改为按当前协议登记表判断；真实 Model 回归先复现登记数量为 0，再通过修正验证重新连接和迟到事件隔离 |
| 页面 owner 销毁后解绑 scene 通知，可能漏掉后台事件并保留过期 scene | 场景订阅改为应用级生命周期；重新挂接时用实际 scene 集合替换旧集合，补充状态回归 |
| 使用按标签查询接口查找草稿，实际得到缺失结果并重复创建草稿 | 改为分页检索有权限的发布列表；实际 GitHub 草稿创建、复用、资产上传和来源不一致拒绝均通过，测试对象已清理 |
| 草稿只比较主源码，无法识别不同补丁、移动端源码或 Android 签名的混用 | 来源标记覆盖全部提交、版本和签名指纹；校验现有 Git 标签的真实目标；同发布标签串行执行 |
| 平台任务直接修改 Release，文件错误可能被上传 action 忽略 | 平台任务仅上传有明确缺失文件检查的 Actions artifacts；最终任务核对来源及文件，再统一发布 |
| 本地目录被替换为文件时，构建快照仍保留旧目录结构 | 先处理已删除路径，再复制当前源码；回归覆盖替换、未提交编辑和原目录保持 |
| Windows 的换行转换影响补丁字节；goversioninfo 安装会改动依赖文件 | 从 Git 对象读取规范补丁原文；显式配置 GCC，以固定版本安装 goversioninfo |
| macOS 15 runner 默认 Xcode 为 16.4，低于当前 iOS 源码所需 SDK | iOS 固定使用已验证的 macOS 15 / Xcode 26.2；CI 执行完整 unsigned IPA 构建并检查分享扩展 |
| Android SDK action 的默认组件包含已撤下的 `tools`，导致安装退出 | 显式安装 `platform-tools`，再指定 SDK、Build Tools 与 NDK；实际 Android 构建通过 |
| Android 产物检查依赖固定文件名与 shell 文本匹配，失败信息不足 | 从 Gradle 元数据定位两种 APK，分别校验真实包名、版本和签名；错误证书与错误包名回归通过 |
| Docker 架构列表包含基础镜像未提供的 `linux/arm/v8` | 核对实际 manifest 后保留 amd64、arm64 和 arm/v7；镜像推送到当前账号 GHCR |
| ARM 容器在 QEMU 中编译 Go，超过一小时仍未完成 | 使用固定摘要的 xx 工具在构建机上交叉编译；三架构构建及最终镜像的 `kernel --version` 均通过，镜像构建约 9 分 22 秒 |

## 验证范围

- 发布工具 17 项回归覆盖来源一致性、草稿分页与复用、错误版本、被修改补丁、目录替换和 Windows 换行。
- Go race 覆盖独立 listener、实际 util/server 接入及 session 身份删除；前端 12 项测试和 lint 通过。
- Swift 状态测试和 iPhoneOS SDK typecheck 通过，包含冷启动续接、页面重新挂接、场景集合和过期 ACK。
- [Android 实际构建](https://github.com/Anemone95/siyuan-unlock/actions/runs/35895088786)通过；两个 APK 的包名、3.8.5 版本和固定自签名证书均已核验，产物与源码记录可从该次 Actions 下载。
- [桌面与 iOS 实际构建](https://github.com/Anemone95/siyuan-unlock/actions/runs/35889730847)的六种桌面任务及 iOS 任务均通过；该次总任务还包含随后单独修复和复测的 Android、Docker 任务。
- [Docker 实际构建](https://github.com/Anemone95/siyuan-unlock/actions/runs/35899392966)通过；amd64、arm64、arm/v7 二进制的目标架构和镜像内执行结果均通过校验。
- [最新源码 CI](https://github.com/Anemone95/siyuan-unlock/actions/runs/35899362684)全部通过，覆盖 Linux、Windows 发布工具、恢复回归、前端检查和完整 iOS 构建。公开 Release 由独立手动入口执行。
- [完整发布工作流](https://github.com/Anemone95/siyuan-unlock/actions/runs/35900081153)成功完成，已公开 [v3.8.5-unlock.1](https://github.com/Anemone95/siyuan-unlock/releases/tag/v3.8.5-unlock.1)，标签对应 `103502621eeb25effd85147551e822a68e277158`。20 个资产包含 11 个安装包与 9 份构建来源记录。GHCR 的版本标签与 `latest` 指向相同摘要，三架构 manifest 已通过匿名访问核验。

## 待完成的产品验证

当前手机已确认 build 3 的启动修复。最新场景订阅精简、分享、长时间后台、iPad 多 scene 和外部 HTTP/HTTPS 仍需相应真机覆盖。未确认写入的持久回执、WebContent 丢失后的持久恢复，以及断连期间远端修改的增量协调，按 [ios-recovery.md](ios-recovery.md) 的范围继续验证和完善。
