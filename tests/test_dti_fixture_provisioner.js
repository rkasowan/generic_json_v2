#!/usr/bin/env node
'use strict';
// Offline execution of the actual embedded DEV installer; no PDI or credentials.
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const child = require('node:child_process');

const runnerFile = path.join(__dirname, 'test_ci_identifier_precedence.py');
const script = child.execFileSync('python3', ['-c',
  'import ast,sys; m=ast.parse(open(sys.argv[1],encoding="utf-8").read()); print(ast.literal_eval(next(n.value for n in m.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="DEV_FIXTURE_ADMIN_SCRIPT" for t in n.targets))))',
  runnerFile], {encoding: 'utf8'});
const TARGET = 'https://dev123456.service-now.com';
const NS = 'USBEM-DTI-FIXTURES-V1';
const MARKER = 'USBEM DTI fixture pack v1';
const PROP = 'x_usbna_usb_event.default_cmdb_ci_sys_id';
const OWNED = MARKER + ' | ' + NS;
const schema = [
  ['cmdb_ci_business_app', 'u_car_id', 'string', '', '100'],
  ['cmdb_ci', 'u_level_2_support_assignee_group', 'reference', 'sys_user_group', '32'],
  ['incident', 'u_usb_em_test_value', 'string', '', '255'],
  ['incident', 'u_netcool_ticket', 'boolean', '', ''],
  ['incident', 'u_generating_alert', 'reference', 'em_alert', '32'],
];
let count = 0;
function test(name, callback) {
  try { callback(); count++; }
  catch (error) { console.error('FAIL ' + name); throw error; }
}
function clone(value) { return JSON.parse(JSON.stringify(value)); }

