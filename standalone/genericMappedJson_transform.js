
(function process(/*RESTAPIRequest*/ request, body) {
    var VERSION = '2026-03-18a';
    var DEFAULT_SOURCE = 'GenericJSON';
    var DEFAULT_DESCRIPTION = 'Generic JSON event';
    var DEFAULT_SEVERITY = '5';
    var ADDITIONAL_INFO_MAX = 4000;
    var MESSAGE_KEY_MAX = 1024;
    var WAIT_ALERT_TIMEOUT_MS = 15000;
    var WAIT_ALERT_POLL_MS = 500;
    var MAX_QUERY_ROWS = 50;

    /*
     * Easy-to-update static DTI severity -> impact / urgency map.
     * Notes:
     * - No P1s.
     * - 0 / 5 do not auto-create incidents, but still get impact/urgency values
     *   in additional_info for downstream flow logic.
     */
    var DTI_SEVERITY_CONFIG = {
        '0': { impact: '4', urgency: '4', allow_incident: false, label: 'Clear' },
        '1': { impact: '2', urgency: '2', allow_incident: true,  label: 'Critical' },
        '2': { impact: '2', urgency: '2', allow_incident: true,  label: 'Major' },
        '3': { impact: '3', urgency: '3', allow_incident: true,  label: 'Minor' },
        '4': { impact: '4', urgency: '4', allow_incident: true,  label: 'Warning' },
        '5': { impact: '4', urgency: '4', allow_incident: false, label: 'OK' }
    };

    var WRAPPER_KEYS = {
        event: true,
        payload: true,
        data: true,
        record: true,
        alert: true
    };

    var FIELD_ALIASES = {
        source: ['source'],
        event_class: ['event_class', 'eventClass', 'source_instance', 'sourceInstance'],
        node: ['node', 'host', 'host_name', 'hostName', 'hostname', 'fqdn', 'ip', 'ip_address', 'ipAddress', 'ipaddress', 'server', 'device'],
        resource: ['resource', 'component', 'instance', 'object', 'target'],
        metric_name: ['metric_name', 'metricName', 'metric'],
        type: ['type', 'event_type', 'eventType'],
        message_key: ['message_key', 'messageKey', 'correlation_id', 'correlationId', 'dedup_key', 'dedupKey', 'alert_key', 'alertKey'],
        ci_type: ['ci_type', 'ciType'],
        ci_identifier: ['ci_identifier', 'ciIdentifier', 'ci_identifiers', 'ciIdentifiers'],
        cmdb_ci: ['cmdb_ci', 'cmdbCi'],
        service: ['service'],
        service_offering: ['service_offering', 'serviceOffering'],
        severity: ['severity'],
        description: ['description', 'short_description', 'shortDescription', 'message', 'summary'],
        time_of_event: ['time_of_event', 'timeOfEvent', 'event_time', 'eventTime', 'timestamp'],
        resolution_state: ['resolution_state', 'resolutionState', 'event_state', 'eventState', 'status', 'state']
    };

    var SPECIAL_ALIASES = {
        assignment_group: ['assignment_group', 'assignmentGroup'],
        usbem_car_id: ['usbem_car_id', 'usbemCarId', 'CAR ID', 'car_id'],
        usbem_service: ['usbem_service', 'usbemService'],
        usbem_offering: ['usbem_offering', 'usbemOffering'],
        usbem_wait_for_alert: ['usbem_wait_for_alert', 'usbemWaitForAlert'],
        usbem_wait_seconds: ['usbem_wait_seconds', 'usbemWaitSeconds'],
        usbem_debug: ['usbem_debug', 'usbemDebug'],
        direct_to_incident: ['direct_to_incident', 'directToIncident'],
        dti_wait_for_incident: ['dti_wait_for_incident', 'dtiWaitForIncident'],
        dti_impact: ['dti_impact', 'dtiImpact'],
        dti_urgency: ['dti_urgency', 'dtiUrgency']
    };

    var TABLE_EXISTS_CACHE = {};

    function isObject(value) {
        return Object.prototype.toString.call(value) === '[object Object]';
    }

    function isArray(value) {
        return Object.prototype.toString.call(value) === '[object Array]';
    }

    function hasOwn(obj, key) {
        return !!obj && Object.prototype.hasOwnProperty.call(obj, key);
    }

    function hasValue(value) {
        return value !== null && typeof value !== 'undefined' && String(value).replace(/^\s+|\s+$/g, '') !== '';
    }

    function trimToString(value) {
        return String(value).replace(/^\s+|\s+$/g, '');
    }

    function lower(value) {
        return trimToString(value).toLowerCase();
    }

    function normalizeKey(value) {
        return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    }

    function canonicalUnderscore(value) {
        return String(value || '')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_+|_+$/g, '')
            .replace(/_+/g, '_');
    }

    function compactAlphaNum(value) {
        return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    }

    function tokenize(value) {
        var tokens = String(value || '').toLowerCase().match(/[a-z0-9]+/g);
        return tokens ? tokens : [];
    }

    function truncateString(value, maxLen) {
        var text;
        if (!hasValue(value)) {
            return '';
        }
        text = String(value);
        if (text.length <= maxLen) {
            return text;
        }
        return text.substring(0, maxLen);
    }

    function looksLikeSysId(value) {
        return /^[0-9a-fA-F]{32}$/.test(trimToString(value));
    }

    function parseBoolean(value, defaultValue) {
        var n;
        if (typeof value === 'boolean') {
            return value;
        }
        if (!hasValue(value)) {
            return defaultValue === true;
        }
        n = normalizeKey(value);
        if (n === 'true' || n === '1' || n === 'yes' || n === 'y' || n === 'on') {
            return true;
        }
        if (n === 'false' || n === '0' || n === 'no' || n === 'n' || n === 'off') {
            return false;
        }
        return defaultValue === true;
    }

    function toInt(value, defaultValue) {
        var n = parseInt(value, 10);
        if (isNaN(n)) {
            return defaultValue;
        }
        return n;
    }

    function tryParseJSON(text) {
        if (typeof text !== 'string') {
            return null;
        }
        try {
            return JSON.parse(text);
        } catch (e) {
            return null;
        }
    }

    function deepClone(value) {
        var out;
        var i;
        var key;
        if (isArray(value)) {
            out = [];
            for (i = 0; i < value.length; i++) {
                out.push(deepClone(value[i]));
            }
            return out;
        }
        if (isObject(value)) {
            out = {};
            for (key in value) {
                if (hasOwn(value, key)) {
                    out[key] = deepClone(value[key]);
                }
            }
            return out;
        }
        return value;
    }

    function isEmptyObject(value) {
        var key;
        if (!isObject(value)) {
            return false;
        }
        for (key in value) {
            if (hasOwn(value, key)) {
                return false;
            }
        }
        return true;
    }

    function normalizeAdditionalInfoValue(value) {
        var out;
        var i;
        var key;

        if (value === null || typeof value === 'undefined') {
            return '';
        }
        if (isArray(value)) {
            out = [];
            for (i = 0; i < value.length; i++) {
                out.push(normalizeAdditionalInfoValue(value[i]));
            }
            return out;
        }
        if (isObject(value)) {
            out = {};
            for (key in value) {
                if (hasOwn(value, key)) {
                    out[key] = normalizeAdditionalInfoValue(value[key]);
                }
            }
            return out;
        }
        return String(value);
    }

    function mergeDeep(target, source) {
        var key;
        if (!isObject(source)) {
            return target;
        }
        if (!isObject(target)) {
            target = {};
        }
        for (key in source) {
            if (!hasOwn(source, key)) {
                continue;
            }
            if (isObject(target[key]) && isObject(source[key])) {
                mergeDeep(target[key], source[key]);
            } else {
                target[key] = normalizeAdditionalInfoValue(source[key]);
            }
        }
        return target;
    }

    function deleteAtPath(obj, path) {
        var current = obj;
        var i;
        var stack = [];

        if (!isObject(obj) || !isArray(path) || path.length === 0) {
            return;
        }

        for (i = 0; i < path.length - 1; i++) {
            if (!isObject(current[path[i]])) {
                return;
            }
            stack.push({ parent: current, key: path[i] });
            current = current[path[i]];
        }

        delete current[path[path.length - 1]];

        for (i = stack.length - 1; i >= 0; i--) {
            if (isObject(stack[i].parent[stack[i].key]) && isEmptyObject(stack[i].parent[stack[i].key])) {
                delete stack[i].parent[stack[i].key];
            }
        }
    }

    function extractFirstMatching(container, aliases) {
        var i;
        var j;
        var alias;
        var wrapper;

        if (!isObject(container)) {
            return null;
        }

        for (i = 0; i < aliases.length; i++) {
            alias = aliases[i];
            if (hasOwn(container, alias)) {
                return { value: container[alias], path: [alias], alias: alias };
            }
        }

        for (wrapper in WRAPPER_KEYS) {
            if (!hasOwn(WRAPPER_KEYS, wrapper)) {
                continue;
            }
            if (!isObject(container[wrapper])) {
                continue;
            }
            for (j = 0; j < aliases.length; j++) {
                alias = aliases[j];
                if (hasOwn(container[wrapper], alias)) {
                    return { value: container[wrapper][alias], path: [wrapper, alias], alias: alias };
                }
            }
        }

        return null;
    }

    function mergeAdditionalInfo(additionalInfo, rawAdditionalInfo) {
        var parsed;
        if (rawAdditionalInfo === null || typeof rawAdditionalInfo === 'undefined') {
            return;
        }

        if (typeof rawAdditionalInfo === 'string') {
            parsed = tryParseJSON(rawAdditionalInfo);
            if (parsed !== null) {
                rawAdditionalInfo = parsed;
            } else {
                additionalInfo.additional_info_text = rawAdditionalInfo;
                return;
            }
        }

        if (isObject(rawAdditionalInfo)) {
            mergeDeep(additionalInfo, rawAdditionalInfo);
            return;
        }

        if (isArray(rawAdditionalInfo)) {
            additionalInfo.additional_info_array = JSON.stringify(rawAdditionalInfo);
            return;
        }

        additionalInfo.additional_info_text = String(rawAdditionalInfo);
    }

    function maybePromoteField(container, aliases, targetObj, targetKey) {
        var match;
        if (hasValue(targetObj[targetKey])) {
            return;
        }
        match = extractFirstMatching(container, aliases);
        if (match) {
            targetObj[targetKey] = match.value;
            deleteAtPath(container, match.path);
        }
    }

    function normalizeResolutionState(raw) {
        var n;
        if (!hasValue(raw)) {
            return '';
        }
        n = normalizeKey(raw);
        if (n === 'closing' || n === 'close' || n === 'closed' || n === 'resolved' || n === 'clear' || n === 'cleared') {
            return 'Closing';
        }
        if (n === 'new' || n === 'open' || n === 'active' || n === 'fired' || n === 'ok' || n === 'warning' || n === 'minor' || n === 'major' || n === 'critical') {
            return 'New';
        }
        return '';
    }

    function normalizeTime(raw) {
        var s;
        var gdt;
        if (!hasValue(raw)) {
            return '';
        }
        s = trimToString(raw);
        if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(s)) {
            return s;
        }
        try {
            gdt = new GlideDateTime(s);
            return gdt.getValue();
        } catch (e) {
            return s;
        }
    }

    function mapSeverity(raw, additionalInfo) {
        var n;
        if (!hasValue(raw)) {
            return '';
        }
        raw = trimToString(raw);

        if (/^[0-5]$/.test(raw)) {
            return raw;
        }

        n = normalizeKey(raw);
        additionalInfo.original_severity = raw;

        if (n === 'clear' || n === 'cleared' || n === 'close' || n === 'closed' || n === 'resolved') {
            return '0';
        }
        if (n === 'critical' || n === 'crit') {
            return '1';
        }
        if (n === 'major') {
            return '2';
        }
        if (n === 'minor') {
            return '3';
        }
        if (n === 'warning' || n === 'warn') {
            return '4';
        }
        if (n === 'ok' || n === 'okay' || n === 'info' || n === 'informational' || n === 'information') {
            return '5';
        }

        additionalInfo.unmapped_severity = raw;
        return '';
    }

    function normalizeMessageKey(raw, mapped) {
        var assembled;
        if (hasValue(raw)) {
            return truncateString(String(raw), MESSAGE_KEY_MAX);
        }
        assembled = ''
            + (hasValue(mapped.source) ? mapped.source : '')
            + (hasValue(mapped.node) ? mapped.node : '')
            + (hasValue(mapped.type) ? mapped.type : '')
            + (hasValue(mapped.resource) ? mapped.resource : '')
            + (hasValue(mapped.metric_name) ? mapped.metric_name : '');
        if (!hasValue(assembled)) {
            assembled = ''
                + (hasValue(mapped.source) ? mapped.source : '')
                + (hasValue(mapped.event_class) ? mapped.event_class : '')
                + (hasValue(mapped.description) ? mapped.description : '');
        }
        return truncateString(assembled, MESSAGE_KEY_MAX);
    }

    
