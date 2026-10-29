'use strict';

const assert = require('assert');
const USBEM_Core = require('../src/USBEM_Core.js');
const USBEM_Lookups = require('../src/USBEM_Lookups.js');

let passed = 0;
function test(name, run) {
    run();
    passed++;
    console.log('PASS ' + name);
}

const EXPECTED_ID = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const DECOY_ID = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const EXPLICIT_ID = 'cccccccccccccccccccccccccccccccc';

function context(overrides) {
    return new USBEM_Core().createRecordContext(Object.assign({
        cmdb_ci: 'Decoy CI',
        ci_type: 'cmdb_ci_server',
        ci_identifier: { serial_number: 'SERIAL-EXPECTED' },
        message_key: 'local-ci-regression-test',
        usbem_debug: true
    }, overrides || {}));
}

function routingLookups(identifierResult) {
    const lookups = new USBEM_Lookups(new USBEM_Core());
    const calls = [];
    lookups.resolveCiTypeTable = () => ({ table_name: 'cmdb_ci_server' });
    lookups.resolveRecordByIdentifier = () => {
        calls.push('identifier');
        return identifierResult;
    };
    lookups.resolveCmdbCiByName = () => {
        calls.push('name');
        return { match: { sys_id: DECOY_ID }, count: 1, rows: [] };
    };
    return { lookups, calls };
}

test('identifier wins over a conflicting textual CI name', () => {
    const { lookups, calls } = routingLookups({ match: { sys_id: EXPECTED_ID }, count: 1, rows: [] });
    const ctx = context();
    const result = lookups.resolvePrimaryCmdbCi(ctx);
    assert.strictEqual(result.sys_id, EXPECTED_ID);
    assert.deepStrictEqual(calls, ['identifier']);
    assert.strictEqual(ctx.mapped.cmdb_ci, EXPECTED_ID);
    assert.strictEqual(ctx.resolved.cmdb_ci_sys_id, EXPECTED_ID);
});

test('text name remains a fallback after an identifier has no match', () => {
    const { lookups, calls } = routingLookups({ match: null, count: 0, rows: [] });
    const ctx = context();
    const result = lookups.resolvePrimaryCmdbCi(ctx);
    assert.strictEqual(result.sys_id, DECOY_ID);
    assert.deepStrictEqual(calls, ['identifier', 'name']);
});

test('a missing identifier uses the textual name without an identifier query', () => {
    const { lookups, calls } = routingLookups(null);
    const ctx = context({ ci_identifier: undefined });
    assert.strictEqual(lookups.resolvePrimaryCmdbCi(ctx).sys_id, DECOY_ID);
    assert.deepStrictEqual(calls, ['name']);
});

test('current policy falls back to a name after ambiguous identifiers', () => {
    // This documents existing fallback semantics, rather than claiming an ambiguous
    // identifier is safe or unique. Live production fixtures must identify one CI.
    const { lookups, calls } = routingLookups({
        match: null, count: 2, rows: [], ambiguous: true, selection_reason: 'top_score_tie'
    });
    const ctx = context();
    assert.strictEqual(lookups.resolvePrimaryCmdbCi(ctx).sys_id, DECOY_ID);
    assert.deepStrictEqual(calls, ['identifier', 'name']);
    assert.strictEqual(ctx.debug.lookups.ci_identifier.status, 'ambiguous');
});

// The fake implements only query/equality/INSTANCEOF and record reads. It exercises
// actual USBEM query construction and row selection; it does not prove ServiceNow
// ACLs, dictionary inheritance, INSTANCEOF execution, or asynchronous processing.
const CI_FIELDS = new Set([
    'sys_id', 'name', 'sys_class_name', 'serial_number', 'asset_tag',
    'operational_status', 'install_status', 'active'
]);
const ANCESTORS = {
    cmdb_ci_server: ['cmdb_ci_computer', 'cmdb_ci'],
    cmdb_ci_linux_server: ['cmdb_ci_server', 'cmdb_ci_computer', 'cmdb_ci'],
    cmdb_ci_vm_instance: ['cmdb_ci']
};

