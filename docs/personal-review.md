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
| Docker 架构列表包含基础镜像未提供的 `linux/arm/v8` | 核对实际 manifest 后保留 amd64、arm64 和 arm/v7；镜像推送到当前账号 GHCR |

## 验证范围

- 发布工具 17 项回归覆盖来源一致性、草稿分页与复用、错误版本、被修改补丁、目录替换和 Windows 换行。
- Go race 覆盖独立 listener、实际 util/server 接入及 session 身份删除；前端 12 项测试和 lint 通过。
- Swift 状态测试和 iPhoneOS SDK typecheck 通过，包含冷启动续接、页面重新挂接、场景集合和过期 ACK。
- 固定 Android 源码通过两个真实补丁的适用性检查；固定自签名密钥已配置，APK 构建时核验签名指纹。
- `personal-check.yml` 在推送后继续验证 Linux、Windows 发布工具和完整 iOS 构建。公开 Release 由独立手动入口执行。

## 待完成的产品验证

当前手机已确认 build 3 的启动修复。最新场景订阅精简、分享、长时间后台、iPad 多 scene 和外部 HTTP/HTTPS 仍需相应真机覆盖。未确认写入的持久回执、WebContent 丢失后的持久恢复，以及断连期间远端修改的增量协调，按 [ios-recovery.md](ios-recovery.md) 的范围继续验证和完善。