function priorityForAdditionalInfoKey(key) {
        if (key === 'direct_to_incident') {
            return 0;
        }
        if (key === 'dti_wait_for_incident') {
            return 1;
        }
        if (key === 'assignment_group' || key === 'cmdb_ci' || key === 'cmdb_ci_business_app' || key === 'cmdb_ci_service' || key === 'cmdb_ci_service_offering') {
            return 2;
        }
        if (key === 'dti_impact' || key === 'dti_urgency') {
            return 3;
        }
        if (/^(assignment_group|cmdb_ci)/.test(String(key))) {
            return 4;
        }
        if (String(key).indexOf('dti_') === 0) {
            return 5;
        }
        return 6;
    }

    function buildAdditionalInfoString(additionalInfo) {
        var full = JSON.stringify(additionalInfo);
        var reduced = {
            __truncated: 'true',
            __original_length: String(full.length)
        };
        var keys = [];
        var i;
        var key;

        if (full.length <= ADDITIONAL_INFO_MAX) {
            return full;
        }

        for (key in additionalInfo) {
            if (hasOwn(additionalInfo, key)) {
                keys.push(key);
            }
        }

        keys.sort(function (a, b) {
            var pa = priorityForAdditionalInfoKey(a);
            var pb = priorityForAdditionalInfoKey(b);
            if (pa !== pb) {
                return pa - pb;
            }
            if (a < b) {
                return -1;
            }
            if (a > b) {
                return 1;
            }
            return 0;
        });

        for (i = 0; i < keys.length; i++) {
            reduced[keys[i]] = additionalInfo[keys[i]];
            if (JSON.stringify(reduced).length > ADDITIONAL_INFO_MAX) {
                delete reduced[keys[i]];
            }
        }

        return JSON.stringify(reduced);
    }

    
function debugPush(enabled, steps, message) {
        if (!enabled) {
            return;
        }
        steps.push(String(message));
    }

    function getStatusReasonList(gr) {
        var reasons = [];
        var operational;
        var install;
        var lifecycle;

        if (!gr || !gr.isValidField) {
            return reasons;
        }

        if (gr.isValidField('operational_status')) {
            operational = normalizeKey(getFieldText(gr, 'operational_status'));
            if (operational.indexOf('operational') > -1 || operational.indexOf('up') > -1 || operational.indexOf('active') > -1) {
                reasons.push('operational');
            }
            if (operational.indexOf('nonoperational') > -1 || operational.indexOf('down') > -1 || operational.indexOf('retired') > -1) {
                reasons.push('non_operational');
            }
        }

        if (gr.isValidField('install_status')) {
            install = normalizeKey(getFieldText(gr, 'install_status'));
            if (install.indexOf('inproduction') > -1 || install.indexOf('production') > -1) {
                reasons.push('in_production');
            }
            if (install.indexOf('installed') > -1 || install.indexOf('inuse') > -1 || install.indexOf('live') > -1) {
                reasons.push('installed_or_live');
            }
            if (install.indexOf('retired') > -1 || install.indexOf('absent') > -1) {
                reasons.push('retired_or_absent');
            }
        }

        if (gr.isValidField('life_cycle_stage_status')) {
            lifecycle = normalizeKey(getFieldText(gr, 'life_cycle_stage_status'));
            if (lifecycle.indexOf('production') > -1) {
                reasons.push('life_cycle_production');
            }
        }

        if (gr.isValidField('active') && String(gr.getValue('active')) === 'true') {
            reasons.push('active');
        }

        return reasons;
    }

    function toDebugCandidates(rows, maxCount) {
        var out = [];
        var i;
        var limit;
        if (!isArray(rows) || rows.length === 0) {
            return out;
        }
        limit = Math.min(rows.length, maxCount || 5);
        for (i = 0; i < limit; i++) {
            out.push(normalizeAdditionalInfoValue(rows[i]));
        }
        return out;
    }

    function applyLookupDebug(additionalInfo, prefix, inputValue, resolution, debugEnabled) {
        if (!debugEnabled || !isObject(additionalInfo) || !hasValue(prefix) || !resolution) {
            return;
        }

        if (typeof inputValue !== 'undefined' && inputValue !== null && inputValue !== '') {
            additionalInfo[prefix + '_input'] = normalizeAdditionalInfoValue(inputValue);
        }

        if (hasValue(resolution.status)) {
            additionalInfo[prefix + '_lookup_status'] = String(resolution.status);
        }
        if (hasValue(resolution.method)) {
            additionalInfo[prefix + '_lookup_method'] = String(resolution.method);
        }
        if (hasValue(resolution.lookup_table)) {
            additionalInfo[prefix + '_lookup_table'] = String(resolution.lookup_table);
        }
        if (typeof resolution.count !== 'undefined') {
            additionalInfo[prefix + '_candidate_count'] = String(resolution.count);
        }
        if (hasValue(resolution.selection_reason)) {
            additionalInfo[prefix + '_selection_reason'] = String(resolution.selection_reason);
        }
        if (resolution.match && typeof resolution.match.score !== 'undefined') {
            additionalInfo[prefix + '_score'] = String(resolution.match.score);
        }
        if (isArray(resolution.rows) && resolution.rows.length > 0) {
            additionalInfo[prefix + '_candidates'] = toDebugCandidates(resolution.rows, 5);
        }
    }

    function tableExists(tableName) {
        var gr;
        if (!hasValue(tableName)) {
            return false;
        }
        if (typeof TABLE_EXISTS_CACHE[tableName] !== 'undefined') {
            return TABLE_EXISTS_CACHE[tableName];
        }
        try {
            gr = new GlideRecord(tableName);
            TABLE_EXISTS_CACHE[tableName] = !!(gr && gr.isValid && gr.isValid());
        } catch (e) {
            TABLE_EXISTS_CACHE[tableName] = false;
        }
        return TABLE_EXISTS_CACHE[tableName];
    }

    function setIfPresent(gr, fieldName, value) {
        if (hasValue(value) && gr.isValidField(fieldName)) {
            gr.setValue(fieldName, value);
        }
    }

    function getFieldText(gr, fieldName) {
        if (!gr || !gr.isValidField || !gr.isValidField(fieldName)) {
            return '';
        }
        return gr.getDisplayValue(fieldName) || gr.getValue(fieldName) || '';
    }

    function getActiveBonus(gr) {
        if (!gr || !gr.isValidField || !gr.isValidField('active')) {
            return 0;
        }
        return String(gr.getValue('active')) === 'true' ? 3 : 0;
    }

    function getStatusScore(gr) {
        var score = 0;
        var operational;
        var install;
        var lifecycle;

        if (!gr || !gr.isValidField) {
            return score;
        }

        if (gr.isValidField('operational_status')) {
            operational = normalizeKey(getFieldText(gr, 'operational_status'));
            if (operational.indexOf('operational') > -1 || operational.indexOf('up') > -1 || operational.indexOf('active') > -1) {
                score += 20;
            }
            if (operational.indexOf('nonoperational') > -1 || operational.indexOf('down') > -1 || operational.indexOf('retired') > -1) {
                score -= 10;
            }
        }

        if (gr.isValidField('install_status')) {
            install = normalizeKey(getFieldText(gr, 'install_status'));
            if (install.indexOf('inproduction') > -1 || install.indexOf('production') > -1 || install.indexOf('installed') > -1 || install.indexOf('inuse') > -1) {
                score += 10;
            }
            if (install.indexOf('retired') > -1 || install.indexOf('absent') > -1) {
                score -= 5;
            }
        }

        if (gr.isValidField('life_cycle_stage_status')) {
            lifecycle = normalizeKey(getFieldText(gr, 'life_cycle_stage_status'));
            if (lifecycle.indexOf('production') > -1) {
                score += 5;
            }
        }

        score += getActiveBonus(gr);
        return score;
    }

    function getCmdbCiClassPreference(sysClassName) {
        var normalized = canonicalUnderscore(sysClassName);

        if (!hasValue(normalized)) {
            return { score: 0, reasons: [] };
        }

        if (normalized === 'cmdb_ci_business_app') {
            return { score: 500, reasons: ['class_business_app'] };
        }

        if (normalized === 'cmdb_ci_service' || normalized.indexOf('cmdb_ci_service_') === 0) {
            return { score: 400, reasons: ['class_service'] };
        }

        if (normalized === 'service_offering' || normalized.indexOf('service_offering_') === 0 || normalized.indexOf('cmdb_ci_service_offering') === 0) {
            return { score: 300, reasons: ['class_service_offering'] };
        }

        if (normalized === 'cmdb_ci_server' || normalized.indexOf('_server') > -1) {
            return { score: 260, reasons: ['class_server'] };
        }

        if (normalized.indexOf('vmware_instance') > -1 || normalized.indexOf('vm_instance') > -1 || normalized.indexOf('virtual_machine') > -1 || normalized.indexOf('virtual_server') > -1) {
            return { score: 120, reasons: ['class_virtual_instance'] };
        }

        return { score: 0, reasons: [] };
    }

    function getCmdbCiLookupExtraScore(ciGr, row, canonicalTarget, compactTarget) {
        var candidateName = row && hasValue(row.name) ? row.name : getFieldText(ciGr, 'name');
        var extra = getCmdbCiClassPreference(row && row.sys_class_name ? row.sys_class_name : (ciGr.isValidField('sys_class_name') ? ciGr.getValue('sys_class_name') : ''));

        if (!isObject(extra)) {
            extra = { score: 0, reasons: [] };
        }
        if (!isArray(extra.reasons)) {
            extra.reasons = [];
        }

        if (hasValue(canonicalTarget) && canonicalUnderscore(candidateName) === canonicalTarget) {
            extra.score += 100;
            extra.reasons.push('canonical_name');
        }
        if (hasValue(compactTarget) && compactAlphaNum(candidateName) === compactTarget) {
            extra.score += 100;
            extra.reasons.push('compact_name');
        }

        return extra;
    }

    
