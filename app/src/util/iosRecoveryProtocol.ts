// 恢复保留当前页面，完成状态覆盖登记的连接和已确认写入，响应丢失的写入保持待确认。
export interface ServingEvent {
    pageID: string;
    requestID: number;
    generation: number;
    state: string;
    detail?: string;
}
export interface RecoverySocket { readyState: number; close: () => void; }
interface Entry {
    main: boolean;
    connect: () => void;
    socket?: RecoverySocket;
    generation: number;
    opened: boolean;
}

export class IOSRecoveryProtocol {
    public pageID: string;
    public event: ServingEvent;
    public entries = new Map<object, Entry>();
    public writes = new Map<number, {body: string; uncertain: boolean}>();
    private nextWrite = 0;
    private connected = "";
    private completed = "";
    private send: (message: object) => void;
    private status: (state: string, detail: string) => void;
    private blocked = false;

    constructor(pageID: string, send: (message: object) => void, status: (state: string, detail: string) => void) {
        this.pageID = pageID;
        this.send = send;
        this.status = status;
    }

    public handshake() { this.send({kind: "bridgeReady", protocolVersion: 1, pageID: this.pageID}); }

    public receive(event: ServingEvent) {
        if (event.pageID !== this.pageID || (this.event &&
            (event.requestID < this.event.requestID || event.generation < this.event.generation))) { return; }
        if (event.state === "Cancelled") { return; }
        const previous = this.event;
        if (previous && ["Failed", "Stopped"].includes(previous.state) &&
            previous.requestID === event.requestID && previous.generation === event.generation &&
            event.state === "TransportAccepting") { return; }
        this.event = event;
        if (event.state !== "TransportAccepting") {
            for (const entry of this.entries.values()) { this.close(entry); }
            this.status(event.state, event.detail || "");
            return;
        }
        if (!previous || previous.generation !== event.generation) { this.blocked = false; }
        for (const entry of this.entries.values()) { this.connect(entry); }
        this.check();
    }

    public register(owner: object, main: boolean, connect: () => void) {
        const entry = {main, connect, generation: -1, opened: false};
        this.entries.set(owner, entry);
        this.connect(entry);
    }

    private connect(entry: Entry) {
        if (this.event?.state !== "TransportAccepting" || entry.generation === this.event.generation) { return; }
        this.close(entry);
        entry.generation = this.event.generation;
        entry.connect();
    }

    public attach(owner: object, socket: RecoverySocket) {
        const entry = this.entries.get(owner);
        if (entry) { entry.socket = socket; entry.opened = false; }
    }

    public current(owner: object, socket: RecoverySocket) {
        const entry = this.entries.get(owner);
        return !!entry && entry.socket === socket && entry.generation === this.event?.generation && this.event.state === "TransportAccepting";
    }

    public open(owner: object, socket: RecoverySocket) {
        if (!this.current(owner, socket)) { return false; }
        this.entries.get(owner).opened = true;
        this.check();
        return true;
    }

    public disconnect(owner: object, socket: RecoverySocket, reason = "") {
        if (!this.current(owner, socket)) { return; }
        if (reason.includes("close websocket")) { this.remove(owner); return; }
        const entry = this.entries.get(owner);
        entry.opened = false;
        if (reason.includes("unauthenticated")) { this.entries.delete(owner); }
        this.fail(reason.includes("unauthenticated") ? "unauthenticated" : "socket_disconnected");
    }

    public fail(detail: string) {
        this.blocked = true;
        this.status("Failed", detail);
        if (this.event) { this.ack("frontendFailed"); }
    }

    public remove(owner: object) {
        const entry = this.entries.get(owner);
        this.entries.delete(owner);
        if (entry) { this.close(entry); }
        this.check();
    }

    private close(entry: Entry) {
        const socket = entry.socket;
        entry.socket = undefined;
        entry.opened = false;
        if (socket && socket.readyState < 2) { socket.close(); }
    }

    public beginWrite(body: string) {
        const id = ++this.nextWrite;
        this.writes.set(id, {body, uncertain: false});
        return id;
    }

    public finishWrite(id: number, acknowledged: boolean) {
        const write = this.writes.get(id);
        if (!write) { return; }
        if (acknowledged) { this.writes.delete(id); } else { write.uncertain = true; }
        this.check();
    }

    public canWrite() {
        return this.event?.state === "TransportAccepting" && !this.blocked &&
            Array.from(this.entries.values()).some(e => e.main && e.opened) &&
            Array.from(this.entries.values()).every(e => e.opened) &&
            !Array.from(this.writes.values()).some(w => w.uncertain);
    }

    public retry() { this.send({kind: "retry", pageID: this.pageID}); }
    public cancel() { this.send({kind: "cancel", pageID: this.pageID}); }

    private ack(kind: string) {
        this.send({kind, pageID: this.pageID, requestID: this.event.requestID, generation: this.event.generation});
    }

    private check() {
        if (this.event?.state !== "TransportAccepting" || this.blocked) { return; }
        const entries = Array.from(this.entries.values());
        const key = `${this.event.requestID}:${this.event.generation}`;
        if (!entries.some(e => e.main && e.opened)) { return; }
        if (this.connected !== key) { this.connected = key; this.ack("frontendConnected"); }
        if (Array.from(this.writes.values()).some(w => w.uncertain)) {
            this.status("UncertainWrites", "write_acknowledgement_missing");
        } else if (entries.every(e => e.opened) && this.writes.size === 0) {
            this.status("Connected", "");
            if (this.completed !== key) { this.completed = key; this.ack("recoveryCompleted"); }
        } else { this.status("Recovering", "pending_connections_or_writes"); }
    }
}
