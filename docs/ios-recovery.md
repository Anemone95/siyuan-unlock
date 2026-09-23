# iOS 事件恢复：实现与验证

主源码基线为 `60a4387cc1ce0cd0c7a61c2343e5a6a020758c0a`，版本 3.8.5；iOS 基线为 `7604e5893ee06d5cebe50861e2736c9249701fd8`。实现直接位于两个源码仓库中，发布流程见 [personal-release.md](personal-release.md)。

## 模块与上游接入

| 位置 | 职责 |
| --- | --- |
| `kernel/server/mobiletransport/` | 稳定的逻辑 listener、物理 listener 代次、串行事件、连接所有权和独立测试 |
| `kernel/server/mobile_transport.go` | iOS 启用入口、监听工厂、HTTP/h2c 连接跟踪和失败事件 |
| `kernel/mobile/mobile_recovery.go` | gomobile observer、单次冷启动和最终退出 facade |
| `kernel/util/serving_lifecycle.go` | cmux/HTTP2 setup 和子 server 退出观察 |
| `kernel/util/push_sessions.go` | session 表写入同步；实际回归测试覆盖内外两层删除竞争 |
| `app/src/util/iosRecoveryProtocol.ts` | 页面、请求、代次、socket 状态与事务保留 |
| `app/src/util/iosKernelRecovery.ts` | native bridge、输入保护、可见状态和事务发送适配 |
| `app/src/util/iosModelRecovery.ts` | Model 注册及首次连接 callback 的一次性消费 |
| iOS `KernelRecoveryCoordinator.swift` | UIScene 通知订阅、需求汇总、页面握手、事件投递和首次启动续接 |

主仓库已有文件的接入为 `serve.go`、`cmux.go`、`websocket.go`、`Model.ts`、`fetch.ts`、`kernelFault.ts` 和 `BacklinkContent.ts`，当前合计新增 56 行、删除 8 行。iOS 恢复接入集中于 `ViewController.swift` 和 Xcode 源文件成员登记，合计新增 16 行、删除 14 行。签名 App Group 配置另涉及 `ShorthandDraftStore.swift`、`SceneDelegate.swift`、`ShareViewController.swift` 的四处替换。

`Model.ts` 当前新增 13 行，注册和首次 callback 状态由独立适配器维护；显式关闭后再次调用 connect 会建立新的登记。Swift 协调器按应用生命周期订阅 scene 通知，在页面 owner 更换时保持订阅，并用当前场景快照替换过期集合。`SceneDelegate` 中保留的是分享目录的 App Group 接入。同步上游时重点核对 listener/server 初始化、Model 的事件与销毁语义、事务响应、页面导航和 Xcode target membership。

## 时序与数据

前台 scene 需求产生新的 request，逻辑 listener 创建新代次 socket；serving setup 完成并进入 Accept 路径后发出 `TransportAccepting`。JS 完成当前页面握手后重放最新状态，主连接真实 `onopen` 产生 `FrontendConnected`，所有有效登记连接与已定义恢复工作完成后产生 `RecoveryCompleted`。

失败和取消保留各自 request/generation；过期 bind、socket 或页面事件被身份检查隔离。普通暂停关闭 idle HTTP/1、未完成握手和 WebSocket，已接纳的活跃 HTTP/1 请求完成后关闭。HTTP/2 连接保持归属并在对端关闭或最终退出时回收，以保留响应帧完整性。最终 Close 终止 waiter 和归属资源。

事务适配器保留序列化原文：未发送请求等待连接事件后发送一次；成功 ACK 释放记录；已发送但响应不确定的请求保留并保护输入。正常恢复延续原页面和编辑状态。持久事务回执、WebContent 丢失后的持久保留，以及断连期间其他客户端修改的增量协调，仍是发布前待完成的数据语义。

session 回归先在上游函数上复现了旧连接断开删除新 session，再通过对象身份条件删除和内外层一致的同步修复。测试包含 main/auth session 和 1000 次外层判空/新增交错。

## 启动故障与真机结果

iPhone 17 / iOS 27.0 上的 build 2 出现长时间白屏后退出。设备 crash 报告为 FRONTBOARD `0x8BADF00D`，scene-create 在 19.98 秒触发看门狗；主线程位于 `usleep`、`waitFotKernelHttpServing`、`viewDidLoad`。首次 listener 等待前台 scene，而阻塞的 viewDidLoad 使该 scene 事件无法推进。

build 3 将首次启动改为 TransportAccepting 的一次性续接，viewDidLoad 完成后交还主线程。主程序与分享扩展均完成签名和原位安装，用户已确认启动修复有效。主程序和扩展使用各自 Bundle ID，以及同一已授权 application-identifier 和 App Group。

当前源码在 build 3 基础上又精简了 scene 通知、Model 注册和 cmux 观察接入。组件验证已通过；该精简版的真机前后台、锁屏、编辑、分享、WebContent 重建、iPad 多 scene、外部 HTTP/HTTPS 和长时间运行覆盖仍待验证。已确认的 build 3 启动结果与这些待验证项目分别记录。

## 已执行验证

- 独立 listener 全套 `go test -race -timeout 120s ./server/mobiletransport` 通过。
- 实际 session/server/util 接入的 race 测试通过，包含 TLS/cmux、HTTP/2 和 feature gate。
- mobile facade 主机编译通过；主机桌面内核构建通过。
- 前端 12 个协议、实际 Model 和事务 fetch 测试通过；`pnpm run typecheck`、`pnpm run lint` 通过。
- Swift 冷启动续接、晚注册、旧快照、scene 汇总、页面身份和 ACK 顺序测试通过；协调器的 iPhoneOS SDK typecheck 通过。
- 评审回归覆盖页面重新挂接后清除旧 scene，以及 Model 显式关闭后再次连接。后者先复现了登记丢失，再通过当前登记表判断修复。
- build 3 的完整 Xcode 编译、主程序/分享扩展严格签名校验和真机安装通过。

恢复代码使用 channel、回调和显式生命周期事件。测试命令中的执行时限用于报告测试死锁。每次上游同步继续运行上述检查，并以真机测量补全尚未覆盖的场景。
