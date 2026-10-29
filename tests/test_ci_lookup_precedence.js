'use strict';

const assert = require('assert');
const USBEM_Lookups = require('../src/USBEM_Lookups.js');

function core() {
    return {
        hasValue: value => value !== null && value !== undefined && String(value) !== '',
        looksLikeSysId: value => /^[0-9a-f]{32}$/i.test(String(value || '')),
        traceLookup: () => {},
        traceNote: () => {},
        isObject: value => value && typeof value === 'object' && !Array.isArray(value),
        shouldUseDummyCi: () => false
    };
}

function context() {
    return {
        mapped: { cmdb_ci: 'Decoy CI', ci_type: 'cmdb_ci_server', resource: '', node: '' },
        ci_identifier_obj: { serial_number: 'SERIAL-EXPECTED' },
        debug: {},
        attempts: { ci: false },
        resolved: {},
        user_additional_info: {}
    };
}

(function identifierWinsOverTextName() {
    const lookups = new USBEM_Lookups(core());
    const calls = [];
    lookups.resolveCiTypeTable = () => ({ table_name: 'cmdb_ci_server' });
    lookups.resolveRecordByIdentifier = () => {
        calls.push('identifier');
        return { match: { sys_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' }, count: 1, rows: [] };
    };
    lookups.resolveCmdbCiByName = () => {
        calls.push('name');
        return { match: { sys_id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' }, count: 1, rows: [] };
    };
    const ctx = context();
    const result = lookups.resolvePrimaryCmdbCi(ctx);
    assert.strictEqual(result.sys_id, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
    assert.deepStrictEqual(calls, ['identifier']);
    assert.strictEqual(ctx.mapped.cmdb_ci, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
})();

(function textNameIsFallbackWhenIdentifierMisses() {
    const lookups = new USBEM_Lookups(core());
    const calls = [];
    lookups.resolveCiTypeTable = () => ({ table_name: 'cmdb_ci_server' });
    lookups.resolveRecordByIdentifier = () => {
        calls.push('identifier');
        return { match: null, count: 0, rows: [] };
    };
    lookups.resolveCmdbCiByName = () => {
        calls.push('name');
        return { match: { sys_id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' }, count: 1, rows: [] };
    };
    const ctx = context();
    const result = lookups.resolvePrimaryCmdbCi(ctx);
    assert.strictEqual(result.sys_id, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
    assert.deepStrictEqual(calls, ['identifier', 'name']);
})();

console.log('CI lookup precedence tests passed');