function collectMatches(gr, nameField, extraScoreFn) {
        var rows = [];
        var row;
        var extra;
        var statusReasons;

        while (gr.next()) {
            statusReasons = getStatusReasonList(gr);
            row = {
                sys_id: gr.getUniqueValue(),
                name: gr.isValidField(nameField || 'name') ? gr.getDisplayValue(nameField || 'name') : gr.getDisplayValue(),
                number: gr.isValidField('number') ? gr.getDisplayValue('number') : '',
                u_car_id: gr.isValidField('u_car_id') ? gr.getDisplayValue('u_car_id') : '',
                sys_class_name: gr.isValidField('sys_class_name') ? gr.getValue('sys_class_name') : '',
                operational_status: gr.isValidField('operational_status') ? gr.getDisplayValue('operational_status') : '',
                install_status: gr.isValidField('install_status') ? gr.getDisplayValue('install_status') : '',
                life_cycle_stage_status: gr.isValidField('life_cycle_stage_status') ? gr.getDisplayValue('life_cycle_stage_status') : '',
                active: gr.isValidField('active') ? gr.getValue('active') : '',
                score: getStatusScore(gr),
                score_reasons: statusReasons,
                display: gr.getDisplayValue()
            };
            if (typeof extraScoreFn === 'function') {
                extra = extraScoreFn(gr, row);
                if (typeof extra === 'number') {
                    row.score += extra;
                } else if (isObject(extra)) {
                    if (typeof extra.score !== 'undefined') {
                        row.score += toInt(extra.score, 0);
                    }
                    if (isArray(extra.reasons)) {
                        row.score_reasons = row.score_reasons.concat(extra.reasons);
                    }
                }
            }
            rows.push(row);
        }
        return rows;
    }

    function sortMatches(rows) {
        rows.sort(function (a, b) {
            if (a.score !== b.score) {
                return b.score - a.score;
            }
            if (String(a.active) !== String(b.active)) {
                return String(a.active) === 'true' ? -1 : 1;
            }
            if (a.name < b.name) {
                return -1;
            }
            if (a.name > b.name) {
                return 1;
            }
            return 0;
        });
    }

    
function chooseBestMatch(rows, requireUniqueTopScore) {
        var out = {
            match: null,
            count: rows ? rows.length : 0,
            ambiguous: false,
            rows: rows || [],
            selection_reason: ''
        };
        if (!rows || rows.length === 0) {
            out.selection_reason = 'no_match';
            return out;
        }
        sortMatches(rows);
        out.rows = rows;
        if (rows.length === 1) {
            out.match = rows[0];
            out.selection_reason = 'unique_match';
            return out;
        }
        if (requireUniqueTopScore && rows[0].score === rows[1].score) {
            out.ambiguous = true;
            out.selection_reason = 'top_score_tie';
            return out;
        }
        out.match = rows[0];
        if (rows[0].score > rows[1].score) {
            out.selection_reason = 'highest_score';
        } else {
            out.selection_reason = 'first_after_sort';
        }
        return out;
    }

    function queryExactByName(tableName, fieldName, value, extraSetup, extraScoreFn, requireUniqueTopScore) {
        var gr;
        var rows;
        if (!tableExists(tableName) || !hasValue(value)) {
            return { match: null, count: 0, ambiguous: false };
        }
        gr = new GlideRecord(tableName);
        if (!gr.isValidField(fieldName)) {
            return { match: null, count: 0, ambiguous: false };
        }
        gr.addQuery(fieldName, trimToString(value));
        if (typeof extraSetup === 'function') {
            extraSetup(gr);
        }
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();
        rows = collectMatches(gr, fieldName, extraScoreFn);
        return chooseBestMatch(rows, requireUniqueTopScore === true);
    }


function buildCiTypeRow(gr, score, reasons) {
    var tableName = gr.isValidField('name') ? gr.getValue('name') : '';
    var label = gr.isValidField('label') ? getFieldText(gr, 'label') : '';
    return {
        sys_id: gr.getUniqueValue(),
        name: tableName,
        label: label,
        table_name: tableName,
        display: label || tableName,
        score: score || 0,
        score_reasons: reasons || [],
        active: ''
    };
}

