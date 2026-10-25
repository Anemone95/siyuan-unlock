import type {IOSRecoveryProtocol} from "./iosRecoveryProtocol";

const initialCallbacks = new WeakMap<object, {callback?: () => void}>();

// Model 提供正常重连参数，适配器独立管理注册状态和仅消费一次的初始化回调。
export const iosRegisterModel = (recovery: IOSRecoveryProtocol | undefined, owner: object,
                                options: {type?: string; callback?: () => void}, reconnect: () => void) => {
    if (!recovery || recovery.entries.has(owner)) { return false; }
    initialCallbacks.set(owner, {callback: options.callback});
    recovery.register(owner, options.type === "main", reconnect);
    return true;
};

export const iosOpenModel = (recovery: IOSRecoveryProtocol | undefined, owner: object, socket: WebSocket) => {
    if (!recovery) { return false; }
    if (recovery.current(owner, socket)) {
        const initial = initialCallbacks.get(owner);
        const callback = initial?.callback;
        if (initial) { initial.callback = undefined; }
        callback?.call(owner);
        recovery.open(owner, socket);
    }
    return true;
};