function withGlideRecord(rows, run) {
    const previous = global.GlideRecord;
    const records = [];
    global.GlideRecord = class {
        constructor(table) {
            this.table = table;
            this.conditions = [];
            this.queried = false;
            this.cursor = -1;
            this.matches = [];
            records.push(this);
        }
        isValidField(field) { return CI_FIELDS.has(field); }
        addQuery(field, operator, value) {
            if (arguments.length === 2) {
                value = operator;
                operator = '=';
            }
            this.conditions.push([field, operator, value]);
        }
        setLimit(limit) { this.limit = limit; }
        query() {
            this.queried = true;
            this.matches = rows.filter(row => this.conditions.every(([field, operator, value]) => {
                if (operator === 'INSTANCEOF') {
                    return row[field] === value || (ANCESTORS[row[field]] || []).includes(value);
                }
                assert.strictEqual(operator, '=', 'unexpected query operator');
                return String(row[field] || '') === String(value);
            })).slice(0, this.limit);
        }
        next() {
            this.current = this.matches[++this.cursor];
            return Boolean(this.current);
        }
        get(sysId) {
            this.current = rows.find(row => row.sys_id === sysId);
            return Boolean(this.current);
        }
        getUniqueValue() { return this.current.sys_id; }
        getValue(field) { return this.current[field] || ''; }
        getDisplayValue(field) { return this.current[field || 'name'] || ''; }
    };
    try {
        const core = new USBEM_Core();
        core.tableExists = table => table === 'cmdb_ci' || Object.hasOwnProperty.call(ANCESTORS, table);
        run(new USBEM_Lookups(core), records, core);
    } finally {
        if (previous === undefined) {
            delete global.GlideRecord;
        } else {
            global.GlideRecord = previous;
        }
    }
}

function ci(sysId, className, overrides) {
    return Object.assign({
        sys_id: sysId, name: 'CI ' + sysId[0], sys_class_name: className,
        serial_number: 'SERIAL-EXPECTED', asset_tag: 'ASSET-EXPECTED',
        operational_status: '', install_status: '', active: 'true'
    }, overrides || {});
}

test('actual identifier query uses the CMDB parent, class descendants, and ANDed keys', () => {
    withGlideRecord([
        ci(EXPECTED_ID, 'cmdb_ci_linux_server'),
        ci(DECOY_ID, 'cmdb_ci_vm_instance'), // Same identity, wrong class.
        ci(EXPLICIT_ID, 'cmdb_ci_server', { asset_tag: 'DIFFERENT-ASSET' })
    ], (lookups, records) => {
        const result = lookups.resolveRecordByIdentifier('cmdb_ci_server', {
            serial_number: ' SERIAL-EXPECTED ', asset_tag: 'ASSET-EXPECTED'
        });
        assert.strictEqual(result.match.sys_id, EXPECTED_ID);
        assert.strictEqual(result.count, 1);
        assert.strictEqual(records[0].table, 'cmdb_ci');
        assert.deepStrictEqual(records[0].conditions, [
            ['sys_class_name', 'INSTANCEOF', 'cmdb_ci_server'],
            ['serial_number', '=', 'SERIAL-EXPECTED'],
            ['asset_tag', '=', 'ASSET-EXPECTED']
        ]);
    });
});

test('a wrong-class identifier collision cannot match the requested class', () => {
    withGlideRecord([ci(DECOY_ID, 'cmdb_ci_vm_instance')], (lookups) => {
        const result = lookups.resolveRecordByIdentifier('cmdb_ci_server', { serial_number: 'SERIAL-EXPECTED' });
        assert.strictEqual(result.match, null);
        assert.strictEqual(result.count, 0);
    });
});