function resolveCiTypeTable(rawValue, debugEnabled, debugSteps) {
    var input = trimToString(rawValue);
    var gr;
    var row;
    var rows;
    var chosen;
    var label = '';
    var name = '';
    var tokens;
    var compactTarget;
    var canonicalTarget;
    var combined;
    var score;
    var reasons;
    var i;
    var allTokensPresent;
    var resolution = {
        table_name: '',
        label: '',
        status: 'not_attempted',
        method: '',
        count: 0,
        rows: [],
        selection_reason: ''
    };

    if (!hasValue(input)) {
        resolution.status = 'empty';
        resolution.method = 'empty';
        return resolution;
    }

    if (looksLikeSysId(input) && tableExists('sys_db_object')) {
        gr = new GlideRecord('sys_db_object');
        if (gr.get(input)) {
            name = gr.isValidField('name') ? gr.getValue('name') : '';
            label = gr.isValidField('label') ? getFieldText(gr, 'label') : '';
            if (hasValue(name) && tableExists(name)) {
                row = buildCiTypeRow(gr, 999, ['provided_sys_db_object_sys_id']);
                resolution.table_name = name;
                resolution.label = label;
                resolution.status = 'matched';
                resolution.method = 'sys_db_object_sys_id';
                resolution.count = 1;
                resolution.rows = [row];
                resolution.match = row;
                resolution.lookup_table = name;
                resolution.selection_reason = 'provided_sys_db_object_sys_id';
                debugPush(debugEnabled, debugSteps, 'ci_type sys_db_object sys_id resolved: ' + input + ' -> ' + name);
                return resolution;
            }
        }
    }

    if (tableExists(input)) {
        resolution.table_name = input;
        resolution.status = 'matched';
        resolution.method = 'provided_table_name';
        resolution.count = 1;
        resolution.lookup_table = input;
        resolution.selection_reason = 'provided_table_name';

        if (tableExists('sys_db_object')) {
            gr = new GlideRecord('sys_db_object');
            if (gr.isValidField('name')) {
                gr.addQuery('name', input);
                gr.setLimit(1);
                gr.query();
                if (gr.next()) {
                    label = gr.isValidField('label') ? getFieldText(gr, 'label') : '';
                    row = buildCiTypeRow(gr, 999, ['provided_table_name']);
                    resolution.label = label;
                    resolution.rows = [row];
                    resolution.match = row;
                }
            }
        }

        if (!resolution.match) {
            resolution.match = {
                sys_id: '',
                name: input,
                label: '',
                table_name: input,
                display: input,
                score: 999,
                score_reasons: ['provided_table_name'],
                active: ''
            };
            resolution.rows = [resolution.match];
        }

        debugPush(debugEnabled, debugSteps, 'ci_type table name accepted: ' + input);
        return resolution;
    }

    if (!tableExists('sys_db_object')) {
        resolution.status = 'lookup_unavailable';
        resolution.method = 'sys_db_object_missing';
        resolution.selection_reason = 'sys_db_object_missing';
        return resolution;
    }

    gr = new GlideRecord('sys_db_object');
    if (gr.isValidField('label')) {
        gr.addQuery('label', input);
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();
        rows = [];
        while (gr.next()) {
            name = gr.isValidField('name') ? gr.getValue('name') : '';
            if (!hasValue(name) || !tableExists(name)) {
                continue;
            }
            rows.push(buildCiTypeRow(gr, 300, ['exact_label']));
        }
        chosen = chooseBestMatch(rows, true);
        if (chosen.match) {
            resolution.table_name = chosen.match.table_name;
            resolution.label = chosen.match.label || '';
            resolution.status = 'matched';
            resolution.method = 'exact_label';
            resolution.count = chosen.count;
            resolution.rows = chosen.rows;
            resolution.match = chosen.match;
            resolution.lookup_table = chosen.match.table_name;
            resolution.selection_reason = chosen.selection_reason || 'exact_label';
            debugPush(debugEnabled, debugSteps, 'ci_type label resolved: ' + input + ' -> ' + chosen.match.table_name);
            return resolution;
        }
        if (chosen.ambiguous) {
            resolution.table_name = '';
            resolution.status = 'ambiguous';
            resolution.method = 'exact_label';
            resolution.count = chosen.count;
            resolution.rows = chosen.rows;
            resolution.selection_reason = chosen.selection_reason || 'top_score_tie';
            return resolution;
        }
    }

    gr = new GlideRecord('sys_db_object');
    if (gr.isValidField('name')) {
        gr.addQuery('name', input);
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();
        rows = [];
        while (gr.next()) {
            name = gr.isValidField('name') ? gr.getValue('name') : '';
            if (!hasValue(name) || !tableExists(name)) {
                continue;
            }
            rows.push(buildCiTypeRow(gr, 300, ['exact_name']));
        }
        chosen = chooseBestMatch(rows, true);
        if (chosen.match) {
            resolution.table_name = chosen.match.table_name;
            resolution.label = chosen.match.label || '';
            resolution.status = 'matched';
            resolution.method = 'exact_name';
            resolution.count = chosen.count;
            resolution.rows = chosen.rows;
            resolution.match = chosen.match;
            resolution.lookup_table = chosen.match.table_name;
            resolution.selection_reason = chosen.selection_reason || 'exact_name';
            debugPush(debugEnabled, debugSteps, 'ci_type exact name resolved: ' + input + ' -> ' + chosen.match.table_name);
            return resolution;
        }
        if (chosen.ambiguous) {
            resolution.table_name = '';
            resolution.status = 'ambiguous';
            resolution.method = 'exact_name';
            resolution.count = chosen.count;
            resolution.rows = chosen.rows;
            resolution.selection_reason = chosen.selection_reason || 'top_score_tie';
            return resolution;
        }
    }

    tokens = tokenize(input);
    if (tokens.length === 0) {
        resolution.status = 'not_found';
        resolution.method = 'token_search';
        resolution.selection_reason = 'no_tokens';
        return resolution;
    }

    compactTarget = compactAlphaNum(input);
    canonicalTarget = canonicalUnderscore(input);

    gr = new GlideRecord('sys_db_object');
    if (gr.isValidField('name') && gr.isValidField('label')) {
        gr.addEncodedQuery('nameLIKE' + tokens[0] + '^ORlabelLIKE' + tokens[0]);
    } else if (gr.isValidField('label')) {
        gr.addQuery('label', 'CONTAINS', tokens[0]);
    } else if (gr.isValidField('name')) {
        gr.addQuery('name', 'CONTAINS', tokens[0]);
    }
    gr.setLimit(MAX_QUERY_ROWS * 4);
    gr.query();

    rows = [];
    while (gr.next()) {
        name = gr.isValidField('name') ? gr.getValue('name') : '';
        label = gr.isValidField('label') ? getFieldText(gr, 'label') : '';

        if (!hasValue(name) || !tableExists(name)) {
            continue;
        }

        combined = lower(name + ' ' + label);
        allTokensPresent = true;
        for (i = 0; i < tokens.length; i++) {
            if (combined.indexOf(tokens[i]) === -1) {
                allTokensPresent = false;
                break;
            }
        }

        if (!allTokensPresent) {
            continue;
        }

        score = 0;
        reasons = [];

        if (canonicalUnderscore(label) === canonicalTarget) {
            score += 220;
            reasons.push('canonical_label');
        }
        if (compactAlphaNum(label) === compactTarget) {
            score += 220;
            reasons.push('compact_label');
        }
        if (canonicalUnderscore(name) === canonicalTarget) {
            score += 180;
            reasons.push('canonical_name');
        }
        if (compactAlphaNum(name) === compactTarget) {
            score += 180;
            reasons.push('compact_name');
        }
        if (name.indexOf('cmdb_ci_') === 0) {
            score += 10;
            reasons.push('cmdb_prefix');
        }

        row = buildCiTypeRow(gr, score, reasons);
        rows.push(row);
    }

    chosen = chooseBestMatch(rows, true);
    resolution.count = chosen.count || 0;
    resolution.rows = chosen.rows || [];
    resolution.selection_reason = chosen.selection_reason || '';

    if (chosen.match) {
        resolution.table_name = chosen.match.table_name;
        resolution.label = chosen.match.label || '';
        resolution.status = 'matched';
        resolution.method = 'canonical_search';
        resolution.match = chosen.match;
        resolution.lookup_table = chosen.match.table_name;
        debugPush(debugEnabled, debugSteps, 'ci_type canonical search resolved: ' + input + ' -> ' + chosen.match.table_name);
        return resolution;
    }

    if (chosen.ambiguous) {
        resolution.status = 'ambiguous';
        resolution.method = 'canonical_search';
        debugPush(debugEnabled, debugSteps, 'ci_type canonical search ambiguous: ' + input);
        return resolution;
    }

    resolution.status = 'not_found';
    resolution.method = 'canonical_search';
    debugPush(debugEnabled, debugSteps, 'ci_type not found: ' + input);
    return resolution;
}

    
function resolveAssignmentGroupSysId(rawValue, debugEnabled, debugSteps) {
        var name = trimToString(rawValue);
        var exact;
        var tokens;
        var canonicalTarget;
        var compactTarget;
        var gr;
        var chosen;
        var i;

        if (!hasValue(name)) {
            return { sys_id: '', method: 'empty', status: 'empty', count: 0, rows: [] };
        }

        if (looksLikeSysId(name)) {
            return {
                sys_id: name,
                method: 'provided_sys_id',
                status: 'matched',
                match: { sys_id: name, name: name, score: 999, score_reasons: ['provided_sys_id'] },
                count: 1,
                rows: [{ sys_id: name, name: name, score: 999, score_reasons: ['provided_sys_id'] }],
                selection_reason: 'provided_sys_id'
            };
        }

        exact = queryExactByName('sys_user_group', 'name', name, function (groupGr) {
            if (groupGr.isValidField('active')) {
                groupGr.orderByDesc('active');
            }
        }, function (groupGr, row) {
            var extra = { score: 0, reasons: [] };
            if (groupGr.isValidField('active') && String(groupGr.getValue('active')) === 'true') {
                extra.score += 10;
            }
            return extra;
        }, false);

        if (exact.match) {
            debugPush(debugEnabled, debugSteps, 'assignment_group exact match: ' + name + ' -> ' + exact.match.sys_id);
            return {
                sys_id: exact.match.sys_id,
                method: 'exact_name',
                status: 'matched',
                matched_name: exact.match.name,
                match: exact.match,
                count: exact.count,
                rows: exact.rows,
                selection_reason: exact.selection_reason
            };
        }

        tokens = tokenize(name);
        canonicalTarget = canonicalUnderscore(name);
        compactTarget = compactAlphaNum(name);

        if (tokens.length === 0) {
            return { sys_id: '', method: 'not_found', status: 'not_found', count: 0, rows: [] };
        }

        gr = new GlideRecord('sys_user_group');
        for (i = 0; i < tokens.length; i++) {
            gr.addQuery('name', 'CONTAINS', tokens[i]);
        }
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();

        chosen = chooseBestMatch(collectMatches(gr, 'name', function (groupGr, row) {
            var candidateName = row.name;
            var extra = { score: 0, reasons: [] };
            if (canonicalUnderscore(candidateName) === canonicalTarget) {
                extra.score += 100;
                extra.reasons.push('canonical_name');
            }
            if (compactAlphaNum(candidateName) === compactTarget) {
                extra.score += 100;
                extra.reasons.push('compact_name');
            }
            if (groupGr.isValidField('active') && String(groupGr.getValue('active')) === 'true') {
                extra.score += 10;
            }
            return extra;
        }), true);

        if (chosen.match) {
            debugPush(debugEnabled, debugSteps, 'assignment_group canonical match: ' + name + ' -> ' + chosen.match.sys_id);
            return {
                sys_id: chosen.match.sys_id,
                method: 'canonical_name',
                status: 'matched',
                matched_name: chosen.match.name,
                match: chosen.match,
                count: chosen.count,
                rows: chosen.rows,
                selection_reason: chosen.selection_reason
            };
        }

        if (chosen.ambiguous) {
            debugPush(debugEnabled, debugSteps, 'assignment_group ambiguous: ' + name);
            return {
                sys_id: '',
                method: 'ambiguous',
                status: 'ambiguous',
                count: chosen.count,
                rows: chosen.rows,
                selection_reason: chosen.selection_reason
            };
        }

        debugPush(debugEnabled, debugSteps, 'assignment_group not found: ' + name);
        return {
            sys_id: '',
            method: 'not_found',
            status: 'not_found',
            count: chosen.count || 0,
            rows: chosen.rows || [],
            selection_reason: chosen.selection_reason || 'no_match'
        };
    }

    
