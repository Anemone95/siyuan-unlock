import * as assert from "node:assert/strict";
import test from "node:test";
import {
    NOTICE_ACKNOWLEDGE_API,
    NOTICE_DELAY_MS,
    NOTICE_STATUS_API,
    acknowledgeNotice,
    getNoticeRemainingSeconds,
    hasAcknowledgedNotice,
    isFirstLaunchNoticeEligible,
} from "./firstLaunchNoticeState";

test("limits the notice to packaged desktop, Android, and iOS clients", () => {
    assert.equal(isFirstLaunchNoticeEligible({browser: false, mobileApp: false, container: "desktop", publish: false}), true);
    assert.equal(isFirstLaunchNoticeEligible({browser: true, mobileApp: true, container: "android", publish: false}), true);
    assert.equal(isFirstLaunchNoticeEligible({browser: true, mobileApp: true, container: "ios", publish: false}), true);
    assert.equal(isFirstLaunchNoticeEligible({browser: true, mobileApp: false, container: "docker", publish: false}), false);
    assert.equal(isFirstLaunchNoticeEligible({browser: true, mobileApp: true, container: "harmony", publish: false}), false);
    assert.equal(isFirstLaunchNoticeEligible({browser: false, mobileApp: false, container: "desktop", publish: true}), false);
});

test("keeps acknowledgement disabled for five elapsed seconds", () => {
    assert.equal(NOTICE_DELAY_MS, 5_000);
    assert.equal(getNoticeRemainingSeconds(1_000, 1_000), 5);
    assert.equal(getNoticeRemainingSeconds(1_000, 5_999), 1);
    assert.equal(getNoticeRemainingSeconds(1_000, 6_000), 0);
    assert.equal(getNoticeRemainingSeconds(1_000, 7_000), 0);
});

test("reads acknowledgement from the installation-scoped API", async () => {
    const calls: string[] = [];
    const acknowledged = await hasAcknowledgedNotice(async (path) => {
        calls.push(path);
        return {code: 0, data: {acknowledged: true}};
    });

    assert.equal(acknowledged, true);
    assert.deepEqual(calls, [NOTICE_STATUS_API]);
});

test("writes acknowledgement through the installation-scoped API", async () => {
    const calls: string[] = [];
    const acknowledged = await acknowledgeNotice(async (path) => {
        calls.push(path);
        return {code: 0};
    });

    assert.equal(acknowledged, true);
    assert.deepEqual(calls, [NOTICE_ACKNOWLEDGE_API]);
});

test("treats API failures as unacknowledged", async () => {
    assert.equal(await hasAcknowledgedNotice(async () => ({code: 0, data: {acknowledged: false}})), false);
    assert.equal(await hasAcknowledgedNotice(async () => ({code: -1})), false);
    assert.equal(await hasAcknowledgedNotice(async () => {
        throw new Error("read failed");
    }), false);
    assert.equal(await acknowledgeNotice(async () => ({code: -1})), false);
    assert.equal(await acknowledgeNotice(async () => {
        throw new Error("write failed");
    }), false);
});