test('base cmdb_ci lookup does not add an unnecessary class filter', () => {
    withGlideRecord([ci(EXPECTED_ID, 'cmdb_ci_linux_server')], (lookups, records) => {
        const result = lookups.resolveRecordByIdentifier('cmdb_ci', { serial_number: 'SERIAL-EXPECTED' });
        assert.strictEqual(result.match.sys_id, EXPECTED_ID);
        assert.deepStrictEqual(records[0].conditions, [['serial_number', '=', 'SERIAL-EXPECTED']]);
    });
});

test('invalid or blank identifier keys never execute an unconstrained query', () => {
    withGlideRecord([ci(EXPECTED_ID, 'cmdb_ci_server')], (lookups, records) => {
        const inherited = { serial_number: 'SERIAL-EXPECTED' };
        const identifier = Object.assign(Object.create(inherited), { unknown_field: 'x', asset_tag: '   ' });
        const result = lookups.resolveRecordByIdentifier('cmdb_ci_server', identifier);
        assert.strictEqual(result.match, null);
        assert.strictEqual(result.selection_reason, 'no_valid_keys');
        assert.strictEqual(records.length, 1);
        assert.strictEqual(records[0].queried, false);
    });
});

test('non-object identifiers do not construct or execute a query', () => {
    withGlideRecord([], (lookups, records) => {
        for (const value of [null, 'not-json', [], 42]) {
            assert.strictEqual(lookups.resolveRecordByIdentifier('cmdb_ci_server', value).match, null);
        }
        assert.strictEqual(records.length, 0);
    });
});

test('current policy ignores invalid keys in a partly valid identifier', () => {
    // A child-only field may be invalid on the cmdb_ci parent. This asserts the
    // present behavior so that this limitation is visible instead of untested.
    withGlideRecord([ci(EXPECTED_ID, 'cmdb_ci_server')], (lookups, records) => {
        const result = lookups.resolveRecordByIdentifier('cmdb_ci_server', {
            serial_number: 'SERIAL-EXPECTED', child_only_field: 'does-not-match'
        });
        assert.strictEqual(result.match.sys_id, EXPECTED_ID);
        assert.deepStrictEqual(records[0].conditions, [
            ['sys_class_name', 'INSTANCEOF', 'cmdb_ci_server'],
            ['serial_number', '=', 'SERIAL-EXPECTED']
        ]);
    });
});

test('equally scored duplicate identifier matches are ambiguous', () => {
    withGlideRecord([
        ci(EXPECTED_ID, 'cmdb_ci_server'), ci(DECOY_ID, 'cmdb_ci_linux_server')
    ], (lookups) => {
        const result = lookups.resolveRecordByIdentifier('cmdb_ci_server', { serial_number: 'SERIAL-EXPECTED' });
        assert.strictEqual(result.match, null);
        assert.strictEqual(result.count, 2);
        assert.strictEqual(result.ambiguous, true);
        assert.strictEqual(result.selection_reason, 'top_score_tie');
    });
});

test('current policy ranks duplicate identifier matches with different status scores', () => {
    withGlideRecord([
        ci(EXPECTED_ID, 'cmdb_ci_server', { operational_status: 'Operational' }),
        ci(DECOY_ID, 'cmdb_ci_server', { operational_status: 'Down', active: 'false' })
    ], (lookups) => {
        const result = lookups.resolveRecordByIdentifier('cmdb_ci_server', { serial_number: 'SERIAL-EXPECTED' });
        assert.strictEqual(result.match.sys_id, EXPECTED_ID);
        assert.strictEqual(result.count, 2);
        assert.strictEqual(result.ambiguous, false);
    });
});

test('an existing explicit CI sys_id is authoritative over conflicting identifiers', () => {
    withGlideRecord([ci(EXPLICIT_ID, 'cmdb_ci_vm_instance')], (lookups, records) => {
        lookups.resolveCiTypeTable = () => ({ table_name: 'cmdb_ci_server' });
        lookups.resolveRecordByIdentifier = () => assert.fail('explicit sys_id must bypass identifiers');
        lookups.resolveCmdbCiByName = () => assert.fail('explicit sys_id must bypass name matching');
        const ctx = context({ cmdb_ci: EXPLICIT_ID });
        assert.strictEqual(lookups.resolvePrimaryCmdbCi(ctx).sys_id, EXPLICIT_ID);
        assert.strictEqual(ctx.resolved.cmdb_ci_sys_id, EXPLICIT_ID);
        assert.strictEqual(records.length, 1);
        assert.strictEqual(records[0].table, 'cmdb_ci');
    });
});