function normalizeAssignmentGroup(additionalInfo, debugEnabled, debugSteps) {
        var rawGroupName;
        var resolved;

        if (!hasValue(additionalInfo.assignment_group)) {
            return;
        }

        rawGroupName = trimToString(additionalInfo.assignment_group);
        resolved = resolveAssignmentGroupSysId(rawGroupName, debugEnabled, debugSteps);

        additionalInfo.assignment_group_name = rawGroupName;
        additionalInfo.assignment_group_lookup_status = resolved.status || resolved.method || 'not_found';
        additionalInfo.assignment_group_lookup_method = resolved.method || '';

        applyLookupDebug(additionalInfo, 'assignment_group', rawGroupName, resolved, debugEnabled);

        if (hasValue(resolved.sys_id)) {
            additionalInfo.assignment_group = resolved.sys_id;
            if (hasValue(resolved.matched_name)) {
                additionalInfo.assignment_group_matched_name = resolved.matched_name;
            }
            return;
        }

        delete additionalInfo.assignment_group;
    }

    function parseCiIdentifier(rawValue) {
        var parsed;
        if (!hasValue(rawValue)) {
            return null;
        }
        if (isObject(rawValue)) {
            return rawValue;
        }
        if (typeof rawValue === 'string') {
            parsed = tryParseJSON(rawValue);
            if (parsed !== null && isObject(parsed)) {
                return parsed;
            }
        }
        return null;
    }

    function getQueryField(gr, candidates) {
        var i;
        for (i = 0; i < candidates.length; i++) {
            if (gr.isValidField(candidates[i])) {
                return candidates[i];
            }
        }
        return '';
    }

    function resolveRecordByIdentifier(tableName, identifierObj, debugEnabled, debugSteps) {
        var gr;
        var key;
        var validKeyCount = 0;
        var rows;
        if (!tableExists(tableName) || !isObject(identifierObj)) {
            return { match: null, count: 0, ambiguous: false };
        }

        gr = new GlideRecord(tableName);

        for (key in identifierObj) {
            if (!hasOwn(identifierObj, key)) {
                continue;
            }
            if (!hasValue(identifierObj[key])) {
                continue;
            }
            if (!gr.isValidField(key)) {
                continue;
            }
            validKeyCount++;
            gr.addQuery(key, trimToString(identifierObj[key]));
        }

        if (validKeyCount === 0) {
            debugPush(debugEnabled, debugSteps, 'ci_identifier has no valid keys for table ' + tableName);
            return { match: null, count: 0, ambiguous: false };
        }

        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();
        rows = collectMatches(gr, 'name');
        return chooseBestMatch(rows, true);
    }

    function resolveCmdbCiByName(nameValue, debugEnabled, debugSteps) {
        var name = trimToString(nameValue);
        var exact;
        var tokens;
        var canonicalTarget;
        var compactTarget;
        var gr;
        var chosen;
        var i;

        if (!hasValue(name) || !tableExists('cmdb_ci')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'empty' };
        }

        exact = queryExactByName('cmdb_ci', 'name', name, null, function (ciGr, row) {
            return getCmdbCiLookupExtraScore(ciGr, row, '', '');
        }, true);
        exact.status = exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found');
        exact.method = 'exact_name';

        if (exact.match) {
            debugPush(debugEnabled, debugSteps, 'cmdb_ci exact match: ' + name + ' -> ' + exact.match.sys_id);
            return exact;
        }

        tokens = tokenize(name);
        canonicalTarget = canonicalUnderscore(name);
        compactTarget = compactAlphaNum(name);

        if (tokens.length === 0) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_found', method: 'canonical_name' };
        }

        gr = new GlideRecord('cmdb_ci');
        if (!gr.isValidField('name')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: 'canonical_name' };
        }

        for (i = 0; i < tokens.length; i++) {
            gr.addQuery('name', 'CONTAINS', tokens[i]);
        }
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();

        chosen = chooseBestMatch(collectMatches(gr, 'name', function (ciGr, row) {
            return getCmdbCiLookupExtraScore(ciGr, row, canonicalTarget, compactTarget);
        }), true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = 'canonical_name';

        if (chosen.match) {
            debugPush(debugEnabled, debugSteps, 'cmdb_ci canonical match: ' + name + ' -> ' + chosen.match.sys_id);
            return chosen;
        }
        if (chosen.ambiguous) {
            debugPush(debugEnabled, debugSteps, 'cmdb_ci canonical lookup ambiguous: ' + name);
            return chosen;
        }

        debugPush(debugEnabled, debugSteps, 'cmdb_ci not found: ' + name);
        return chosen;
    }

    function validateCmdbCiSysId(sysId, debugEnabled, debugSteps) {
        var gr;
        if (!looksLikeSysId(sysId) || !tableExists('cmdb_ci')) {
            return null;
        }
        gr = new GlideRecord('cmdb_ci');
        if (!gr.get(sysId)) {
            debugPush(debugEnabled, debugSteps, 'provided cmdb_ci sys_id not found: ' + sysId);
            return null;
        }
        return {
            sys_id: gr.getUniqueValue(),
            name: getFieldText(gr, 'name'),
            sys_class_name: getFieldText(gr, 'sys_class_name')
        };
    }

    
function resolveCmdbCi(mapped, remaining, additionalInfo, debugEnabled, debugSteps) {
        var validated;
        var identifierObj;
        var exact;
        var nameValue;
        var result = null;
        var resolution = {
            status: 'not_attempted',
            method: '',
            count: 0,
            rows: [],
            selection_reason: ''
        };
        var debugInput = '';

        if (hasValue(mapped.cmdb_ci)) {
            debugInput = mapped.cmdb_ci;
            if (looksLikeSysId(mapped.cmdb_ci)) {
                validated = validateCmdbCiSysId(mapped.cmdb_ci, debugEnabled, debugSteps);
                if (validated) {
                    validated.score = 999;
                    validated.score_reasons = ['provided_sys_id'];
                    result = validated;
                    resolution = {
                        status: 'matched',
                        method: 'provided_sys_id',
                        count: 1,
                        rows: [validated],
                        match: validated,
                        selection_reason: 'provided_sys_id'
                    };
                } else {
                    resolution = {
                        status: 'not_found',
                        method: 'provided_sys_id',
                        count: 0,
                        rows: [],
                        selection_reason: 'not_found'
                    };
                }
            } else {
                exact = resolveCmdbCiByName(mapped.cmdb_ci, debugEnabled, debugSteps);
                resolution = {
                    status: exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found'),
                    method: exact.method || 'cmdb_ci_name',
                    count: exact.count,
                    rows: exact.rows,
                    match: exact.match,
                    selection_reason: exact.selection_reason
                };
                if (exact.match) {
                    result = exact.match;
                    additionalInfo.cmdb_ci_lookup_method = exact.method || 'cmdb_ci_name';
                }
            }
        }

        if (!result && hasValue(mapped.ci_type) && hasValue(mapped.ci_identifier)) {
            identifierObj = parseCiIdentifier(mapped.ci_identifier);
            if (identifierObj) {
                debugInput = identifierObj;
                exact = resolveRecordByIdentifier(mapped.ci_type, identifierObj, debugEnabled, debugSteps);
                resolution = {
                    status: exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found'),
                    method: 'ci_type_and_ci_identifier',
                    lookup_table: mapped.ci_type,
                    count: exact.count,
                    rows: exact.rows,
                    match: exact.match,
                    selection_reason: exact.selection_reason
                };
                if (exact.match) {
                    result = exact.match;
                    additionalInfo.cmdb_ci_lookup_method = 'ci_identifier';
                    additionalInfo.cmdb_ci_lookup_table = mapped.ci_type;
                } else if (exact.ambiguous) {
                    additionalInfo.cmdb_ci_lookup_status = 'ambiguous';
                    additionalInfo.cmdb_ci_lookup_table = mapped.ci_type;
                }
            }
        }

        if (!result && !hasValue(mapped.node)) {
            nameValue = '';
            if (isObject(remaining) && hasValue(remaining.name)) {
                nameValue = remaining.name;
                delete remaining.name;
            } else if (hasValue(additionalInfo.name)) {
                nameValue = additionalInfo.name;
                delete additionalInfo.name;
            }
            if (hasValue(nameValue)) {
                debugInput = nameValue;
                exact = resolveCmdbCiByName(nameValue, debugEnabled, debugSteps);
                resolution = {
                    status: exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found'),
                    method: exact.method || 'name_fallback',
                    count: exact.count,
                    rows: exact.rows,
                    match: exact.match,
                    selection_reason: exact.selection_reason
                };
                if (exact.match) {
                    result = exact.match;
                    additionalInfo.cmdb_ci_lookup_method = exact.method || 'name_fallback';
                } else if (exact.ambiguous) {
                    additionalInfo.cmdb_ci_lookup_status = 'ambiguous';
                }
            }
        }

        applyLookupDebug(additionalInfo, 'cmdb_ci', debugInput, resolution, debugEnabled);
        if (hasValue(mapped.ci_type) && debugEnabled) {
            additionalInfo.cmdb_ci_lookup_table = mapped.ci_type;
        }

        if (result && hasValue(result.sys_id)) {
            mapped.cmdb_ci = result.sys_id;
            additionalInfo.cmdb_ci = result.sys_id;
            additionalInfo.cmdb_ci_name = result.name || '';
            if (hasValue(result.sys_class_name)) {
                additionalInfo.cmdb_ci_class = result.sys_class_name;
            }
            additionalInfo.cmdb_ci_lookup_status = 'matched';
        } else if (resolution.status && resolution.status !== 'not_attempted') {
            mapped.cmdb_ci = '';
            additionalInfo.cmdb_ci_lookup_status = resolution.status;
        }

        return result;
    }

    
function resolveServiceFromAssoc(ciSysId, debugEnabled, debugSteps) {
        var gr;
        var ciField;
        var serviceField;
        var rows = [];
        var serviceSysId;
        var serviceGr;
        var chosen;
        if (!looksLikeSysId(ciSysId) || !tableExists('svc_ci_assoc') || !tableExists('cmdb_ci_service')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'svc_ci_assoc' };
        }

        gr = new GlideRecord('svc_ci_assoc');
        ciField = getQueryField(gr, ['ci', 'cmdb_ci', 'configuration_item', 'ci_id']);
        serviceField = getQueryField(gr, ['service', 'business_service', 'cmdb_ci_service', 'service_id']);

        if (!hasValue(ciField) || !hasValue(serviceField)) {
            debugPush(debugEnabled, debugSteps, 'svc_ci_assoc fields not found');
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: 'svc_ci_assoc' };
        }

        gr.addQuery(ciField, ciSysId);
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();

        while (gr.next()) {
            serviceSysId = gr.getValue(serviceField);
            if (!looksLikeSysId(serviceSysId)) {
                continue;
            }
            serviceGr = new GlideRecord('cmdb_ci_service');
            if (!serviceGr.get(serviceSysId)) {
                continue;
            }
            rows.push({
                sys_id: serviceGr.getUniqueValue(),
                name: getFieldText(serviceGr, 'name'),
                number: serviceGr.isValidField('number') ? serviceGr.getDisplayValue('number') : '',
                sys_class_name: serviceGr.isValidField('sys_class_name') ? serviceGr.getValue('sys_class_name') : '',
                operational_status: serviceGr.isValidField('operational_status') ? serviceGr.getDisplayValue('operational_status') : '',
                install_status: serviceGr.isValidField('install_status') ? serviceGr.getDisplayValue('install_status') : '',
                active: serviceGr.isValidField('active') ? serviceGr.getValue('active') : '',
                score: getStatusScore(serviceGr),
                score_reasons: getStatusReasonList(serviceGr).concat(['service_association'])
            });
        }

        chosen = chooseBestMatch(rows, false);
        if (chosen.match) {
            debugPush(debugEnabled, debugSteps, 'service inferred from svc_ci_assoc: ' + chosen.match.sys_id);
        }
        chosen.status = chosen.match ? 'matched' : 'not_found';
        chosen.method = 'svc_ci_assoc';
        return chosen;
    }

    