function sandbox(options = {}) {
  const db = {}, writes = [], sourceIds = {}, calls = {simulate: [], commit: []};
  let counter = 0x100;
  function nextId() { return (++counter).toString(16).padStart(32, '0'); }
  function add(table, fields) {
    const row = {...fields, sys_id: fields.sys_id || nextId()};
    row.sys_mod_count ||= '0'; row.sys_updated_on ||= '2026-10-29 18:00:00';
    if (table.startsWith('cmdb_ci') || table === 'service_offering') row.sys_class_name ||= table;
    (db[table] ||= []).push(row);
    return row;
  }
  function all(table) {
    if (table === 'cmdb_ci') return Object.entries(db).filter(([name]) => name.startsWith('cmdb_ci') || name === 'service_offering').flatMap(([, rows]) => rows);
    return db[table] || [];
  }
  for (const [name, element, internal_type, reference, max_length] of schema) {
    add('sys_dictionary', {name, element, internal_type, reference, max_length, sys_scope: 'global'});
  }
  class GlideRecord {
    constructor(table) { this.table = table; this.conditions = []; this.current = null; this.found = []; this.index = 0; this.limit = Infinity; }
    addQuery(field, operator, expected) { if (expected === undefined) { expected = operator; operator = '='; } this.conditions.push([field, operator, String(expected)]); }
    setLimit(limit) { this.limit = limit; }
    query() {
      this.found = all(this.table).filter(row => this.conditions.every(([field, operator, expected]) => {
        const actual = String(row[field] ?? '');
        if (operator === '=') return actual === expected;
        if (operator === 'IN') return expected.split(',').includes(actual);
        throw new Error('unimplemented local query operator: ' + operator);
      })).slice(0, this.limit); this.index = 0;
    }
    next() { this.current = this.found[this.index++]; return !!this.current; }
    hasNext() { return this.index < this.found.length; }
    get(sysId) { this.current = all(this.table).find(row => row.sys_id === String(sysId)); return !!this.current; }
    getValue(field) {
      const stored = this.current?.[field] ?? '';
      if (options.platformBooleans && ['active', 'locked_out', 'web_service_access_only'].includes(field)) {
        return ['true', '1', true].includes(stored) ? '1' : '0';
      }
      return stored;
    }
    getUniqueValue() { return this.getValue('sys_id'); }
    getTableName() { return this.table; }
    initialize() { this.current = {}; }
    setValue(field, value) { this.current[field] = String(value); }
    isValidField(field) { return this.table !== 'svc_ci_assoc' || ['ci', 'service'].includes(field); }
    insert() {
      if (this.table === 'sys_user') this.current.name = [this.current.first_name, this.current.last_name].join(' ');
      const row = add(this.table, this.current); this.current = row;
      if (options.newRecordFieldDrift && this.table === 'sys_user_group') row.active = 'false';
      writes.push({method: 'insert', table: this.table, id: row.sys_id}); return row.sys_id;
    }
    update() {
      this.current.sys_mod_count = String(Number(this.current.sys_mod_count) + 1);
      this.current.sys_updated_on = '2026-10-29 18:00:' + this.current.sys_mod_count.padStart(2, '0');
      writes.push({method: 'update', table: this.table, id: this.current.sys_id}); return this.current.sys_id;
    }
    deleteRecord() {
      const rows = db[this.table] || [], index = rows.indexOf(this.current);
      if (index < 0) return false;
      writes.push({method: 'delete', table: this.table, id: this.current.sys_id}); rows.splice(index, 1); return true;
    }
  }
  const SNC = {IdentificationEngineScriptableApi: {
    identifyCI(...args) {
      calls.simulate.push(args); assert.equal(args.length, 1, 'Australia identifyCI takes one JSON string');
      const payload = JSON.parse(args[0]), item = payload.items[0];
      assert.equal(item.sys_object_source_info.source_name, 'ServiceNow');
      assert.equal(item.sys_object_source_info.source_native_key, NS + ':' + item.internal_id);
      if (options.simulationError) return JSON.stringify({items: [{errors: [{error: 'deliberate simulation failure'}]}]});
      if (options.simulationWarning) return JSON.stringify({items: [{warnings: ['deliberate warning']}]});
      if (options.simulationShape !== undefined) return JSON.stringify(options.simulationShape);
      return JSON.stringify({items: [{sysId: options.predictedId || sourceIds[item.internal_id] || '', operation: 'INSERT'}]});
    },
    createOrUpdateCI(...args) {
      calls.commit.push(args); assert.equal(args.length, 2); assert.equal(args[0], 'ServiceNow');
      const item = JSON.parse(args[1]).items[0];
      let row = all(item.className).find(record => record.sys_id === sourceIds[item.internal_id]);
      if (!row) { row = add(item.className, clone(item.values)); sourceIds[item.internal_id] = row.sys_id; }
      else Object.assign(row, clone(item.values));
      if (options.commitReadbackDrift) row.name = 'unexpected nonfixture name';
      writes.push({method: 'IRE', table: item.className, id: row.sys_id});
      return JSON.stringify({items: [{sysId: row.sys_id}]});
    }
  }};
  function execute(action = 'provision', config = {}) {
    const lines = [], cfg = {action, target: TARGET, confirmation: TARGET, namespace: NS,
      result_marker: 'OFFLINE_RESULT', property_name: PROP, ...config};
    const gs = {hasRole: role => role === 'admin' && options.admin !== false,
      getProperty: (name, fallback = '') => {
        if (name === 'instance_name') return options.instanceName || 'dev123456';
        if (name === PROP && Object.hasOwn(options, 'cacheOverride')) return options.cacheOverride;
        return (db.sys_properties || []).find(row => row.name === name)?.value ?? fallback;
      },
      flushProperties() {}, print: line => lines.push(line)};
    vm.runInNewContext(script, {cfg, gs, GlideRecord, SNC}, {timeout: 1000});
    assert.equal(lines.length, 1);
    return JSON.parse(lines[0].slice(cfg.result_marker.length, -cfg.result_marker.length));
  }
  return {db, add, writes, sourceIds, calls, execute};
}

test('non-admin and mismatched target make zero writes', () => {
  for (const options of [{admin: false}, {instanceName: 'prod'}]) {
    const s = sandbox(options); assert.equal(s.execute().ok, false); assert.equal(s.writes.length, 0);
  }
});

test('all existing dictionary definitions are checked before any write', () => {
  for (const field of ['internal_type', 'reference', 'max_length', 'sys_scope']) {
    const s = sandbox(); s.db.sys_dictionary[4][field] = 'incompatible';
    s.db.sys_dictionary.shift(); // Missing earlier field must not be created before later mismatch.
    assert.equal(s.execute().ok, false); assert.equal(s.writes.length, 0);
  }
});

test('duplicate dictionary rows fail without writes', () => {
  const s = sandbox(); s.add('sys_dictionary', {...s.db.sys_dictionary[0], sys_id: 'd'.repeat(32)});
  assert.equal(s.execute().ok, false); assert.equal(s.writes.length, 0);
});

test('missing schema creates only five allowlisted global u_ fields', () => {
  const s = sandbox(); s.db.sys_dictionary = [];
  const result = s.execute(); assert.equal(result.ok, true, result.error);
  assert.equal(s.db.sys_dictionary.length, schema.length);
  assert.deepEqual(s.db.sys_dictionary.map(row => [row.name, row.element, row.internal_type, row.reference || '', row.max_length || '']), schema);
  assert.ok(s.db.sys_dictionary.every(row => row.sys_scope === 'global' && row.element.startsWith('u_')));
});

