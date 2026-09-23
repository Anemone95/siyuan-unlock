import {IOSRecoveryProtocol, ServingEvent} from "./iosRecoveryProtocol";

interface RecoveryWindow {
    siyuanRecovery?: {pageID: string; receive: (event: ServingEvent) => void; handshake: () => void};
    webkit?: {messageHandlers?: {kernelRecovery?: {postMessage: (value: object) => void}}};
}

let protocol: IOSRecoveryProtocol;
const queued: Array<() => void> = [];
let banner: HTMLElement;

// 原生桥能力决定手机与 iPad 桌面布局的恢复策略，其他构建沿用 Model 的原有策略。
export const iosRecovery = () => {
    const host = window as unknown as RecoveryWindow;
    const bridge = host.webkit?.messageHandlers?.kernelRecovery;
    if (!bridge) { return undefined; }
    if (!protocol) {
        protocol = new IOSRecoveryProtocol(crypto.randomUUID(), message => { debug("bridge", message); bridge.postMessage(message); }, updateStatus);
        host.siyuanRecovery = {pageID: protocol.pageID, receive: event => protocol.receive(event), handshake: () => protocol.handshake()};
        for (const name of ["beforeinput", "paste", "drop", "compositionstart"]) {
            document.addEventListener(name, event => {
                if (!protocol.canWrite() && (event.target as HTMLElement)?.closest("[contenteditable=true], input, textarea")) {
                    event.preventDefault();
                }
            }, true);
        }
        protocol.handshake();
    }
    return protocol;
};

const debug = (kind: string, data: object) => {
    if (sessionStorage.getItem("iosRecoveryLogging") === "1") { console.debug("[recovery]", kind, data); }
};

const updateStatus = (state: string, detail: string) => {
    debug("status", {state, detail});
    if (protocol.canWrite()) {
        const pending = queued.splice(0);
        pending.forEach(send => send());
    }
    if (state === "Connected") {
        banner?.remove();
        banner = undefined;
        window.siyuan?.dialogs?.find(item => item.element.id === "errorLog")?.destroy();
        return;
    }
    if (!document.body) { return; }
    if (!banner) {
        banner = document.createElement("div");
        banner.setAttribute("role", "status");
        banner.style.cssText = "position:fixed;z-index:10000;bottom:0;left:0;right:0;padding:12px;background:var(--b3-theme-background);color:var(--b3-theme-on-background);border-top:1px solid var(--b3-theme-primary)";
        document.body.append(banner);
    }
    banner.replaceChildren();
    const text = document.createElement("span");
    text.textContent = state === "UncertainWrites" ? "Edits preserved. A write response is missing; review is required before editing can continue." :
        state === "Failed" ? `Connection failed (${detail}). Edits preserved. ` :
        state === "Stopped" ? "Kernel stopped. Reopen SiYuan to continue. " :
        state === "Paused" || state === "Pausing" ? "Connection paused. Edits preserved. " :
        "Restoring connection. Edits preserved. ";
    banner.append(text);
    for (const [label, action] of [["Retry", () => protocol.retry()], ["Cancel", () => protocol.cancel()]] as const) {
        const button = document.createElement("button");
        button.textContent = label;
        button.onclick = action;
        banner.append(button);
    }
};

export const iosKernelError = () => {
    const recovery = iosRecovery();
    if (!recovery) { return false; }
    if (recovery.event?.state === "TransportAccepting") { recovery.fail("request_failed"); }
    else { updateStatus(recovery.event?.state || "Starting", recovery.event?.detail || ""); }
    return true;
};

// 保留事务原文直到响应确认；排队请求等待首次发送，不确定写入保留供核对。
export const iosTransactionFetch = (url: string, init: RequestInit): Promise<Response> | undefined => {
    const recovery = iosRecovery();
    if (!recovery || url !== "/api/transactions") { return undefined; }
    const body = String(init.body || "");
    const id = recovery.beginWrite(body);
    return new Promise<Response>((resolve, reject) => {
        const send = () => {
            fetch(url, {...init, body}).then(async response => {
                let acknowledged = false;
                try { acknowledged = response.ok && (await response.clone().json()).code === 0; } catch { /* 保留待确认的原文。 */ }
                debug("write_response", {id, acknowledged});
                recovery.finishWrite(id, acknowledged);
                resolve(response);
            }).catch(error => {
                debug("write_response", {id, acknowledged: false});
                recovery.finishWrite(id, false);
                reject(error);
            });
        };
        if (recovery.canWrite()) { send(); } else { queued.push(send); }
    });
};