function resolveServiceByName(nameValue, debugEnabled, debugSteps) {
        var exact = queryExactByName('cmdb_ci_service', 'name', nameValue, null, null, true);
        exact.status = exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found');
        exact.method = 'exact_name';
        if (exact.match) {
            debugPush(debugEnabled, debugSteps, 'service exact match: ' + nameValue + ' -> ' + exact.match.sys_id);
        }
        if (exact.ambiguous) {
            debugPush(debugEnabled, debugSteps, 'service ambiguous: ' + nameValue);
        }
        return exact;
    }

    
function resolveBusinessAppByCarId(carIdValue, debugEnabled, debugSteps) {
        var gr;
        var chosen;
        if (!hasValue(carIdValue) || !tableExists('cmdb_ci_business_app')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'u_car_id' };
        }
        gr = new GlideRecord('cmdb_ci_business_app');
        if (gr.isValidField('u_car_id')) {
            gr.addQuery('u_car_id', trimToString(carIdValue));
        } else {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: 'u_car_id' };
        }
        if (gr.isValidField('sys_class_name')) {
            gr.addQuery('sys_class_name', 'cmdb_ci_business_app');
        }
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();
        chosen = chooseBestMatch(collectMatches(gr, 'name', function (appGr, row) {
            var extra = { score: 0, reasons: [] };
            if (appGr.isValidField('sys_class_name') && String(appGr.getValue('sys_class_name')) === 'cmdb_ci_business_app') {
                extra.score += 100;
                extra.reasons.push('expected_class');
            }
            return extra;
        }), true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = 'u_car_id';
        if (chosen.match) {
            debugPush(debugEnabled, debugSteps, 'business app match for usbem_car_id ' + carIdValue + ': ' + chosen.match.sys_id);
        }
        return chosen;
    }

    
