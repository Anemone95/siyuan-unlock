export const NOTICE_DELAY_MS = 5_000;
export const NOTICE_STATUS_API = "/api/system/getFirstLaunchNotice";
export const NOTICE_ACKNOWLEDGE_API = "/api/system/acknowledgeFirstLaunchNotice";

export interface NoticeRuntime {
    browser: boolean;
    mobileApp: boolean;
    container: string;
    publish: boolean;
}

interface NoticeAPIResponse {
    code: number;
    data?: {
        acknowledged?: boolean;
    };
}

export type NoticeRequest = (path: string) => Promise<NoticeAPIResponse>;

export const isFirstLaunchNoticeEligible = (runtime: NoticeRuntime) => {
    if (runtime.publish) {
        return false;
    }
    if (!runtime.browser) {
        return true;
    }
    return runtime.mobileApp && ["android", "ios"].includes(runtime.container);
};

export const getNoticeRemainingSeconds = (startedAt: number, now: number) => {
    const remaining = Math.ceil((NOTICE_DELAY_MS - (now - startedAt)) / 1_000);
    return Math.min(NOTICE_DELAY_MS / 1_000, Math.max(0, remaining));
};

export const hasAcknowledgedNotice = async (request: NoticeRequest) => {
    try {
        const response = await request(NOTICE_STATUS_API);
        return response.code === 0 && response.data?.acknowledged === true;
    } catch {
        return false;
    }
};

export const acknowledgeNotice = async (request: NoticeRequest) => {
    try {
        const response = await request(NOTICE_ACKNOWLEDGE_API);
        return response.code === 0;
    } catch {
        return false;
    }
};
