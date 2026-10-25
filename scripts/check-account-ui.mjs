import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {resolve} from 'node:path';
import {runInNewContext} from 'node:vm';

// Exercise the real settings registration without mounting unrelated panels.
const source = process.argv[2];
assert.ok(source, 'Usage: node scripts/check-account-ui.mjs <prepared-source>');
const load = path => stripTypeScriptTypes(readFileSync(resolve(source, path), 'utf8'))
    .replace(/^import .*;$/gm, '').replace(/^export /gm, '');
const syncTab = load('app/src/config/tabs/syncTab.ts');
const groups = [];
const group = new Proxy({}, {get: () => () => {}});
const context = {
    window: {siyuan: {languages: {}, config: {system: {container: 'docker'}}}},
    getSyncProviderConfigKeywords: () => [],
    getSyncProviderConfigRowKeywords: () => [],
    mountSyncProvider() {},
    mountSyncAssetDownloadMode() {},
    mountLANSyncStatus() {},
    getLANSyncSearchAvailability() {},
    registerAccountGroup() { groups.push('account'); },
    tab: {group(id) { groups.push(id); return group; }},
};
runInNewContext(`${syncTab}\nregisterSyncTab(tab);`, context);
assert.deepEqual(groups, ['sync', 'repo'], 'Sync settings must contain no account/login group');
console.log('PASS: sync settings register only sync and local repository groups');

const element = () => ({innerHTML: '', hidden: false, classList: {toggle(name, force) { this.owner.hidden = force; }},
    querySelector: () => null, querySelectorAll: () => [], addEventListener() {}});
const panel = element();
const row = element();
row.classList.owner = row;
const syncContext = {
    window: {siyuan: {user: {userSiYuanOneTimePayStatus: 1}, languages: {_kernel: {214: 'LOGIN_REQUIRED'}},
        config: {sync: {provider: 2, s3: {}, webdav: {}}}}},
    getCloudURL: () => '',
    getHostCapabilities: () => ({importExport: false}),
    escapeHtmlTextAndAttr: value => String(value ?? ''),
    root: {querySelector: selector => ({'#syncProviderConfig': panel, '#syncProviderConfigRow': row})[selector] || null},
};
const renderSource = load('app/src/util/needSubscribe.ts') + '\n' + load('app/src/config/tabs/syncUi.ts');
for (const provider of [2, 3]) {
    syncContext.window.siyuan.config.sync.provider = provider;
    runInNewContext(`${renderSource}\nrenderProviderConfig(root);`, {...syncContext});
    assert.match(row.innerHTML, /data-action="configureSync"/, 'Third-party sync configuration must be editable');
    assert.equal(row.hidden, false);
    assert.doesNotMatch(panel.innerHTML, /LOGIN_REQUIRED/);
}
syncContext.window.siyuan.user = null;
runInNewContext(`${renderSource}\nrenderProviderConfig(root);`, {...syncContext});
assert.match(panel.innerHTML, /LOGIN_REQUIRED/, 'Control case must detect the reported missing-user regression');
assert.equal(row.hidden, true, 'Control case must hide third-party sync configuration');
console.log('PASS: S3/WebDAV configuration renders for local unlock state; missing-user control is blocked');