function resolveOfferingByName(nameValue, serviceSysId, debugEnabled, debugSteps) {
        var gr;
        var chosen;
        if (!hasValue(nameValue) || !tableExists('service_offering')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: hasValue(serviceSysId) ? 'name_and_parent' : 'name' };
        }
        gr = new GlideRecord('service_offering');
        if (!gr.isValidField('name')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: hasValue(serviceSysId) ? 'name_and_parent' : 'name' };
        }
        gr.addQuery('name', trimToString(nameValue));
        if (hasValue(serviceSysId) && gr.isValidField('parent')) {
            gr.addQuery('parent', serviceSysId);
        }
        gr.setLimit(MAX_QUERY_ROWS);
        gr.query();
        chosen = chooseBestMatch(collectMatches(gr, 'name', function (offeringGr, row) {
            var extra = { score: 0, reasons: [] };
            if (hasValue(serviceSysId) && offeringGr.isValidField('parent') && offeringGr.getValue('parent') === serviceSysId) {
                extra.score += 120;
                extra.reasons.push('service_parent_match');
            }
            return extra;
        }), true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = hasValue(serviceSysId) ? 'name_and_parent' : 'name';
        if (chosen.match) {
            debugPush(debugEnabled, debugSteps, 'offering match: ' + nameValue + ' -> ' + chosen.match.sys_id);
        }
        return chosen;
    }

    function copyUnmappedIntoAdditionalInfo(additionalInfo, sourceObj) {
        if (isObject(sourceObj) && !isEmptyObject(sourceObj)) {
            mergeDeep(additionalInfo, sourceObj);
        }
    }

    function getDtiSeverityConfig(severityValue) {
        if (hasOwn(DTI_SEVERITY_CONFIG, String(severityValue))) {
            return DTI_SEVERITY_CONFIG[String(severityValue)];
        }
        return DTI_SEVERITY_CONFIG['4'];
    }

    function resolveDtiImpactUrgency(directToIncidentRequested, dtiWaitForIncident, mappedSeverity, providedImpact, providedUrgency, additionalInfo, debugEnabled, debugSteps) {
        var config = getDtiSeverityConfig(mappedSeverity);
        var impact = hasValue(providedImpact) ? trimToString(providedImpact) : config.impact;
        var urgency = hasValue(providedUrgency) ? trimToString(providedUrgency) : config.urgency;
        var allowIncident = config.allow_incident;
        var providedAny = hasValue(providedImpact) || hasValue(providedUrgency);

        if (directToIncidentRequested) {
            additionalInfo.dti_impact = String(impact);
            additionalInfo.dti_urgency = String(urgency);
            additionalInfo.dti_severity_policy = config.label;
            if (!providedAny) {
                additionalInfo.dti_impact_source = 'severity_map';
                additionalInfo.dti_urgency_source = 'severity_map';
            } else {
                additionalInfo.dti_impact_source = hasValue(providedImpact) ? 'payload' : 'severity_map';
                additionalInfo.dti_urgency_source = hasValue(providedUrgency) ? 'payload' : 'severity_map';
            }
        } else {
            if (hasValue(providedImpact)) {
                additionalInfo.dti_impact = String(impact);
                additionalInfo.dti_impact_source = 'payload';
            }
            if (hasValue(providedUrgency)) {
                additionalInfo.dti_urgency = String(urgency);
                additionalInfo.dti_urgency_source = 'payload';
            }
        }

        if (providedAny && dtiWaitForIncident) {
            allowIncident = true;
        }

        debugPush(debugEnabled, debugSteps, 'DTI impact/urgency resolved to ' + impact + '/' + urgency + ', allow_incident=' + allowIncident);

        return {
            impact: String(impact),
            urgency: String(urgency),
            allow_incident: allowIncident,
            provided_any: providedAny
        };
    }

    function findAlertByMessageKey(messageKey, source, eventClass) {
        var gr;
        if (!hasValue(messageKey) || !tableExists('em_alert')) {
            return null;
        }
        gr = new GlideRecord('em_alert');
        if (gr.isValidField('message_key')) {
            gr.addQuery('message_key', messageKey);
        } else {
            return null;
        }
        if (hasValue(source) && gr.isValidField('source')) {
            gr.addQuery('source', source);
        }
        if (hasValue(eventClass) && gr.isValidField('event_class')) {
            gr.addQuery('event_class', eventClass);
        }
        if (gr.isValidField('sys_updated_on')) {
            gr.orderByDesc('sys_updated_on');
        }
        if (gr.isValidField('sys_created_on')) {
            gr.orderByDesc('sys_created_on');
        }
        gr.setLimit(1);
        gr.query();
        if (gr.next()) {
            return gr;
        }
        return null;
    }

    function getEventBySysId(eventSysId) {
        var gr;
        if (!looksLikeSysId(eventSysId) || !tableExists('em_event')) {
            return null;
        }
        gr = new GlideRecord('em_event');
        if (gr.get(eventSysId)) {
            return gr;
        }
        return null;
    }

    function getAlertBySysId(alertSysId) {
        var gr;
        if (!looksLikeSysId(alertSysId) || !tableExists('em_alert')) {
            return null;
        }
        gr = new GlideRecord('em_alert');
        if (gr.get(alertSysId)) {
            return gr;
        }
        return null;
    }

    function getAlertFromEvent(eventGr) {
        var alertSysId;
        var alertGr;
        if (!eventGr || !eventGr.isValidField('alert')) {
            return null;
        }
        alertSysId = eventGr.getValue('alert');
        if (!looksLikeSysId(alertSysId)) {
            return null;
        }
        alertGr = getAlertBySysId(alertSysId);
        return alertGr;
    }

    function getEventStateInfo(eventGr) {
        var rawValue = '';
        var displayValue = '';
        var normalized = '';

        if (eventGr && eventGr.isValidField('state')) {
            rawValue = eventGr.getValue('state') || '';
            displayValue = eventGr.getDisplayValue('state') || rawValue || '';
        }

        normalized = normalizeKey(displayValue || rawValue);

        return {
            raw: rawValue,
            display: displayValue,
            normalized: normalized
        };
    }

    function isReadyEventState(stateInfo) {
        if (!stateInfo) {
            return true;
        }
        return stateInfo.normalized === '' || stateInfo.normalized === 'ready';
    }

    function waitForAlert(eventSysId, messageKey, source, eventClass, deadlineMs, pollMs, debugEnabled, debugSteps) {
        var alertGr = null;
        var eventGr = null;
        var stateInfo;
        var now;
        var nextPollAt = 0;
        var lastState = '';

        while (true) {
            now = new Date().getTime();
            if (now >= deadlineMs) {
                break;
            }
            if (now < nextPollAt) {
                continue;
            }
            nextPollAt = now + pollMs;

            if (looksLikeSysId(eventSysId)) {
                eventGr = getEventBySysId(eventSysId);
                if (eventGr) {
                    stateInfo = getEventStateInfo(eventGr);

                    if ((stateInfo.display || stateInfo.raw) !== lastState) {
                        lastState = stateInfo.display || stateInfo.raw || '';
                        if (hasValue(lastState)) {
                            debugPush(debugEnabled, debugSteps, 'event state observed: ' + lastState);
                        }
                    }

                    alertGr = getAlertFromEvent(eventGr);
                    if (alertGr) {
                        debugPush(debugEnabled, debugSteps, 'alert located via em_event.alert');
                        return alertGr;
                    }

                    if (!isReadyEventState(stateInfo) && hasValue(messageKey)) {
                        alertGr = findAlertByMessageKey(messageKey, source, eventClass);
                        if (alertGr) {
                            debugPush(debugEnabled, debugSteps, 'alert located by message_key after event left Ready state');
                            return alertGr;
                        }
                    }
                }
            }

            if (hasValue(messageKey)) {
                alertGr = findAlertByMessageKey(messageKey, source, eventClass);
                if (alertGr) {
                    debugPush(debugEnabled, debugSteps, 'alert located by message_key ' + messageKey);
                    return alertGr;
                }
            }
        }

        if (hasValue(messageKey)) {
            alertGr = findAlertByMessageKey(messageKey, source, eventClass);
            if (alertGr) {
                debugPush(debugEnabled, debugSteps, 'alert located by message_key on final pass ' + messageKey);
                return alertGr;
            }
        }

        if (looksLikeSysId(eventSysId)) {
            eventGr = getEventBySysId(eventSysId);
            if (eventGr) {
                alertGr = getAlertFromEvent(eventGr);
                if (alertGr) {
                    debugPush(debugEnabled, debugSteps, 'alert located via em_event.alert on final pass');
                    return alertGr;
                }
            }
        }

        debugPush(debugEnabled, debugSteps, 'alert wait timed out');
        return null;
    }

    function waitForIncidentOnAlert(alertGr, deadlineMs, pollMs, debugEnabled, debugSteps) {
        var alertSysId;
        var now;
        var nextPollAt = 0;
        var refreshedAlert;
        var incidentGr;

        if (!alertGr) {
            return null;
        }

        incidentGr = getIncidentFromAlert(alertGr);
        if (incidentGr) {
            debugPush(debugEnabled, debugSteps, 'incident already linked on alert');
            return incidentGr;
        }

        alertSysId = alertGr.getUniqueValue();

        while (true) {
            now = new Date().getTime();
            if (now >= deadlineMs) {
                break;
            }
            if (now < nextPollAt) {
                continue;
            }
            nextPollAt = now + pollMs;

            refreshedAlert = getAlertBySysId(alertSysId);
            if (!refreshedAlert) {
                break;
            }

            incidentGr = getIncidentFromAlert(refreshedAlert);
            if (incidentGr) {
                debugPush(debugEnabled, debugSteps, 'incident linked on alert after state polling');
                return incidentGr;
            }
        }

        refreshedAlert = getAlertBySysId(alertSysId);
        if (refreshedAlert) {
            incidentGr = getIncidentFromAlert(refreshedAlert);
            if (incidentGr) {
                debugPush(debugEnabled, debugSteps, 'incident linked on alert on final pass');
                return incidentGr;
            }
        }

        debugPush(debugEnabled, debugSteps, 'incident wait timed out on alert');
        return null;
    }

    function getIncidentFromAlert(alertGr) {
        var sysId;
        var inc;

        if (!alertGr) {
            return null;
        }

        if (alertGr.isValidField('incident')) {
            sysId = alertGr.getValue('incident');
            if (looksLikeSysId(sysId)) {
                inc = new GlideRecord('incident');
                if (inc.get(sysId)) {
                    return inc;
                }
            }
        }

        if (alertGr.isValidField('task')) {
            sysId = alertGr.getValue('task');
            if (looksLikeSysId(sysId)) {
                inc = new GlideRecord('incident');
                if (inc.get(sysId)) {
                    return inc;
                }
            }
        }

        return null;
    }

    function setWorkNotesIfPresent(incGr, value) {
        if (!hasValue(value)) {
            return;
        }
        if (incGr.isValidField('work_notes')) {
            incGr.setValue('work_notes', String(value));
        } else if (incGr.isValidField('comments')) {
            incGr.setValue('comments', String(value));
        }
    }

    function createIncidentFromAlert(alertGr, mapped, additionalInfo, dtiDecision, debugEnabled, debugSteps) {
        var inc;
        var sysId;
        var shortDescription;
        var description;
        var incident;
        if (!tableExists('incident')) {
            return null;
        }

        inc = new GlideRecord('incident');
        inc.initialize();

        // Incident mapping rule:
        // - dti_short_description -> incident.short_description
        // - event description      -> incident.description
        shortDescription = hasValue(additionalInfo.dti_short_description) ? additionalInfo.dti_short_description : mapped.description;
        description = mapped.description;

        setIfPresent(inc, 'short_description', truncateString(shortDescription, 160));
        setIfPresent(inc, 'description', truncateString(description, 4000));
        setIfPresent(inc, 'impact', dtiDecision.impact);
        setIfPresent(inc, 'urgency', dtiDecision.urgency);

        if (hasValue(additionalInfo.assignment_group) && looksLikeSysId(additionalInfo.assignment_group)) {
            setIfPresent(inc, 'assignment_group', additionalInfo.assignment_group);
        }
        if (hasValue(additionalInfo.cmdb_ci) && looksLikeSysId(additionalInfo.cmdb_ci)) {
            setIfPresent(inc, 'cmdb_ci', additionalInfo.cmdb_ci);
        }
        if (hasValue(additionalInfo.cmdb_ci_service) && looksLikeSysId(additionalInfo.cmdb_ci_service)) {
            if (inc.isValidField('business_service')) {
                inc.setValue('business_service', additionalInfo.cmdb_ci_service);
            } else if (inc.isValidField('service')) {
                inc.setValue('service', additionalInfo.cmdb_ci_service);
            }
        }
        if (hasValue(additionalInfo.cmdb_ci_service_offering) && looksLikeSysId(additionalInfo.cmdb_ci_service_offering) && inc.isValidField('service_offering')) {
            inc.setValue('service_offering', additionalInfo.cmdb_ci_service_offering);
        }

        setWorkNotesIfPresent(inc, additionalInfo.dti_work_note);

        sysId = inc.insert();
        if (!looksLikeSysId(sysId)) {
            return null;
        }

        if (alertGr) {
            if (alertGr.isValidField('incident')) {
                alertGr.setValue('incident', sysId);
            }
            if (alertGr.isValidField('task')) {
                alertGr.setValue('task', sysId);
            }
            alertGr.update();
        }

        debugPush(debugEnabled, debugSteps, 'incident created: ' + sysId);

        incident = new GlideRecord('incident');
        if (incident.get(sysId)) {
            return incident;
        }
        return null;
    }

    function buildResultSkeleton() {
        return {
            status: 'success',
            event_sys_id: '',
            message_key: '',
            alert_sys_id: '',
            alert_number: '',
            incident_sys_id: '',
            incident_number: ''
        };
    }

    function summarizeAlert(alertGr) {
        var out = { alert_sys_id: '', alert_number: '' };
        if (!alertGr) {
            return out;
        }
        out.alert_sys_id = alertGr.getUniqueValue();
        out.alert_number = alertGr.isValidField('number') ? (alertGr.getValue('number') || alertGr.getDisplayValue('number') || '') : '';
        return out;
    }

    function summarizeIncident(incidentGr) {
        var out = { incident_sys_id: '', incident_number: '' };
        if (!incidentGr) {
            return out;
        }
        out.incident_sys_id = incidentGr.getUniqueValue();
        out.incident_number = incidentGr.isValidField('number') ? (incidentGr.getValue('number') || incidentGr.getDisplayValue('number') || '') : '';
        return out;
    }

    function processSingleEvent(rawEvent, envelope) {
        var startedAt = new Date().getTime();
        var debugSteps = [];
        var working;
        var remaining;
        var rawAdditionalInfo = null;
        var mapped = {};
        var special = {};
        var fieldName;
        var additionalInfo = {};
        var result = buildResultSkeleton();
        var gr;
        var sysId;
        var directToIncidentRequested;
        var waitForAlertRequested;
        var dtiWaitForIncident;
        var waitSeconds;
        var waitMs;
        var waitDeadlineMs;
        var alertGr;
        var existingIncident;
        var createdIncident;
        var dtiDecision;
        var ciMatch;
        var businessAppMatch;
        var serviceMatch;
        var offeringMatch;
        var debugEnabled;
        var ciIdentifierObj;
        var ciTypeResolution;

        if (isObject(rawEvent)) {
            working = deepClone(envelope);
            mergeDeep(working, rawEvent);
        } else {
            working = deepClone(envelope);
            working.description = String(rawEvent);
        }

        if (hasOwn(working, 'additional_info')) {
            rawAdditionalInfo = working.additional_info;
            delete working.additional_info;
        } else if (hasOwn(working, 'additionalInfo')) {
            rawAdditionalInfo = working.additionalInfo;
            delete working.additionalInfo;
        }

        remaining = deepClone(working);

        for (fieldName in FIELD_ALIASES) {
            if (hasOwn(FIELD_ALIASES, fieldName)) {
                maybePromoteField(remaining, FIELD_ALIASES[fieldName], mapped, fieldName);
            }
        }

        for (fieldName in SPECIAL_ALIASES) {
            if (hasOwn(SPECIAL_ALIASES, fieldName)) {
                maybePromoteField(remaining, SPECIAL_ALIASES[fieldName], special, fieldName);
            }
        }

        mergeAdditionalInfo(additionalInfo, rawAdditionalInfo);

        for (fieldName in FIELD_ALIASES) {
            if (hasOwn(FIELD_ALIASES, fieldName)) {
                maybePromoteField(additionalInfo, FIELD_ALIASES[fieldName], mapped, fieldName);
            }
        }

        for (fieldName in SPECIAL_ALIASES) {
            if (hasOwn(SPECIAL_ALIASES, fieldName)) {
                maybePromoteField(additionalInfo, SPECIAL_ALIASES[fieldName], special, fieldName);
            }
        }

        debugEnabled = parseBoolean(special.usbem_debug, false);
        debugPush(debugEnabled, debugSteps, 'USBEM version ' + VERSION);

        if (hasValue(mapped.time_of_event)) {
            mapped.time_of_event = normalizeTime(mapped.time_of_event);
        }

        if (hasValue(mapped.resolution_state)) {
            mapped.resolution_state = normalizeResolutionState(mapped.resolution_state);
        }

        mapped.severity = mapSeverity(mapped.severity, additionalInfo);
        if (!hasValue(mapped.severity)) {
            mapped.severity = DEFAULT_SEVERITY;
        }

        if (!hasValue(mapped.source)) {
            mapped.source = DEFAULT_SOURCE;
        }
        if (!hasValue(mapped.event_class)) {
            mapped.event_class = mapped.source;
        }
        if (!hasValue(mapped.description)) {
            mapped.description = DEFAULT_DESCRIPTION;
        }

        if (!hasValue(mapped.message_key)) {
            mapped.message_key = normalizeMessageKey('', mapped);
        } else {
            mapped.message_key = normalizeMessageKey(mapped.message_key, mapped);
        }

        if (hasValue(mapped.ci_type)) {
            ciTypeResolution = resolveCiTypeTable(mapped.ci_type, debugEnabled, debugSteps);
            applyLookupDebug(additionalInfo, 'ci_type', mapped.ci_type, ciTypeResolution, debugEnabled);

            if (ciTypeResolution && hasValue(ciTypeResolution.table_name)) {
                if (debugEnabled && hasValue(ciTypeResolution.label)) {
                    additionalInfo.ci_type_label = ciTypeResolution.label;
                }
                if (debugEnabled) {
                    additionalInfo.ci_type_resolved = ciTypeResolution.table_name;
                }
                mapped.ci_type = ciTypeResolution.table_name;
            }
        }

        ciIdentifierObj = parseCiIdentifier(mapped.ci_identifier);
        if (ciIdentifierObj) {
            mapped.ci_identifier = JSON.stringify(ciIdentifierObj);
        }

        copyUnmappedIntoAdditionalInfo(additionalInfo, remaining);

        directToIncidentRequested = parseBoolean(special.direct_to_incident, false);
        dtiWaitForIncident = parseBoolean(special.dti_wait_for_incident, false);
        waitForAlertRequested = parseBoolean(special.usbem_wait_for_alert, false) || dtiWaitForIncident;
        waitSeconds = toInt(special.usbem_wait_seconds, 0);
        if (waitSeconds <= 0) {
            waitSeconds = Math.floor(WAIT_ALERT_TIMEOUT_MS / 1000);
        }
        waitMs = waitSeconds * 1000;

        if (hasValue(special.assignment_group)) {
            additionalInfo.assignment_group = String(special.assignment_group);
        }

        if (hasValue(special.direct_to_incident) || directToIncidentRequested) {
            additionalInfo.direct_to_incident = directToIncidentRequested ? 'true' : String(special.direct_to_incident);
        }
        if (directToIncidentRequested && !hasValue(additionalInfo.dti_short_description)) {
            additionalInfo.dti_short_description = mapped.description;
            if (debugEnabled) {
                additionalInfo.dti_short_description_source = 'event_description';
            }
        }
        if (hasValue(special.dti_wait_for_incident)) {
            additionalInfo.dti_wait_for_incident = dtiWaitForIncident ? 'true' : String(special.dti_wait_for_incident);
        }
        if (hasValue(special.usbem_wait_for_alert)) {
            additionalInfo.usbem_wait_for_alert = parseBoolean(special.usbem_wait_for_alert, false) ? 'true' : String(special.usbem_wait_for_alert);
        }

        if (debugEnabled) {
            additionalInfo.usbem_debug = 'true';
            additionalInfo.usbem_version = VERSION;
        }

        normalizeAssignmentGroup(additionalInfo, debugEnabled, debugSteps);

        ciMatch = resolveCmdbCi(mapped, remaining, additionalInfo, debugEnabled, debugSteps);

        if (hasValue(special.usbem_car_id)) {
            additionalInfo.usbem_car_id = String(special.usbem_car_id);
            businessAppMatch = resolveBusinessAppByCarId(special.usbem_car_id, debugEnabled, debugSteps);
            applyLookupDebug(additionalInfo, 'cmdb_ci_business_app', String(special.usbem_car_id), businessAppMatch, debugEnabled);
            if (businessAppMatch && businessAppMatch.match) {
                additionalInfo.cmdb_ci_business_app = businessAppMatch.match.sys_id;
                additionalInfo.cmdb_ci_business_app_name = businessAppMatch.match.name || '';
            }
        }

        if (hasValue(special.usbem_service)) {
            additionalInfo.usbem_service = String(special.usbem_service);
            serviceMatch = resolveServiceByName(special.usbem_service, debugEnabled, debugSteps);
            applyLookupDebug(additionalInfo, 'cmdb_ci_service', String(special.usbem_service), serviceMatch, debugEnabled);
        } else if (ciMatch && hasValue(ciMatch.sys_id)) {
            serviceMatch = resolveServiceFromAssoc(ciMatch.sys_id, debugEnabled, debugSteps);
            applyLookupDebug(additionalInfo, 'cmdb_ci_service', ciMatch.sys_id, serviceMatch, debugEnabled);
        }

        if (serviceMatch && serviceMatch.match) {
            additionalInfo.cmdb_ci_service = serviceMatch.match.sys_id;
            additionalInfo.cmdb_ci_service_name = serviceMatch.match.name || '';
        }

        if (hasValue(special.usbem_offering)) {
            additionalInfo.usbem_offering = String(special.usbem_offering);
            offeringMatch = resolveOfferingByName(special.usbem_offering, (serviceMatch && serviceMatch.match) ? serviceMatch.match.sys_id : '', debugEnabled, debugSteps);
            applyLookupDebug(additionalInfo, 'cmdb_ci_service_offering', String(special.usbem_offering), offeringMatch, debugEnabled);
            if (offeringMatch && offeringMatch.match) {
                additionalInfo.cmdb_ci_service_offering = offeringMatch.match.sys_id;
                additionalInfo.cmdb_ci_service_offering_name = offeringMatch.match.name || '';
            }
        }

        dtiDecision = resolveDtiImpactUrgency(
            directToIncidentRequested,
            dtiWaitForIncident,
            mapped.severity,
            special.dti_impact,
            special.dti_urgency,
            additionalInfo,
            debugEnabled,
            debugSteps
        );

        gr = new GlideRecord('em_event');
        gr.initialize();

        setIfPresent(gr, 'source', truncateString(mapped.source, 200));
        setIfPresent(gr, 'event_class', truncateString(mapped.event_class, 200));
        setIfPresent(gr, 'node', truncateString(mapped.node, 200));
        setIfPresent(gr, 'resource', truncateString(mapped.resource, 200));
        setIfPresent(gr, 'metric_name', mapped.metric_name);
        setIfPresent(gr, 'type', truncateString(mapped.type, 200));
        setIfPresent(gr, 'message_key', mapped.message_key);
        setIfPresent(gr, 'ci_type', mapped.ci_type);
        setIfPresent(gr, 'cmdb_ci', mapped.cmdb_ci);
        setIfPresent(gr, 'service', mapped.service);
        setIfPresent(gr, 'service_offering', mapped.service_offering);
        setIfPresent(gr, 'severity', mapped.severity);
        setIfPresent(gr, 'description', truncateString(mapped.description, 4000));
        setIfPresent(gr, 'time_of_event', mapped.time_of_event);
        setIfPresent(gr, 'resolution_state', mapped.resolution_state);

        if (hasValue(mapped.ci_identifier)) {
            if (gr.isValidField('ci_identifiers')) {
                gr.setValue('ci_identifiers', mapped.ci_identifier);
            } else if (gr.isValidField('ci_identifier')) {
                gr.setValue('ci_identifier', mapped.ci_identifier);
            } else {
                additionalInfo.ci_identifier = mapped.ci_identifier;
            }
        }

        gr.setValue('additional_info', buildAdditionalInfoString(additionalInfo));

        sysId = gr.insert();
        waitDeadlineMs = new Date().getTime() + waitMs;

        result.event_sys_id = sysId;
        result.message_key = mapped.message_key;

        if (waitForAlertRequested) {
            alertGr = waitForAlert(sysId, mapped.message_key, mapped.source, mapped.event_class, waitDeadlineMs, WAIT_ALERT_POLL_MS, debugEnabled, debugSteps);
            if (alertGr) {
                mergeDeep(result, summarizeAlert(alertGr));
            } else {
                result.alert_wait_status = 'timeout';
            }
        }

        if (directToIncidentRequested && dtiWaitForIncident) {
            if (!alertGr) {
                alertGr = waitForAlert(sysId, mapped.message_key, mapped.source, mapped.event_class, waitDeadlineMs, WAIT_ALERT_POLL_MS, debugEnabled, debugSteps);
                if (alertGr) {
                    mergeDeep(result, summarizeAlert(alertGr));
                }
            }

            if (alertGr) {
                existingIncident = waitForIncidentOnAlert(alertGr, waitDeadlineMs, WAIT_ALERT_POLL_MS, debugEnabled, debugSteps);
                if (existingIncident) {
                    mergeDeep(result, summarizeIncident(existingIncident));
                    result.dti_incident_status = 'existing';
                } else if (dtiDecision.allow_incident) {
                    createdIncident = createIncidentFromAlert(alertGr, mapped, additionalInfo, dtiDecision, debugEnabled, debugSteps);
                    if (createdIncident) {
                        mergeDeep(result, summarizeIncident(createdIncident));
                        result.dti_incident_status = 'created';
                    } else {
                        result.dti_incident_status = 'create_failed';
                    }
                } else {
                    result.dti_incident_status = 'suppressed_by_severity_map';
                }
            } else {
                result.dti_incident_status = 'alert_not_found';
            }
        }

        if (debugEnabled) {
            result.debug_steps = debugSteps;
            result.debug_enabled = 'true';
            try {
                gs.info('USBEM debug: ' + JSON.stringify({
                    version: VERSION,
                    event_sys_id: result.event_sys_id,
                    message_key: result.message_key,
                    alert_sys_id: result.alert_sys_id,
                    incident_sys_id: result.incident_sys_id,
                    steps: debugSteps
                }));
            } catch (eLog) {
            }
        }

        result.usbem_processing_ms = String(new Date().getTime() - startedAt);
        return result;
    }

    try {
        var payload = (typeof body === 'string') ? JSON.parse(body) : body;
        var envelope = {};
        var records = [];
        var results = [];
        var i;
        var response;

        if (isArray(payload)) {
            records = payload;
        } else if (isObject(payload) && isArray(payload.records)) {
            envelope = deepClone(payload);
            delete envelope.records;
            records = payload.records;
        } else if (isObject(payload) && isArray(payload.events)) {
            envelope = deepClone(payload);
            delete envelope.events;
            records = payload.events;
        } else {
            records = [payload];
        }

        for (i = 0; i < records.length; i++) {
            results.push(processSingleEvent(records[i], envelope));
        }

        response = {
            status: 'success',
            inserted: String(results.length),
            sys_ids: [],
            results: results,
            version: VERSION
        };

        for (i = 0; i < results.length; i++) {
            response.sys_ids.push(results[i].event_sys_id);
        }

        if (results.length === 1) {
            mergeDeep(response, results[0]);
        }

        return JSON.stringify(response);
    } catch (er) {
        gs.error('TransformEvents_genericMappedJson failed: ' + er);
        if (typeof status !== 'undefined') {
            status = 500;
        }
        return JSON.stringify({
            status: 'error',
            message: String(er),
            version: VERSION
        });
    }
})(request, body);