test('foreign same-name group is never adopted or overwritten', () => {
  const s = sandbox(); const foreign = s.add('sys_user_group', {name: '[TEST] ' + NS + ' L2 Support', description: 'real group', active: 'true'});
  const before = clone(foreign); assert.equal(s.execute().ok, false);
  assert.deepEqual(foreign, before); assert.equal(s.writes.length, 0);
});

test('owned fixture drift is not silently overwritten', () => {
  const s = sandbox(); const row = s.add('sys_user_group', {name: '[TEST] ' + NS + ' L2 Support', description: OWNED, active: 'false'});
  assert.equal(s.execute().ok, false); assert.equal(row.active, 'false'); assert.equal(s.writes.length, 0);
});

test('new fixture requested fields must survive insert readback', () => {
  const s = sandbox({newRecordFieldDrift: true});
  const result = s.execute(); assert.equal(result.ok, false); assert.match(result.error, /readback/);
  assert.equal(s.calls.commit.length, 0);
});

test('duplicate fixture names are rejected instead of choosing an arbitrary row', () => {
  const s = sandbox();
  for (let index = 0; index < 2; index++) s.add('sys_user_group', {name: '[TEST] ' + NS + ' L2 Support', description: OWNED, active: 'true'});
  assert.equal(s.execute().ok, false); assert.equal(s.writes.length, 0);
});

test('IRE simulation failure or warning never commits a CI', () => {
  for (const options of [{simulationError: true}, {simulationWarning: true}]) {
    const s = sandbox(options); assert.equal(s.execute().ok, false);
    assert.equal(s.calls.simulate.length, 1); assert.equal(s.calls.commit.length, 0);
    assert.equal(s.writes.filter(write => write.method === 'IRE').length, 0);
  }
});

test('every IRE error section and invalid response shape prevents commit', () => {
  for (const simulationShape of [null, [], {}, {items: []}, {items: [{errorCount: 1}]},
    {items: [{}], relations: [{errors: ['failure']}]}, {items: [{maskedAttributes: ['name']}]},
    {items: [{}], additionalCommittedItems: [{warnings: ['failure']}]}, {hasError: true, items: [{}]}]) {
    const s = sandbox({simulationShape}); assert.equal(s.execute().ok, false); assert.equal(s.calls.commit.length, 0);
  }
});

test('IRE would-update of foreign CI is rejected before commit', () => {
  const predictedId = 'c'.repeat(32), s = sandbox({predictedId});
  const foreign = s.add('cmdb_ci_service', {sys_id: predictedId, name: 'real service', short_description: 'not fixture'}), before = clone(foreign);
  assert.equal(s.execute().ok, false); assert.equal(s.calls.commit.length, 0); assert.deepEqual(foreign, before);
});

test('committed CI must match owned names and expected values on readback', () => {
  const s = sandbox({commitReadbackDrift: true}); assert.equal(s.execute().ok, false);
  assert.equal(s.calls.commit.length, 1); assert.match(s.execute().error || '', /readback|foreign/i);
});

test('provision rerun reuses exactly the same record identities without duplicates', () => {
  const s = sandbox(), first = s.execute(); assert.equal(first.ok, true, first.error);
  const tableSizes = Object.fromEntries(Object.entries(s.db).map(([table, rows]) => [table, rows.length]));
  const initialWriteCount = s.writes.length, initialCommitCount = s.calls.commit.length;
  const second = s.execute(); assert.equal(second.ok, true, second.error);
  assert.deepEqual(second.result, first.result);
  assert.equal(s.writes.length, initialWriteCount, 'unchanged fixture rerun must be zero-write');
  assert.equal(s.calls.commit.length, initialCommitCount, 'unchanged CI should not be committed again');
  assert.deepEqual(Object.fromEntries(Object.entries(s.db).map(([table, rows]) => [table, rows.length])), tableSizes);
  assert.equal(s.db.sys_user_has_role?.length || 0, 0);
  assert.equal(s.writes.filter(write => write.table === 'sys_dictionary').length, 0);
});

test('platform boolean getValue 1/0 does not cause false fixture drift on rerun', () => {
  const s = sandbox({platformBooleans: true}), first = s.execute(); assert.equal(first.ok, true, first.error);
  const second = s.execute(); assert.equal(second.ok, true, second.error);
  assert.deepEqual(second.result, first.result);
});

