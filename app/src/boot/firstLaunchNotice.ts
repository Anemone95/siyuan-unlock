import {Dialog} from "../dialog";
import {isInMobileApp} from "../protyle/util/compatibility";
import {fetchSyncPost} from "../util/fetch";
import {isBrowser, isMobile} from "../util/functions";
import {
    acknowledgeNotice,
    getNoticeRemainingSeconds,
    hasAcknowledgedNotice,
    isFirstLaunchNoticeEligible,
} from "./firstLaunchNoticeState";

const RELEASE_URL = "https://github.com/Anemone95/siyuan-unlock/releases";

const requestNotice = (path: string) => fetchSyncPost(path, {}, undefined, false);

export const openFirstLaunchNotice = async () => {
    const eligible = isFirstLaunchNoticeEligible({
        browser: isBrowser(),
        mobileApp: Boolean(isInMobileApp()),
        container: window.siyuan.config.system.container,
        publish: window.siyuan.isPublish,
    });
    if (!eligible || await hasAcknowledgedNotice(requestNotice)) {
        return;
    }

    return new Promise<void>((resolve) => {
        const dialog = new Dialog({
            title: "重要声明",
            width: isMobile() ? "92vw" : "520px",
            disableClose: true,
            hideCloseIcon: true,
            content: `<div class="b3-dialog__content b3-typography">
    <p>本项目 <strong>SiYuan Unlock</strong> 为免费开源项目，官方始终免费提供，未授权任何个人或平台收费代售本项目、安装包、激活码或所谓售后服务。</p>
    <p>如果您通过付费渠道获得本软件，请立即向交易平台申请退款并举报相关卖家，谨防后续收费及安全风险。</p>
    <p>请仅从官方发布页面获取版本：<br><a href="${RELEASE_URL}" target="_blank" rel="noopener noreferrer">${RELEASE_URL}</a></p>
    <p>感谢支持开源，共同抵制倒卖。</p>
    <div class="ft__error fn__none" data-type="noticeError">无法保存确认状态，请重试。</div>
</div>
<div class="b3-dialog__action">
    <button class="b3-button b3-button--text" data-type="noticeAcknowledge" disabled>我已知晓（5）</button>
</div>`,
        });
        const destroy = dialog.destroy.bind(dialog);
        dialog.destroy = () => undefined;

        const button = dialog.element.querySelector<HTMLButtonElement>("[data-type='noticeAcknowledge']");
        const errorElement = dialog.element.querySelector<HTMLElement>("[data-type='noticeError']");
        const startedAt = Date.now();
        const updateButton = () => {
            const remaining = getNoticeRemainingSeconds(startedAt, Date.now());
            if (remaining > 0) {
                button.textContent = `我已知晓（${remaining}）`;
                return;
            }
            window.clearInterval(timer);
            button.textContent = "我已知晓";
            button.disabled = false;
        };
        const timer = window.setInterval(updateButton, 250);
        updateButton();

        button.addEventListener("click", async () => {
            if (button.disabled) {
                return;
            }
            button.disabled = true;
            if (!await acknowledgeNotice(requestNotice)) {
                errorElement.classList.remove("fn__none");
                button.disabled = false;
                return;
            }
            window.clearInterval(timer);
            destroy();
            resolve();
        });
    });
};