test('a nonexistent explicit sys_id falls through to valid identifiers', () => {
    withGlideRecord([], (lookups) => {
        lookups.resolveCiTypeTable = () => ({ table_name: 'cmdb_ci_server' });
        lookups.resolveRecordByIdentifier = () => ({ match: { sys_id: EXPECTED_ID }, count: 1, rows: [] });
        lookups.resolveCmdbCiByName = () => assert.fail('a sys_id must never become a text-name query');
        const ctx = context({ cmdb_ci: EXPLICIT_ID });
        assert.strictEqual(lookups.resolvePrimaryCmdbCi(ctx).sys_id, EXPECTED_ID);
    });
});

for (const typeAlias of ['ci_type', 'ciType']) {
    for (const identifierAlias of ['ci_identifier', 'ciIdentifier', 'ci_identifiers', 'ciIdentifiers']) {
        test('actual Core normalizes ' + typeAlias + ' + ' + identifierAlias, () => {
            const ctx = new USBEM_Core().createRecordContext({
                [typeAlias]: 'cmdb_ci_server',
                [identifierAlias]: { serial_number: 'SERIAL-EXPECTED' },
                cmdbCi: 'Decoy CI'
            });
            assert.strictEqual(ctx.mapped.ci_type, 'cmdb_ci_server');
            assert.strictEqual(ctx.mapped.cmdb_ci, 'Decoy CI');
            assert.deepStrictEqual(ctx.ci_identifier_obj, { serial_number: 'SERIAL-EXPECTED' });
            assert.deepStrictEqual(JSON.parse(ctx.mapped.ci_identifier), ctx.ci_identifier_obj);
        });
    }
}

for (const encodeAdditionalInfo of [value => value, JSON.stringify]) {
    test('actual Core promotes CI aliases from ' + (encodeAdditionalInfo === JSON.stringify ? 'JSON' : 'object') + ' additional_info', () => {
        const ctx = new USBEM_Core().createRecordContext({
            additional_info: encodeAdditionalInfo({
                ciType: 'cmdb_ci_server',
                ciIdentifiers: JSON.stringify({ serial_number: 'SERIAL-EXPECTED' }),
                cmdbCi: 'Decoy CI'
            })
        });
        assert.strictEqual(ctx.mapped.ci_type, 'cmdb_ci_server');
        assert.strictEqual(ctx.mapped.cmdb_ci, 'Decoy CI');
        assert.deepStrictEqual(ctx.ci_identifier_obj, { serial_number: 'SERIAL-EXPECTED' });
    });
}

test('actual Core gives per-event aliases precedence over batch-envelope defaults', () => {
    const ctx = new USBEM_Core().createRecordContext({
        ciType: 'cmdb_ci_linux_server', ciIdentifier: { serial_number: 'EVENT-SERIAL' }
    }, {
        ciType: 'cmdb_ci_server', ciIdentifier: { serial_number: 'ENVELOPE-SERIAL' }
    });
    assert.strictEqual(ctx.mapped.ci_type, 'cmdb_ci_linux_server');
    assert.deepStrictEqual(ctx.ci_identifier_obj, { serial_number: 'EVENT-SERIAL' });
});

test('actual Core rejects malformed JSON, arrays, and scalar identifiers', () => {
    const core = new USBEM_Core();
    for (const raw of ['{broken', '["serial"]', '42', ['serial'], 42, null]) {
        assert.strictEqual(core.createRecordContext({ ciIdentifier: raw }).ci_identifier_obj, null);
    }
});

console.log('CI lookup precedence tests passed: ' + passed + ' cases');