test('fixture users cannot authenticate and acquire no roles or email destinations', () => {
  const s = sandbox(), result = s.execute(); assert.equal(result.ok, true, result.error);
  assert.equal(s.db.sys_user.length, 3);
  assert.ok(s.db.sys_user.every(row => row.locked_out === 'true' && row.web_service_access_only === 'true' && row.email === '' && row.source === OWNED));
  assert.equal(s.db.sys_user_has_role?.length || 0, 0);
});

function fixtureCi(s) { return s.add('cmdb_ci_server', {name: '[TEST] ' + NS + ' Default Server', short_description: OWNED}).sys_id; }

test('valid existing global default cannot be overwritten', () => {
  const s = sandbox(), fixture = fixtureCi(s), real = s.add('cmdb_ci_server', {name: 'real CI'});
  s.add('sys_properties', {name: PROP, value: real.sys_id, description: 'original'});
  const before = s.execute('property_snapshot').result;
  assert.equal(before.valid_ci, true);
  assert.equal(s.execute('property_set', {before, fixture_ci_id: fixture}).ok, false);
  assert.equal(s.writes.length, 0);
});

test('changed property baseline and foreign temporary CI prevent any property write', () => {
  for (const type of ['changed baseline', 'foreign CI']) {
    const s = sandbox(), fixture = type === 'foreign CI' ? s.add('cmdb_ci_server', {name: 'real server'}).sys_id : fixtureCi(s);
    const before = s.execute('property_snapshot').result;
    if (type === 'changed baseline') s.add('sys_properties', {name: PROP, value: '', description: 'concurrent original'});
    assert.equal(s.execute('property_set', {before, fixture_ci_id: fixture}).ok, false);
    assert.equal(s.writes.length, 0);
  }
});

test('duplicate default properties are not silently selected or changed', () => {
  const s = sandbox();
  s.add('sys_properties', {name: PROP, value: 'one'}); s.add('sys_properties', {name: PROP, value: 'two'});
  assert.equal(s.execute('property_snapshot').ok, false); assert.equal(s.writes.length, 0);
});

test('absent property lease is restored to absence by exact owned row', () => {
  const s = sandbox(), fixture = fixtureCi(s), before = s.execute('property_snapshot').result;
  const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true, set.error);
  const restored = s.execute('property_restore', {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id});
  assert.equal(restored.ok, true, restored.error); assert.equal(s.db.sys_properties.length, 0);
  assert.equal(s.writes.filter(write => write.method === 'delete').length, 1);
});

test('invalid or empty existing property restores original value and description', () => {
  for (const original of ['', 'not-a-valid-ci']) {
    const s = sandbox(), fixture = fixtureCi(s), property = s.add('sys_properties', {name: PROP, value: original, description: 'preserve original description'});
    const before = s.execute('property_snapshot').result;
    const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true, set.error);
    assert.equal(s.execute('property_restore', {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id}).ok, true);
    assert.equal(property.value, original); assert.equal(property.description, 'preserve original description');
    assert.equal(s.writes.filter(write => write.method === 'delete').length, 0);
  }
});

test('concurrent property value or identity change is not clobbered', () => {
  for (const change of ['value', 'sys_id']) {
    const s = sandbox(), fixture = fixtureCi(s), before = s.execute('property_snapshot').result;
    const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true);
    s.db.sys_properties[0][change] = change === 'value' ? 'concurrent operator choice' : 'f'.repeat(32);
    const snapshot = clone(s.db.sys_properties), writes = s.writes.length;
    const restored = s.execute('property_restore', {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id});
    assert.equal(restored.ok, false); assert.deepEqual(s.db.sys_properties, snapshot); assert.equal(s.writes.length, writes);
  }
});

test('prepared journal recovery rejects more than its single expected property update', () => {
  const s = sandbox(), fixture = fixtureCi(s);
  s.add('sys_properties', {name: PROP, value: '', description: 'original property'});
  const before = s.execute('property_snapshot').result;
  assert.equal(s.execute('property_set', {before, fixture_ci_id: fixture}).ok, true);
  s.db.sys_properties[0].sys_mod_count = String(Number(s.db.sys_properties[0].sys_mod_count) + 1);
  const snapshot = clone(s.db.sys_properties), writes = s.writes.length;
  const result = s.execute('property_restore', {before, fixture_ci_id: fixture});
  assert.equal(result.ok, false); assert.deepEqual(s.db.sys_properties, snapshot); assert.equal(s.writes.length, writes);
});

test('active journal recovery rejects same-value concurrent modification', () => {
  const s = sandbox(), fixture = fixtureCi(s), before = s.execute('property_snapshot').result;
  const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true);
  s.db.sys_properties[0].sys_mod_count = String(Number(s.db.sys_properties[0].sys_mod_count) + 1);
  const snapshot = clone(s.db.sys_properties), writes = s.writes.length;
  const result = s.execute('property_restore', {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id,
    lease_mod_count: set.result.mod_count, lease_updated_on: set.result.updated_on});
  assert.equal(result.ok, false); assert.deepEqual(s.db.sys_properties, snapshot); assert.equal(s.writes.length, writes);
});

test('originally absent property with changed ownership marker is not deleted', () => {
  const s = sandbox(), fixture = fixtureCi(s), before = s.execute('property_snapshot').result;
  const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true);
  s.db.sys_properties[0].description = 'concurrent ownership'; const writes = s.writes.length;
  assert.equal(s.execute('property_restore', {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id}).ok, false);
  assert.equal(s.writes.length, writes); assert.equal(s.db.sys_properties.length, 1);
});

test('already-restored original state is a zero-write recovery no-op', () => {
  const s = sandbox(), before = s.execute('property_snapshot').result;
  const result = s.execute('property_restore', {before, fixture_ci_id: 'a'.repeat(32)});
  assert.equal(result.ok, true, result.error); assert.equal(result.result.unchanged, true); assert.equal(s.writes.length, 0);
});

test('repeated recovery of an existing property is a zero-write no-op despite changed rowversion', () => {
  const s = sandbox(), fixture = fixtureCi(s);
  s.add('sys_properties', {name: PROP, value: '', description: 'original existing property'});
  const before = s.execute('property_snapshot').result;
  const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true, set.error);
  const active = {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id,
    lease_mod_count: set.result.mod_count, lease_updated_on: set.result.updated_on};
  assert.equal(s.execute('property_restore', active).ok, true);
  assert.notEqual(s.db.sys_properties[0].sys_mod_count, before.mod_count);
  const unchanged = clone(s.db.sys_properties), writes = s.writes.length;
  const repeated = s.execute('property_restore', active);
  assert.equal(repeated.ok, true, repeated.error); assert.equal(repeated.result.unchanged, true);
  assert.deepEqual(s.db.sys_properties, unchanged); assert.equal(s.writes.length, writes);
});

test('crash-after-restore stale prepared journal can be replayed without another update', () => {
  const s = sandbox(), fixture = fixtureCi(s);
  s.add('sys_properties', {name: PROP, value: 'original-invalid-ci', description: 'original existing property'});
  const before = s.execute('property_snapshot').result, prepared = {before, fixture_ci_id: fixture};
  assert.equal(s.execute('property_set', prepared).ok, true);
  assert.equal(s.execute('property_restore', prepared).ok, true);
  const unchanged = clone(s.db.sys_properties), writes = s.writes.length;
  const replay = s.execute('property_restore', prepared);
  assert.equal(replay.ok, true, replay.error); assert.equal(replay.result.unchanged, true);
  assert.deepEqual(s.db.sys_properties, unchanged); assert.equal(s.writes.length, writes);
});

test('already-restored database value with a wrong effective cache is not reported restored', () => {
  const options = {}, s = sandbox(options), fixture = fixtureCi(s);
  s.add('sys_properties', {name: PROP, value: '', description: 'original existing property'});
  const before = s.execute('property_snapshot').result;
  const set = s.execute('property_set', {before, fixture_ci_id: fixture}); assert.equal(set.ok, true);
  const active = {before, fixture_ci_id: fixture, lease_sys_id: set.result.sys_id,
    lease_mod_count: set.result.mod_count, lease_updated_on: set.result.updated_on};
  assert.equal(s.execute('property_restore', active).ok, true);
  options.cacheOverride = fixture;
  const unchanged = clone(s.db.sys_properties), writes = s.writes.length;
  const result = s.execute('property_restore', active);
  assert.equal(result.ok, false); assert.match(result.error, /effective value/);
  assert.deepEqual(s.db.sys_properties, unchanged); assert.equal(s.writes.length, writes);
});

test('unknown actions and arbitrary property names are rejected without writes', () => {
  for (const [action, config] of [['anything', {}], ['property_set', {property_name: 'glide.some.global.setting'}]]) {
    const s = sandbox(); assert.equal(s.execute(action, config).ok, false); assert.equal(s.writes.length, 0);
  }
});

console.log(count + ' DEV fixture installer contracts passed');
