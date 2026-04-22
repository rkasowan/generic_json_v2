/* USBEM genericJsonV2 full standalone build: Core + Lookups + Debug + DTI + listener */

if (typeof Class === 'undefined') {
    var Class = {
        create: function () {
            return function () {
                if (typeof this.initialize === 'function') {
                    this.initialize.apply(this, arguments);
                }
            };
        }
    };
}

var USBEM_Core = Class.create();
USBEM_Core.prototype = {
    initialize: function (options) {
        options = options || {};
        this.request = options.request || null;

        this.VERSION = '2026-04-22a';
        this.DEFAULT_SOURCE = 'GenericJSON';
        this.DEFAULT_DESCRIPTION = 'Generic JSON event';
        this.DEFAULT_SEVERITY = '5';
        this.ADDITIONAL_INFO_MAX = 4000;
        this.MESSAGE_KEY_MAX = 1024;
        this.WAIT_ALERT_TIMEOUT_MS = 15000;
        this.WAIT_ALERT_POLL_MS = 500;
        this.MAX_QUERY_ROWS = 250;
        this.NODE_RELATION_MAX_DEPTH = 2;
        this.NODE_RELATION_MAX_NODES = 250;

        this.PROPERTY_DEFAULT_CMDB_CI_SYS_ID = 'x_usbna_usb_event.default_cmdb_ci_sys_id';
        this.PROPERTY_DEFAULT_ASSIGNMENT_GROUP_SYS_ID = 'x_usbna_usb_event.default_assignment_group_sys_id';

        this.DEBUG_EVENT_SOURCE = 'USBEM Debug';
        this.DEBUG_EVENT_CLASS = 'USBEM Request Debug';
        this.DEBUG_EVENT_SEVERITY = '5';
        this.DEBUG_EVENT_STATE = 'Processed';

        this.DTI_SEVERITY_CONFIG = {
            '0': { impact: '4', urgency: '4', allow_incident: false, label: 'Clear' },
            '1': { impact: '2', urgency: '2', allow_incident: true,  label: 'Critical' },
            '2': { impact: '2', urgency: '2', allow_incident: true,  label: 'Major' },
            '3': { impact: '3', urgency: '3', allow_incident: true,  label: 'Minor' },
            '4': { impact: '4', urgency: '4', allow_incident: true,  label: 'Warning' },
            '5': { impact: '4', urgency: '4', allow_incident: false, label: 'OK' }
        };

        this.WRAPPER_KEYS = {
            event: true,
            payload: true,
            data: true,
            record: true,
            alert: true
        };

        this.FIELD_ALIASES = {
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

        this.SPECIAL_ALIASES = {
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
            dti_urgency: ['dti_urgency', 'dtiUrgency'],
            dti_short_description: ['dti_short_description', 'dtiShortDescription'],
            dti_work_note: ['dti_work_note', 'dtiWorkNote']
        };

        this.caches = options.caches || {
            tables: {},
            properties: {},
            ci_types: {},
            groups: {},
            cmdb_by_sysid: {},
            cmdb_by_name: {},
            nodes: {},
            related_nodes: {},
            services: {},
            service_assoc: {},
            offerings: {},
            business_apps: {}
        };
    },

    isObject: function (value) {
        return Object.prototype.toString.call(value) === '[object Object]';
    },

    isArray: function (value) {
        return Object.prototype.toString.call(value) === '[object Array]';
    },

    hasOwn: function (obj, key) {
        return !!obj && Object.prototype.hasOwnProperty.call(obj, key);
    },

    hasValue: function (value) {
        return value !== null && typeof value !== 'undefined' && String(value).replace(/^\s+|\s+$/g, '') !== '';
    },

    trimToString: function (value) {
        return String(value).replace(/^\s+|\s+$/g, '');
    },

    lower: function (value) {
        return this.trimToString(value).toLowerCase();
    },

    normalizeKey: function (value) {
        return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    },

    canonicalUnderscore: function (value) {
        return String(value || '')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_+|_+$/g, '')
            .replace(/_+/g, '_');
    },

    compactAlphaNum: function (value) {
        return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    },

    tokenize: function (value) {
        var tokens = String(value || '').toLowerCase().match(/[a-z0-9]+/g);
        return tokens ? tokens : [];
    },

    truncateString: function (value, maxLen) {
        var text;
        if (!this.hasValue(value)) {
            return '';
        }
        text = String(value);
        if (text.length <= maxLen) {
            return text;
        }
        return text.substring(0, maxLen);
    },

    looksLikeSysId: function (value) {
        return /^[0-9a-fA-F]{32}$/.test(this.trimToString(value));
    },

    parseBoolean: function (value, defaultValue) {
        var n;
        if (typeof value === 'boolean') {
            return value;
        }
        if (!this.hasValue(value)) {
            return defaultValue === true;
        }
        n = this.normalizeKey(value);
        if (n === 'true' || n === '1' || n === 'yes' || n === 'y' || n === 'on') {
            return true;
        }
        if (n === 'false' || n === '0' || n === 'no' || n === 'n' || n === 'off') {
            return false;
        }
        return defaultValue === true;
    },

    toInt: function (value, defaultValue) {
        var n = parseInt(value, 10);
        if (isNaN(n)) {
            return defaultValue;
        }
        return n;
    },

    tryParseJSON: function (text) {
        if (typeof text !== 'string') {
            return null;
        }
        try {
            return JSON.parse(text);
        } catch (e) {
            return null;
        }
    },

    safeJSONStringify: function (value) {
        try {
            return JSON.stringify(value, null, 2);
        } catch (e) {
            try {
                return String(value);
            } catch (e2) {
                return '';
            }
        }
    },

    deepClone: function (value) {
        var out;
        var i;
        var key;
        if (this.isArray(value)) {
            out = [];
            for (i = 0; i < value.length; i++) {
                out.push(this.deepClone(value[i]));
            }
            return out;
        }
        if (this.isObject(value)) {
            out = {};
            for (key in value) {
                if (this.hasOwn(value, key)) {
                    out[key] = this.deepClone(value[key]);
                }
            }
            return out;
        }
        return value;
    },

    mergeDeep: function (target, source) {
        var key;
        if (!this.isObject(target) || !this.isObject(source)) {
            return target;
        }
        for (key in source) {
            if (!this.hasOwn(source, key)) {
                continue;
            }
            if (this.isObject(source[key])) {
                if (!this.isObject(target[key])) {
                    target[key] = {};
                }
                this.mergeDeep(target[key], source[key]);
            } else if (this.isArray(source[key])) {
                target[key] = this.deepClone(source[key]);
            } else {
                target[key] = source[key];
            }
        }
        return target;
    },

    isEmptyObject: function (value) {
        var key;
        if (!this.isObject(value)) {
            return false;
        }
        for (key in value) {
            if (this.hasOwn(value, key)) {
                return false;
            }
        }
        return true;
    },

    normalizeAdditionalInfoValue: function (value) {
        var out;
        var i;
        var key;
        if (value === null || typeof value === 'undefined') {
            return '';
        }
        if (this.isArray(value)) {
            out = [];
            for (i = 0; i < value.length; i++) {
                out.push(this.normalizeAdditionalInfoValue(value[i]));
            }
            return out;
        }
        if (this.isObject(value)) {
            out = {};
            for (key in value) {
                if (this.hasOwn(value, key)) {
                    out[key] = this.normalizeAdditionalInfoValue(value[key]);
                }
            }
            return out;
        }
        return String(value);
    },

    deleteAtPath: function (obj, path) {
        var current = obj;
        var stack = [];
        var i;
        if (!this.isObject(obj) || !this.isArray(path) || path.length === 0) {
            return;
        }
        for (i = 0; i < path.length - 1; i++) {
            if (!this.isObject(current[path[i]])) {
                return;
            }
            stack.push({ parent: current, key: path[i] });
            current = current[path[i]];
        }
        delete current[path[path.length - 1]];
        for (i = stack.length - 1; i >= 0; i--) {
            if (this.isObject(stack[i].parent[stack[i].key]) && this.isEmptyObject(stack[i].parent[stack[i].key])) {
                delete stack[i].parent[stack[i].key];
            }
        }
    },

    extractFirstMatching: function (container, aliases) {
        var i;
        var j;
        var alias;
        var wrapper;
        if (!this.isObject(container)) {
            return null;
        }
        for (i = 0; i < aliases.length; i++) {
            alias = aliases[i];
            if (this.hasOwn(container, alias)) {
                return { value: container[alias], path: [alias], alias: alias };
            }
        }
        for (wrapper in this.WRAPPER_KEYS) {
            if (!this.hasOwn(this.WRAPPER_KEYS, wrapper) || !this.isObject(container[wrapper])) {
                continue;
            }
            for (j = 0; j < aliases.length; j++) {
                alias = aliases[j];
                if (this.hasOwn(container[wrapper], alias)) {
                    return { value: container[wrapper][alias], path: [wrapper, alias], alias: alias };
                }
            }
        }
        return null;
    },

    maybePromoteField: function (container, aliases, targetObj, targetKey) {
        var match;
        if (this.hasValue(targetObj[targetKey])) {
            return;
        }
        match = this.extractFirstMatching(container, aliases);
        if (match) {
            targetObj[targetKey] = match.value;
            this.deleteAtPath(container, match.path);
        }
    },

    mergeAdditionalInfo: function (additionalInfo, rawAdditionalInfo) {
        var parsed;
        if (rawAdditionalInfo === null || typeof rawAdditionalInfo === 'undefined') {
            return;
        }
        if (typeof rawAdditionalInfo === 'string') {
            parsed = this.tryParseJSON(rawAdditionalInfo);
            if (parsed !== null) {
                rawAdditionalInfo = parsed;
            } else {
                additionalInfo.additional_info_text = rawAdditionalInfo;
                return;
            }
        }
        if (this.isObject(rawAdditionalInfo)) {
            this.mergeDeep(additionalInfo, rawAdditionalInfo);
            return;
        }
        if (this.isArray(rawAdditionalInfo)) {
            additionalInfo.additional_info_array = this.deepClone(rawAdditionalInfo);
            return;
        }
        additionalInfo.additional_info_text = String(rawAdditionalInfo);
    },

    normalizeResolutionState: function (raw) {
        var n;
        if (!this.hasValue(raw)) {
            return '';
        }
        n = this.normalizeKey(raw);
        if (n === 'closing' || n === 'close' || n === 'closed' || n === 'resolved' || n === 'clear' || n === 'cleared') {
            return 'Closing';
        }
        if (n === 'new' || n === 'open' || n === 'active' || n === 'fired' || n === 'ok' || n === 'warning' || n === 'minor' || n === 'major' || n === 'critical') {
            return 'New';
        }
        return '';
    },

    normalizeTime: function (raw) {
        var s;
        var gdt;
        if (!this.hasValue(raw)) {
            return '';
        }
        s = this.trimToString(raw);
        if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(s)) {
            return s;
        }
        try {
            gdt = new GlideDateTime(s);
            return gdt.getValue();
        } catch (e) {
            return s;
        }
    },

    mapSeverity: function (raw) {
        var n;
        if (!this.hasValue(raw)) {
            return '';
        }
        raw = this.trimToString(raw);
        if (/^[0-5]$/.test(raw)) {
            return raw;
        }
        n = this.normalizeKey(raw);
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
        return '';
    },

    normalizeMessageKey: function (raw, mapped) {
        var out = this.hasValue(raw) ? this.trimToString(raw) : '';
        if (!this.hasValue(out)) {
            out = [
                this.trimToString(mapped.source),
                this.trimToString(mapped.node),
                this.trimToString(mapped.type),
                this.trimToString(mapped.resource),
                this.trimToString(mapped.metric_name)
            ].join('');
            if (!this.hasValue(out)) {
                out = [
                    this.trimToString(mapped.source),
                    this.trimToString(mapped.event_class),
                    this.trimToString(mapped.description)
                ].join('|');
            }
        }
        return this.truncateString(out, this.MESSAGE_KEY_MAX);
    },

    parseCiIdentifier: function (rawValue) {
        var parsed;
        if (!this.hasValue(rawValue)) {
            return null;
        }
        if (this.isObject(rawValue)) {
            return rawValue;
        }
        if (typeof rawValue === 'string') {
            parsed = this.tryParseJSON(rawValue);
            if (parsed !== null && this.isObject(parsed)) {
                return parsed;
            }
        }
        return null;
    },

    newTrace: function (enabled) {
        return {
            enabled: enabled === true,
            steps: [],
            lookups: {},
            candidates: {},
            notes: [],
            errors: [],
            perf: {
                started_at_ms: new Date().getTime(),
                query_count: 0,
                cache_hits: 0,
                cache_misses: 0
            },
            quality: {}
        };
    },

    tracePush: function (trace, message) {
        if (!trace || trace.enabled !== true || !this.hasValue(message)) {
            return;
        }
        trace.steps.push(String(message));
    },

    traceNote: function (trace, note) {
        if (!trace || trace.enabled !== true || !this.hasValue(note)) {
            return;
        }
        trace.notes.push(String(note));
    },

    traceError: function (trace, label, errorText) {
        if (!trace || trace.enabled !== true) {
            return;
        }
        trace.errors.push({
            label: this.hasValue(label) ? String(label) : 'error',
            error: this.hasValue(errorText) ? String(errorText) : ''
        });
    },

    traceLookup: function (trace, name, resolution) {
        var out;
        if (!trace || trace.enabled !== true || !this.hasValue(name) || !resolution) {
            return;
        }
        out = {
            status: resolution.status || '',
            method: resolution.method || '',
            lookup_table: resolution.lookup_table || '',
            selection_reason: resolution.selection_reason || '',
            count: typeof resolution.count !== 'undefined' ? resolution.count : 0,
            match: resolution.match ? this.normalizeAdditionalInfoValue(resolution.match) : null,
            rows: this.isArray(resolution.rows) ? this.normalizeAdditionalInfoValue(resolution.rows) : []
        };
        trace.lookups[name] = out;
        if (this.isArray(out.rows) && out.rows.length > 0) {
            trace.candidates[name] = out.rows;
        }
    },

    bumpMetric: function (trace, name, amount) {
        if (!trace || !trace.perf) {
            return;
        }
        if (typeof trace.perf[name] === 'undefined') {
            trace.perf[name] = 0;
        }
        trace.perf[name] += (typeof amount === 'number' ? amount : 1);
    },

    tableExists: function (tableName, trace) {
        var gr;
        if (!this.hasValue(tableName)) {
            return false;
        }
        if (typeof this.caches.tables[tableName] !== 'undefined') {
            this.bumpMetric(trace, 'cache_hits', 1);
            return this.caches.tables[tableName];
        }
        this.bumpMetric(trace, 'cache_misses', 1);
        try {
            gr = new GlideRecord(tableName);
            this.caches.tables[tableName] = !!(gr && gr.isValid && gr.isValid());
        } catch (e) {
            this.caches.tables[tableName] = false;
        }
        return this.caches.tables[tableName];
    },

    getProperty: function (name, defaultValue, trace) {
        var value = defaultValue;
        if (!this.hasValue(name)) {
            return defaultValue;
        }
        if (typeof this.caches.properties[name] !== 'undefined') {
            this.bumpMetric(trace, 'cache_hits', 1);
            return this.caches.properties[name];
        }
        this.bumpMetric(trace, 'cache_misses', 1);
        try {
            value = gs.getProperty(name, defaultValue);
        } catch (e) {
            value = defaultValue;
        }
        this.caches.properties[name] = value;
        return value;
    },

    setIfPresent: function (gr, fieldName, value) {
        if (this.hasValue(value) && gr.isValidField(fieldName)) {
            gr.setValue(fieldName, value);
        }
    },

    getFieldText: function (gr, fieldName) {
        if (!gr || !gr.isValidField || !gr.isValidField(fieldName)) {
            return '';
        }
        return gr.getDisplayValue(fieldName) || gr.getValue(fieldName) || '';
    },

    buildResultSkeleton: function () {
        return {
            status: 'success',
            event_sys_id: '',
            message_key: '',
            alert_sys_id: '',
            alert_number: '',
            incident_sys_id: '',
            incident_number: ''
        };
    },

    summarizeAlert: function (alertGr) {
        var out = { alert_sys_id: '', alert_number: '' };
        if (!alertGr) {
            return out;
        }
        out.alert_sys_id = alertGr.getUniqueValue();
        out.alert_number = alertGr.isValidField('number') ? (alertGr.getValue('number') || alertGr.getDisplayValue('number') || '') : '';
        return out;
    },

    summarizeIncident: function (incidentGr) {
        var out = { incident_sys_id: '', incident_number: '' };
        if (!incidentGr) {
            return out;
        }
        out.incident_sys_id = incidentGr.getUniqueValue();
        out.incident_number = incidentGr.isValidField('number') ? (incidentGr.getValue('number') || incidentGr.getDisplayValue('number') || '') : '';
        return out;
    },

    getDtiSeverityConfig: function (severityValue) {
        if (this.hasOwn(this.DTI_SEVERITY_CONFIG, String(severityValue))) {
            return this.DTI_SEVERITY_CONFIG[String(severityValue)];
        }
        return this.DTI_SEVERITY_CONFIG['4'];
    },

    resolveDtiImpactUrgency: function (directToIncidentRequested, dtiWaitForIncident, mappedSeverity, providedImpact, providedUrgency) {
        var config = this.getDtiSeverityConfig(mappedSeverity);
        var impact = this.hasValue(providedImpact) ? this.trimToString(providedImpact) : config.impact;
        var urgency = this.hasValue(providedUrgency) ? this.trimToString(providedUrgency) : config.urgency;
        var allowIncident = config.allow_incident;
        var providedAny = this.hasValue(providedImpact) || this.hasValue(providedUrgency);

        if (providedAny && dtiWaitForIncident) {
            allowIncident = true;
        }

        return {
            impact: String(impact),
            urgency: String(urgency),
            allow_incident: allowIncident,
            provided_any: providedAny,
            impact_source: this.hasValue(providedImpact) ? 'payload' : 'severity_map',
            urgency_source: this.hasValue(providedUrgency) ? 'payload' : 'severity_map',
            severity_policy: config.label
        };
    },

    extractScalarText: function (value) {
        if (!this.hasValue(value)) {
            return '';
        }
        if (this.isObject(value)) {
            if (this.hasValue(value.display_value)) {
                return this.trimToString(value.display_value);
            }
            if (this.hasValue(value.value)) {
                return this.trimToString(value.value);
            }
            return '';
        }
        if (this.isArray(value)) {
            return '';
        }
        return this.trimToString(value);
    },

    findFirstValueByCanonicalKeys: function (container, aliases) {
        var wanted = {};
        var found = '';
        var self = this;
        var i;

        for (i = 0; i < aliases.length; i++) {
            wanted[this.canonicalUnderscore(aliases[i])] = true;
        }

        function walk(value) {
            var key;
            var scalar;
            var parsed;

            if (self.hasValue(found) || value === null || typeof value === 'undefined') {
                return;
            }

            scalar = self.extractScalarText(value);
            if (self.hasValue(scalar) && typeof value !== 'string') {
                return;
            }

            if (typeof value === 'string') {
                parsed = self.tryParseJSON(value);
                if (parsed !== null) {
                    walk(parsed);
                }
                return;
            }

            if (self.isArray(value)) {
                for (i = 0; i < value.length; i++) {
                    walk(value[i]);
                    if (self.hasValue(found)) {
                        return;
                    }
                }
                return;
            }

            if (!self.isObject(value)) {
                return;
            }

            for (key in value) {
                if (!self.hasOwn(value, key)) {
                    continue;
                }
                if (wanted[self.canonicalUnderscore(key)]) {
                    scalar = self.extractScalarText(value[key]);
                    if (self.hasValue(scalar)) {
                        found = scalar;
                        return;
                    }
                }
                walk(value[key]);
                if (self.hasValue(found)) {
                    return;
                }
            }
        }

        walk(container);
        return found;
    },

    normalizeSalesforceCaseStatus: function (statusText) {
        var normalized = this.normalizeKey(statusText);
        if (!this.hasValue(normalized)) {
            return '';
        }
        if (normalized === 'closed' || normalized === 'close' || normalized === 'resolved' || normalized === 'cleared' || normalized === 'clear') {
            return 'closed';
        }
        return 'open';
    },

    inferSalesforceCaseSeverity: function (caseStatus, caseSubject, impactedCount) {
        var statusBucket = this.normalizeSalesforceCaseStatus(caseStatus);
        var subject = this.lower(caseSubject);
        var impacted = parseInt(impactedCount, 10);

        if (statusBucket === 'closed') {
            return '0';
        }
        if (
            /(^|[^a-z0-9])(down|outage|critical|sev1|sev2|major|unavailable)([^a-z0-9]|$)/.test(subject) ||
            (!isNaN(impacted) && impacted >= 5)
        ) {
            return '2';
        }
        if (!isNaN(impacted) && impacted > 0) {
            return '3';
        }
        return '3';
    },

    applySalesforcePeruDefaults: function (ctx) {
        var payload = ctx.user_additional_info;
        var caseNumber;
        var caseSubject;
        var caseStatus;
        var createdDate;
        var impactedCount;
        var primaryOffering;
        var secondaryOffering;

        if (!this.isObject(payload)) {
            return false;
        }

        caseNumber = this.findFirstValueByCanonicalKeys(payload, ['case_number', 'case number', 'casenumber', 'external_case_id', 'salesforce_case_id', 'sf_case_number']);
        caseSubject = this.findFirstValueByCanonicalKeys(payload, ['case_subject', 'case subject', 'casesubject', 'subject', 'salesforce_case_subject', 'sf_case_subject']);
        caseStatus = this.findFirstValueByCanonicalKeys(payload, ['case_status', 'case status', 'casestatus', 'status', 'salesforce_case_status', 'sf_case_status']);
        createdDate = this.findFirstValueByCanonicalKeys(payload, ['case_created_date', 'case created_date', 'created_date', 'case_opened_date']);
        impactedCount = this.findFirstValueByCanonicalKeys(payload, ['number_of_customers_impacted', 'number of customers impacted', 'customers_impacted', 'customer_count']);
        primaryOffering = this.findFirstValueByCanonicalKeys(payload, ['primary_offering', 'primary offering', 'primary_service_offering', 'service_offering_primary']);
        secondaryOffering = this.findFirstValueByCanonicalKeys(payload, ['secondary_offering', 'secondary offering', 'secondary_service_offering', 'service_offering_secondary']);

        if (!this.hasValue(caseNumber) || (!this.hasValue(caseSubject) && !this.hasValue(caseStatus))) {
            return false;
        }

        if (!this.hasValue(ctx.mapped.source)) {
            ctx.mapped.source = 'salesforce';
        }
        if (!this.hasValue(ctx.mapped.event_class)) {
            ctx.mapped.event_class = 'salesforce';
        }
        if (!this.hasValue(ctx.mapped.type)) {
            ctx.mapped.type = 'peru';
        }
        if (!this.hasValue(ctx.mapped.resource)) {
            ctx.mapped.resource = caseNumber;
        }
        if (!this.hasValue(ctx.mapped.metric_name)) {
            ctx.mapped.metric_name = 'salesforce_case';
        }
        if (!this.hasValue(ctx.mapped.description)) {
            ctx.mapped.description = this.hasValue(caseSubject) ? caseSubject : ('Salesforce case ' + caseNumber);
        }
        if (!this.hasValue(ctx.mapped.message_key)) {
            ctx.mapped.message_key = caseNumber;
        }
        if (!this.hasValue(ctx.mapped.time_of_event) && this.hasValue(createdDate)) {
            ctx.mapped.time_of_event = createdDate;
        }
        if (!this.hasValue(ctx.mapped.resolution_state)) {
            ctx.mapped.resolution_state = this.normalizeSalesforceCaseStatus(caseStatus) === 'closed' ? 'Closing' : 'New';
        }
        if (!this.hasValue(ctx.mapped.severity)) {
            ctx.mapped.severity = this.inferSalesforceCaseSeverity(caseStatus, caseSubject, impactedCount);
        }
        if (!this.hasValue(ctx.special.usbem_offering)) {
            if (this.hasValue(primaryOffering)) {
                ctx.special.usbem_offering = primaryOffering;
            } else if (this.hasValue(secondaryOffering)) {
                ctx.special.usbem_offering = secondaryOffering;
            }
        }

        this.tracePush(ctx.debug, 'applied Salesforce PERU defaults from flat case payload');
        return true;
    },

    createRecordContext: function (rawEvent, envelope) {
        var ctx = {
            started_at_ms: new Date().getTime(),
            raw_event: this.deepClone(rawEvent),
            envelope: this.deepClone(envelope || {}),
            working: {},
            raw_additional_info: null,
            mapped: {},
            special: {},
            user_additional_info: {},
            remaining: {},
            result: this.buildResultSkeleton(),
            flags: {},
            dti: {},
            ci_identifier_obj: null,
            ci_type_resolution: null,
            debug: null,
            resolved: {
                cmdb_ci_sys_id: '',
                assignment_group_sys_id: '',
                cmdb_ci_service: '',
                cmdb_ci_service_offering: '',
                cmdb_ci_business_app: '',
                support_group_sys_id: '',
                dummy_ci_used: false,
                dummy_assignment_group_used: false
            },
            attempts: {
                ci: false,
                assignment_group: false
            },
            snapshots: {},
            quality: {}
        };
        var fieldName;

        if (this.isObject(rawEvent)) {
            ctx.working = this.deepClone(ctx.envelope);
            this.mergeDeep(ctx.working, rawEvent);
        } else {
            ctx.working = this.deepClone(ctx.envelope);
            ctx.working.description = String(rawEvent);
        }

        if (this.hasOwn(ctx.working, 'additional_info')) {
            ctx.raw_additional_info = ctx.working.additional_info;
            delete ctx.working.additional_info;
        } else if (this.hasOwn(ctx.working, 'additionalInfo')) {
            ctx.raw_additional_info = ctx.working.additionalInfo;
            delete ctx.working.additionalInfo;
        }

        ctx.remaining = this.deepClone(ctx.working);

        for (fieldName in this.FIELD_ALIASES) {
            if (this.hasOwn(this.FIELD_ALIASES, fieldName)) {
                this.maybePromoteField(ctx.remaining, this.FIELD_ALIASES[fieldName], ctx.mapped, fieldName);
            }
        }

        for (fieldName in this.SPECIAL_ALIASES) {
            if (this.hasOwn(this.SPECIAL_ALIASES, fieldName)) {
                this.maybePromoteField(ctx.remaining, this.SPECIAL_ALIASES[fieldName], ctx.special, fieldName);
            }
        }

        this.mergeAdditionalInfo(ctx.user_additional_info, ctx.raw_additional_info);

        for (fieldName in this.FIELD_ALIASES) {
            if (this.hasOwn(this.FIELD_ALIASES, fieldName)) {
                this.maybePromoteField(ctx.user_additional_info, this.FIELD_ALIASES[fieldName], ctx.mapped, fieldName);
            }
        }

        for (fieldName in this.SPECIAL_ALIASES) {
            if (this.hasOwn(this.SPECIAL_ALIASES, fieldName)) {
                this.maybePromoteField(ctx.user_additional_info, this.SPECIAL_ALIASES[fieldName], ctx.special, fieldName);
            }
        }

        this.mergeDeep(ctx.user_additional_info, ctx.remaining);

        ctx.flags.debug_enabled = this.parseBoolean(ctx.special.usbem_debug, false);
        ctx.debug = this.newTrace(ctx.flags.debug_enabled);
        this.tracePush(ctx.debug, 'USBEM version ' + this.VERSION);

        this.applySalesforcePeruDefaults(ctx);

        if (this.hasValue(ctx.mapped.time_of_event)) {
            ctx.mapped.time_of_event = this.normalizeTime(ctx.mapped.time_of_event);
        }
        if (this.hasValue(ctx.mapped.resolution_state)) {
            ctx.mapped.resolution_state = this.normalizeResolutionState(ctx.mapped.resolution_state);
        }

        ctx.mapped.severity = this.mapSeverity(ctx.mapped.severity);
        if (!this.hasValue(ctx.mapped.severity)) {
            ctx.mapped.severity = this.DEFAULT_SEVERITY;
        }
        if (!this.hasValue(ctx.mapped.source)) {
            ctx.mapped.source = this.DEFAULT_SOURCE;
        }
        if (!this.hasValue(ctx.mapped.event_class)) {
            ctx.mapped.event_class = ctx.mapped.source;
        }
        if (!this.hasValue(ctx.mapped.description)) {
            ctx.mapped.description = this.DEFAULT_DESCRIPTION;
        }

        ctx.mapped.message_key = this.normalizeMessageKey(ctx.mapped.message_key, ctx.mapped);

        ctx.ci_identifier_obj = this.parseCiIdentifier(ctx.mapped.ci_identifier);
        if (ctx.ci_identifier_obj) {
            ctx.mapped.ci_identifier = this.safeJSONStringify(ctx.ci_identifier_obj);
        }

        ctx.flags.direct_to_incident = this.parseBoolean(ctx.special.direct_to_incident, false);
        ctx.flags.dti_wait_for_incident = this.parseBoolean(ctx.special.dti_wait_for_incident, false);
        ctx.flags.usbem_wait_for_alert = this.parseBoolean(ctx.special.usbem_wait_for_alert, false);
        ctx.flags.wait_requested = ctx.flags.usbem_wait_for_alert || (ctx.flags.direct_to_incident && ctx.flags.dti_wait_for_incident);
        ctx.flags.wait_seconds = this.toInt(ctx.special.usbem_wait_seconds, 0);
        if (ctx.flags.wait_seconds <= 0) {
            ctx.flags.wait_seconds = Math.floor(this.WAIT_ALERT_TIMEOUT_MS / 1000);
        }
        ctx.flags.wait_ms = ctx.flags.wait_seconds * 1000;

        if (ctx.flags.direct_to_incident && !this.hasValue(ctx.special.dti_short_description)) {
            ctx.special.dti_short_description = ctx.mapped.description;
        }

        ctx.dti = this.resolveDtiImpactUrgency(
            ctx.flags.direct_to_incident,
            ctx.flags.dti_wait_for_incident,
            ctx.mapped.severity,
            ctx.special.dti_impact,
            ctx.special.dti_urgency
        );

        ctx.quality = this.buildPayloadQuality(ctx);
        ctx.debug.quality = this.deepClone(ctx.quality);
        ctx.snapshots.normalized_input = this.buildNormalizedInputSnapshot(ctx);
        return ctx;
    },

    buildNormalizedInputSnapshot: function (ctx) {
        return {
            mapped: this.deepClone(ctx.mapped),
            special: this.deepClone(ctx.special),
            user_additional_info: this.deepClone(ctx.user_additional_info),
            flags: this.deepClone(ctx.flags),
            ci_identifier_obj: this.deepClone(ctx.ci_identifier_obj)
        };
    },

    buildMappedEventSnapshot: function (ctx, finalAdditionalInfo) {
        return {
            source: ctx.mapped.source || '',
            event_class: ctx.mapped.event_class || '',
            node: ctx.mapped.node || '',
            resource: ctx.mapped.resource || '',
            metric_name: ctx.mapped.metric_name || '',
            type: ctx.mapped.type || '',
            message_key: ctx.mapped.message_key || '',
            ci_type: ctx.mapped.ci_type || '',
            ci_identifier: ctx.mapped.ci_identifier || '',
            cmdb_ci: ctx.mapped.cmdb_ci || '',
            service: ctx.mapped.service || '',
            service_offering: ctx.mapped.service_offering || '',
            severity: ctx.mapped.severity || '',
            description: ctx.mapped.description || '',
            time_of_event: ctx.mapped.time_of_event || '',
            resolution_state: ctx.mapped.resolution_state || '',
            additional_info: this.deepClone(finalAdditionalInfo || {})
        };
    },

    buildPayloadQuality: function (ctx) {
        var countKeys = function (obj, self) {
            var count = 0;
            var key;
            if (!self.isObject(obj)) {
                return 0;
            }
            for (key in obj) {
                if (self.hasOwn(obj, key)) {
                    count++;
                }
            }
            return count;
        };
        return {
            mapped_key_count: countKeys(ctx.mapped, this),
            special_key_count: countKeys(ctx.special, this),
            user_additional_info_key_count: countKeys(ctx.user_additional_info, this),
            direct_to_incident: ctx.flags.direct_to_incident === true,
            wait_requested: ctx.flags.wait_requested === true
        };
    },

    getDefaultCmdbCiSysId: function (trace) {
        return this.trimToString(this.getProperty(this.PROPERTY_DEFAULT_CMDB_CI_SYS_ID, '', trace));
    },

    getDefaultAssignmentGroupSysId: function (trace) {
        return this.trimToString(this.getProperty(this.PROPERTY_DEFAULT_ASSIGNMENT_GROUP_SYS_ID, '', trace));
    },

    shouldUseDummyCi: function (ctx) {
        return this.hasValue(ctx.mapped.node) ||
            this.hasValue(ctx.mapped.resource) ||
            this.hasValue(ctx.mapped.cmdb_ci) ||
            this.hasValue(ctx.mapped.ci_type) ||
            this.hasValue(ctx.mapped.ci_identifier) ||
            (this.isObject(ctx.user_additional_info) && this.hasValue(ctx.user_additional_info.name));
    },

    addOperationalAdditionalInfo: function (ctx) {
        var ai = this.deepClone(ctx.user_additional_info);

        if (this.hasValue(ctx.resolved.cmdb_ci_sys_id)) {
            ai.cmdb_ci = ctx.resolved.cmdb_ci_sys_id;
        }
        if (this.hasValue(ctx.resolved.assignment_group_sys_id)) {
            ai.assignment_group = ctx.resolved.assignment_group_sys_id;
        }
        if (this.hasValue(ctx.resolved.cmdb_ci_business_app)) {
            ai.cmdb_ci_business_app = ctx.resolved.cmdb_ci_business_app;
        }
        if (this.hasValue(ctx.resolved.cmdb_ci_service)) {
            ai.cmdb_ci_service = ctx.resolved.cmdb_ci_service;
        }
        if (this.hasValue(ctx.resolved.cmdb_ci_service_offering)) {
            ai.cmdb_ci_service_offering = ctx.resolved.cmdb_ci_service_offering;
        }

        if (ctx.flags.direct_to_incident) {
            ai.direct_to_incident = 'true';
            ai.dti_short_description = this.hasValue(ctx.special.dti_short_description) ? String(ctx.special.dti_short_description) : ctx.mapped.description;
            ai.dti_impact = String(ctx.dti.impact);
            ai.dti_urgency = String(ctx.dti.urgency);
            if (this.hasValue(ctx.special.dti_work_note)) {
                ai.dti_work_note = String(ctx.special.dti_work_note);
            }
            if (ctx.flags.dti_wait_for_incident) {
                ai.dti_wait_for_incident = 'true';
            }
        }

        if (ctx.flags.usbem_wait_for_alert) {
            ai.usbem_wait_for_alert = 'true';
        }

        return ai;
    },

    priorityForAdditionalInfoKey: function (key) {
        if (key === 'cmdb_ci') return 0;
        if (key === 'assignment_group') return 1;
        if (key === 'cmdb_ci_business_app') return 2;
        if (key === 'cmdb_ci_service') return 3;
        if (key === 'cmdb_ci_service_offering') return 4;
        if (key === 'direct_to_incident') return 5;
        if (key === 'dti_short_description') return 6;
        if (key === 'dti_impact') return 7;
        if (key === 'dti_urgency') return 8;
        if (key === 'dti_work_note') return 9;
        if (key === 'dti_wait_for_incident') return 10;
        if (key === 'usbem_wait_for_alert') return 11;
        return 50;
    },

    buildAdditionalInfoString: function (additionalInfo) {
        var full = this.safeJSONStringify(additionalInfo);
        var reduced = {};
        var keys = [];
        var k;
        var i;
        if (full.length <= this.ADDITIONAL_INFO_MAX) {
            return full;
        }
        for (k in additionalInfo) {
            if (this.hasOwn(additionalInfo, k)) {
                keys.push(k);
            }
        }
        keys.sort((function (self) {
            return function (a, b) {
                var pa = self.priorityForAdditionalInfoKey(a);
                var pb = self.priorityForAdditionalInfoKey(b);
                if (pa !== pb) {
                    return pa - pb;
                }
                return a < b ? -1 : (a > b ? 1 : 0);
            };
        })(this));

        for (i = 0; i < keys.length; i++) {
            reduced[keys[i]] = additionalInfo[keys[i]];
            if (this.safeJSONStringify(reduced).length > this.ADDITIONAL_INFO_MAX) {
                delete reduced[keys[i]];
            }
        }
        return this.safeJSONStringify(reduced);
    },

    insertEventRecord: function (ctx, finalAdditionalInfo) {
        var gr = new GlideRecord('em_event');
        var sysId;
        gr.initialize();

        this.setIfPresent(gr, 'source', this.truncateString(ctx.mapped.source, 200));
        this.setIfPresent(gr, 'event_class', this.truncateString(ctx.mapped.event_class, 200));
        this.setIfPresent(gr, 'node', this.truncateString(ctx.mapped.node, 200));
        this.setIfPresent(gr, 'resource', this.truncateString(ctx.mapped.resource, 200));
        this.setIfPresent(gr, 'metric_name', ctx.mapped.metric_name);
        this.setIfPresent(gr, 'type', this.truncateString(ctx.mapped.type, 200));
        this.setIfPresent(gr, 'message_key', ctx.mapped.message_key);
        this.setIfPresent(gr, 'ci_type', ctx.mapped.ci_type);
        this.setIfPresent(gr, 'cmdb_ci', ctx.mapped.cmdb_ci);
        this.setIfPresent(gr, 'service', ctx.mapped.service);
        this.setIfPresent(gr, 'service_offering', ctx.mapped.service_offering);
        this.setIfPresent(gr, 'severity', ctx.mapped.severity);
        this.setIfPresent(gr, 'description', this.truncateString(ctx.mapped.description, 4000));
        this.setIfPresent(gr, 'time_of_event', ctx.mapped.time_of_event);
        this.setIfPresent(gr, 'resolution_state', ctx.mapped.resolution_state);

        if (this.hasValue(ctx.mapped.ci_identifier)) {
            if (gr.isValidField('ci_identifiers')) {
                gr.setValue('ci_identifiers', ctx.mapped.ci_identifier);
            } else if (gr.isValidField('ci_identifier')) {
                gr.setValue('ci_identifier', ctx.mapped.ci_identifier);
            } else {
                finalAdditionalInfo.ci_identifier = ctx.ci_identifier_obj ? this.deepClone(ctx.ci_identifier_obj) : ctx.mapped.ci_identifier;
            }
        }

        gr.setValue('additional_info', this.buildAdditionalInfoString(finalAdditionalInfo));
        sysId = gr.insert();
        ctx.result.event_sys_id = sysId;
        ctx.result.message_key = ctx.mapped.message_key;
        return sysId;
    },

    finalizeContext: function (ctx, finalAdditionalInfo) {
        ctx.snapshots.final_event = this.buildMappedEventSnapshot(ctx, finalAdditionalInfo);
        ctx.result.usbem_processing_ms = String(new Date().getTime() - ctx.started_at_ms);
    },

    anyDebugEnabled: function (results) {
        var i;
        if (!this.isArray(results)) {
            return false;
        }
        for (i = 0; i < results.length; i++) {
            if (results[i] && results[i].debug_enabled === 'true') {
                return true;
            }
        }
        return false;
    },

    rawPayloadLooksDebugEnabled: function (rawPayloadText) {
        if (!this.hasValue(rawPayloadText)) {
            return false;
        }
        return /["']usbem_debug["']\s*:\s*(true|["']true["']|1|["']1["'])/i.test(String(rawPayloadText));
    },

    type: 'USBEM_Core'
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = USBEM_Core;
}

if (typeof Class === 'undefined') {
    var Class = {
        create: function () {
            return function () {
                if (typeof this.initialize === 'function') {
                    this.initialize.apply(this, arguments);
                }
            };
        }
    };
}

var USBEM_Lookups = Class.create();
USBEM_Lookups.prototype = {
    initialize: function (core) {
        this.core = core;
    },

    queryNow: function (gr, trace) {
        this.core.bumpMetric(trace, 'query_count', 1);
        gr.query();
    },

    getQueryField: function (gr, candidates) {
        var i;
        for (i = 0; i < candidates.length; i++) {
            if (gr.isValidField(candidates[i])) {
                return candidates[i];
            }
        }
        return '';
    },

    getActiveBonus: function (gr) {
        if (!gr || !gr.isValidField || !gr.isValidField('active')) {
            return 0;
        }
        return String(gr.getValue('active')) === 'true' ? 3 : 0;
    },

    getStatusReasonList: function (gr) {
        var reasons = [];
        var operational;
        var install;
        var lifecycle;

        if (!gr || !gr.isValidField) {
            return reasons;
        }

        if (gr.isValidField('operational_status')) {
            operational = this.core.normalizeKey(this.core.getFieldText(gr, 'operational_status'));
            if (operational.indexOf('operational') > -1 || operational.indexOf('up') > -1 || operational.indexOf('active') > -1) {
                reasons.push('operational');
            }
            if (operational.indexOf('nonoperational') > -1 || operational.indexOf('down') > -1 || operational.indexOf('retired') > -1) {
                reasons.push('non_operational');
            }
        }

        if (gr.isValidField('install_status')) {
            install = this.core.normalizeKey(this.core.getFieldText(gr, 'install_status'));
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
            lifecycle = this.core.normalizeKey(this.core.getFieldText(gr, 'life_cycle_stage_status'));
            if (lifecycle.indexOf('production') > -1) {
                reasons.push('life_cycle_production');
            }
        }

        if (gr.isValidField('active') && String(gr.getValue('active')) === 'true') {
            reasons.push('active');
        }

        return reasons;
    },

    getStatusScore: function (gr) {
        var score = 0;
        var operational;
        var install;
        var lifecycle;

        if (!gr || !gr.isValidField) {
            return score;
        }

        if (gr.isValidField('operational_status')) {
            operational = this.core.normalizeKey(this.core.getFieldText(gr, 'operational_status'));
            if (operational.indexOf('operational') > -1 || operational.indexOf('up') > -1 || operational.indexOf('active') > -1) {
                score += 20;
            }
            if (operational.indexOf('nonoperational') > -1 || operational.indexOf('down') > -1 || operational.indexOf('retired') > -1) {
                score -= 10;
            }
        }

        if (gr.isValidField('install_status')) {
            install = this.core.normalizeKey(this.core.getFieldText(gr, 'install_status'));
            if (install.indexOf('inproduction') > -1 || install.indexOf('production') > -1 || install.indexOf('installed') > -1 || install.indexOf('inuse') > -1) {
                score += 10;
            }
            if (install.indexOf('retired') > -1 || install.indexOf('absent') > -1) {
                score -= 5;
            }
        }

        if (gr.isValidField('life_cycle_stage_status')) {
            lifecycle = this.core.normalizeKey(this.core.getFieldText(gr, 'life_cycle_stage_status'));
            if (lifecycle.indexOf('production') > -1) {
                score += 5;
            }
        }

        score += this.getActiveBonus(gr);
        return score;
    },

    getCmdbCiClassPreference: function (sysClassName) {
        var normalized = this.core.canonicalUnderscore(sysClassName);

        if (!this.core.hasValue(normalized)) {
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
    },

    getCmdbCiLookupExtraScore: function (ciGr, row, canonicalTarget, compactTarget) {
        var candidateName = row && this.core.hasValue(row.name) ? row.name : this.core.getFieldText(ciGr, 'name');
        var extra = this.getCmdbCiClassPreference(row && row.sys_class_name ? row.sys_class_name : (ciGr.isValidField('sys_class_name') ? ciGr.getValue('sys_class_name') : ''));

        if (!this.core.isObject(extra)) {
            extra = { score: 0, reasons: [] };
        }
        if (!this.core.isArray(extra.reasons)) {
            extra.reasons = [];
        }
        if (this.core.hasValue(canonicalTarget) && this.core.canonicalUnderscore(candidateName) === canonicalTarget) {
            extra.score += 100;
            extra.reasons.push('canonical_name');
        }
        if (this.core.hasValue(compactTarget) && this.core.compactAlphaNum(candidateName) === compactTarget) {
            extra.score += 100;
            extra.reasons.push('compact_name');
        }

        return extra;
    },

    buildMatchRowFromRecord: function (gr, nameField, extraScoreFn) {
        var row;
        var extra;

        if (!gr) {
            return null;
        }

        row = {
            sys_id: gr.getUniqueValue(),
            name: gr.isValidField(nameField || 'name') ? gr.getDisplayValue(nameField || 'name') : gr.getDisplayValue(),
            number: gr.isValidField('number') ? gr.getDisplayValue('number') : '',
            sys_class_name: gr.isValidField('sys_class_name') ? gr.getValue('sys_class_name') : '',
            category: gr.isValidField('category') ? gr.getDisplayValue('category') : '',
            operational_status: gr.isValidField('operational_status') ? gr.getDisplayValue('operational_status') : '',
            install_status: gr.isValidField('install_status') ? gr.getDisplayValue('install_status') : '',
            life_cycle_stage_status: gr.isValidField('life_cycle_stage_status') ? gr.getDisplayValue('life_cycle_stage_status') : '',
            active: gr.isValidField('active') ? gr.getValue('active') : '',
            score: this.getStatusScore(gr),
            score_reasons: this.getStatusReasonList(gr),
            display: gr.getDisplayValue()
        };

        if (typeof extraScoreFn === 'function') {
            extra = extraScoreFn(gr, row);
            if (typeof extra === 'number') {
                row.score += extra;
            } else if (this.core.isObject(extra)) {
                if (typeof extra.score !== 'undefined') {
                    row.score += this.core.toInt(extra.score, 0);
                }
                if (this.core.isArray(extra.reasons)) {
                    row.score_reasons = row.score_reasons.concat(extra.reasons);
                }
                if (typeof extra.depth !== 'undefined') {
                    row.relation_depth = extra.depth;
                }
            }
        }

        return row;
    },

    collectMatches: function (gr, nameField, extraScoreFn) {
        var out = [];
        var row;
        while (gr.next()) {
            row = this.buildMatchRowFromRecord(gr, nameField, extraScoreFn);
            if (row) {
                out.push(row);
            }
        }
        return out;
    },

    sortMatches: function (rows) {
        rows.sort(function (a, b) {
            var aDepth = typeof a.relation_depth === 'number' ? a.relation_depth : 999;
            var bDepth = typeof b.relation_depth === 'number' ? b.relation_depth : 999;
            if (b.score !== a.score) {
                return b.score - a.score;
            }
            if (aDepth !== bDepth) {
                return aDepth - bDepth;
            }
            return String(a.sys_id).localeCompare(String(b.sys_id));
        });
        return rows;
    },

    chooseBestMatch: function (rows, strictAmbiguity) {
        var sorted = this.sortMatches(rows || []);
        var top;
        var second;

        if (!sorted.length) {
            return { match: null, count: 0, rows: [], ambiguous: false, selection_reason: 'no_match' };
        }

        top = sorted[0];
        second = sorted.length > 1 ? sorted[1] : null;

        if (strictAmbiguity && second && second.score === top.score) {
            return {
                match: null,
                count: sorted.length,
                rows: sorted,
                ambiguous: true,
                selection_reason: 'top_score_tie'
            };
        }

        return {
            match: top,
            count: sorted.length,
            rows: sorted,
            ambiguous: false,
            selection_reason: top.score_reasons && top.score_reasons.length ? top.score_reasons[0] : 'best_score'
        };
    },

    mergeCandidateRow: function (rows, bySysId, row) {
        var existing;
        var i;
        var seen = {};
        var merged = [];

        if (!row || !this.core.hasValue(row.sys_id)) {
            return;
        }

        existing = bySysId[row.sys_id];
        if (!existing) {
            bySysId[row.sys_id] = row;
            rows.push(row);
            return;
        }

        if (row.score > existing.score) {
            existing.score = row.score;
            existing.name = row.name || existing.name;
            existing.display = row.display || existing.display;
            existing.sys_class_name = row.sys_class_name || existing.sys_class_name;
            existing.category = row.category || existing.category;
            existing.operational_status = row.operational_status || existing.operational_status;
            existing.install_status = row.install_status || existing.install_status;
            existing.life_cycle_stage_status = row.life_cycle_stage_status || existing.life_cycle_stage_status;
            existing.active = row.active || existing.active;
        }
        if (typeof row.relation_depth === 'number' && (typeof existing.relation_depth === 'undefined' || row.relation_depth < existing.relation_depth)) {
            existing.relation_depth = row.relation_depth;
        }

        for (i = 0; i < existing.score_reasons.length; i++) {
            if (!seen[existing.score_reasons[i]]) {
                seen[existing.score_reasons[i]] = true;
                merged.push(existing.score_reasons[i]);
            }
        }
        for (i = 0; i < row.score_reasons.length; i++) {
            if (!seen[row.score_reasons[i]]) {
                seen[row.score_reasons[i]] = true;
                merged.push(row.score_reasons[i]);
            }
        }
        existing.score_reasons = merged;
    },

    queryExactByName: function (tableName, nameField, nameValue, preQueryFn, extraScoreFn, strictAmbiguity, trace) {
        var rows = [];
        var gr;
        var chosen;
        if (!this.core.hasValue(nameValue) || !this.core.tableExists(tableName, trace)) {
            return { match: null, count: 0, rows: [], ambiguous: false, selection_reason: 'no_match' };
        }
        gr = new GlideRecord(tableName);
        if (!gr.isValidField(nameField || 'name')) {
            return { match: null, count: 0, rows: [], ambiguous: false, selection_reason: 'name_field_missing' };
        }
        if (typeof preQueryFn === 'function') {
            preQueryFn(gr);
        }
        gr.addQuery(nameField || 'name', this.core.trimToString(nameValue));
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);
        rows = this.collectMatches(gr, nameField, extraScoreFn);
        chosen = this.chooseBestMatch(rows, strictAmbiguity === true);
        return chosen;
    },

    buildCiTypeRow: function (gr, score, reasons) {
        var tableName = gr.isValidField('name') ? gr.getValue('name') : '';
        var label = gr.isValidField('label') ? this.core.getFieldText(gr, 'label') : '';
        return {
            sys_id: gr.getUniqueValue(),
            name: tableName,
            label: label,
            table_name: tableName,
            display: label || tableName,
            score: score || 0,
            score_reasons: reasons || []
        };
    },

    resolveCiTypeTable: function (rawValue, trace) {
        var input = this.core.trimToString(rawValue);
        var cacheKey = 'ci_type|' + input;
        var resolution = {
            table_name: '',
            label: '',
            status: 'not_attempted',
            method: '',
            count: 0,
            rows: [],
            selection_reason: ''
        };
        var gr;
        var row;
        var rows;
        var chosen;
        var name;
        var label;
        var tokens;
        var compactTarget;
        var canonicalTarget;
        var combined;
        var score;
        var reasons;
        var i;
        var allTokensPresent;

        if (!this.core.hasValue(input)) {
            resolution.status = 'empty';
            resolution.method = 'empty';
            return resolution;
        }

        if (typeof this.core.caches.ci_types[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.ci_types[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        if (this.core.looksLikeSysId(input) && this.core.tableExists('sys_db_object', trace)) {
            gr = new GlideRecord('sys_db_object');
            if (gr.get(input)) {
                name = gr.isValidField('name') ? gr.getValue('name') : '';
                label = gr.isValidField('label') ? this.core.getFieldText(gr, 'label') : '';
                if (this.core.hasValue(name) && this.core.tableExists(name, trace)) {
                    row = this.buildCiTypeRow(gr, 999, ['provided_sys_db_object_sys_id']);
                    resolution.table_name = name;
                    resolution.label = label;
                    resolution.status = 'matched';
                    resolution.method = 'sys_db_object_sys_id';
                    resolution.count = 1;
                    resolution.rows = [row];
                    resolution.match = row;
                    resolution.lookup_table = name;
                    resolution.selection_reason = 'provided_sys_db_object_sys_id';
                    this.core.caches.ci_types[cacheKey] = this.core.deepClone(resolution);
                    return resolution;
                }
            }
        }

        if (this.core.tableExists(input, trace)) {
            resolution.table_name = input;
            resolution.status = 'matched';
            resolution.method = 'provided_table_name';
            resolution.count = 1;
            resolution.lookup_table = input;
            resolution.selection_reason = 'provided_table_name';
            if (this.core.tableExists('sys_db_object', trace)) {
                gr = new GlideRecord('sys_db_object');
                if (gr.isValidField('name')) {
                    gr.addQuery('name', input);
                    gr.setLimit(1);
                    this.queryNow(gr, trace);
                    if (gr.next()) {
                        label = gr.isValidField('label') ? this.core.getFieldText(gr, 'label') : '';
                        row = this.buildCiTypeRow(gr, 999, ['provided_table_name']);
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
                    score_reasons: ['provided_table_name']
                };
                resolution.rows = [resolution.match];
            }
            this.core.caches.ci_types[cacheKey] = this.core.deepClone(resolution);
            return resolution;
        }

        if (!this.core.tableExists('sys_db_object', trace)) {
            resolution.status = 'lookup_unavailable';
            resolution.method = 'sys_db_object_missing';
            resolution.selection_reason = 'sys_db_object_missing';
            return resolution;
        }

        gr = new GlideRecord('sys_db_object');
        if (gr.isValidField('label')) {
            gr.addQuery('label', input);
            gr.setLimit(this.core.MAX_QUERY_ROWS);
            this.queryNow(gr, trace);
            rows = [];
            while (gr.next()) {
                name = gr.isValidField('name') ? gr.getValue('name') : '';
                if (!this.core.hasValue(name) || !this.core.tableExists(name, trace)) {
                    continue;
                }
                rows.push(this.buildCiTypeRow(gr, 300, ['exact_label']));
            }
            chosen = this.chooseBestMatch(rows, true);
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
                this.core.caches.ci_types[cacheKey] = this.core.deepClone(resolution);
                return resolution;
            }
        }

        tokens = this.core.tokenize(input);
        if (tokens.length === 0) {
            resolution.status = 'not_found';
            resolution.method = 'token_search';
            resolution.selection_reason = 'no_tokens';
            return resolution;
        }

        compactTarget = this.core.compactAlphaNum(input);
        canonicalTarget = this.core.canonicalUnderscore(input);

        gr = new GlideRecord('sys_db_object');
        if (gr.isValidField('name') && gr.isValidField('label')) {
            gr.addEncodedQuery('nameLIKE' + tokens[0] + '^ORlabelLIKE' + tokens[0]);
        } else if (gr.isValidField('label')) {
            gr.addQuery('label', 'CONTAINS', tokens[0]);
        } else if (gr.isValidField('name')) {
            gr.addQuery('name', 'CONTAINS', tokens[0]);
        }
        gr.setLimit(this.core.MAX_QUERY_ROWS * 4);
        this.queryNow(gr, trace);

        rows = [];
        while (gr.next()) {
            name = gr.isValidField('name') ? gr.getValue('name') : '';
            label = gr.isValidField('label') ? this.core.getFieldText(gr, 'label') : '';

            if (!this.core.hasValue(name) || !this.core.tableExists(name, trace)) {
                continue;
            }

            combined = this.core.lower(name + ' ' + label);
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

            if (this.core.canonicalUnderscore(label) === canonicalTarget) {
                score += 220;
                reasons.push('canonical_label');
            }
            if (this.core.compactAlphaNum(label) === compactTarget) {
                score += 220;
                reasons.push('compact_label');
            }
            if (this.core.canonicalUnderscore(name) === canonicalTarget) {
                score += 180;
                reasons.push('canonical_name');
            }
            if (this.core.compactAlphaNum(name) === compactTarget) {
                score += 180;
                reasons.push('compact_name');
            }
            if (name.indexOf('cmdb_ci_') === 0) {
                score += 10;
                reasons.push('cmdb_prefix');
            }

            row = this.buildCiTypeRow(gr, score, reasons);
            rows.push(row);
        }

        chosen = this.chooseBestMatch(rows, true);
        resolution.count = chosen.count || 0;
        resolution.rows = chosen.rows || [];
        resolution.selection_reason = chosen.selection_reason || '';
        if (chosen.match) {
            resolution.table_name = chosen.match.table_name;
            resolution.label = chosen.match.label || '';
            resolution.status = 'matched';
            resolution.method = 'token_search';
            resolution.match = chosen.match;
            resolution.lookup_table = chosen.match.table_name;
        } else if (chosen.ambiguous) {
            resolution.status = 'ambiguous';
            resolution.method = 'token_search';
        } else {
            resolution.status = 'not_found';
            resolution.method = 'token_search';
        }

        this.core.caches.ci_types[cacheKey] = this.core.deepClone(resolution);
        return resolution;
    },

    resolveAssignmentGroup: function (rawValue, trace) {
        var name = this.core.trimToString(rawValue);
        var cacheKey = 'group|' + name;
        var exact;
        var tokens;
        var canonicalTarget;
        var compactTarget;
        var gr;
        var chosen;

        if (!this.core.hasValue(name) || !this.core.tableExists('sys_user_group', trace)) {
            return { sys_id: '', method: 'not_attempted', status: 'not_attempted', count: 0, rows: [] };
        }

        if (typeof this.core.caches.groups[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.groups[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        if (this.core.looksLikeSysId(name)) {
            gr = new GlideRecord('sys_user_group');
            if (gr.get(name)) {
                chosen = {
                    sys_id: gr.getUniqueValue(),
                    method: 'provided_sys_id',
                    status: 'matched',
                    matched_name: this.core.getFieldText(gr, 'name'),
                    match: this.buildMatchRowFromRecord(gr, 'name'),
                    count: 1,
                    rows: [this.buildMatchRowFromRecord(gr, 'name')],
                    selection_reason: 'provided_sys_id'
                };
                this.core.caches.groups[cacheKey] = this.core.deepClone(chosen);
                return chosen;
            }
        }

        exact = this.queryExactByName(
            'sys_user_group',
            'name',
            name,
            function (groupGr) {
                if (groupGr.isValidField('active')) {
                    groupGr.orderByDesc('active');
                }
            },
            function (groupGr) {
                var extra = { score: 0, reasons: [] };
                if (groupGr.isValidField('active') && String(groupGr.getValue('active')) === 'true') {
                    extra.score += 10;
                    extra.reasons.push('active');
                }
                return extra;
            },
            false,
            trace
        );
        if (exact.match) {
            chosen = {
                sys_id: exact.match.sys_id,
                method: 'exact_name',
                status: 'matched',
                matched_name: exact.match.name,
                match: exact.match,
                count: exact.count,
                rows: exact.rows,
                selection_reason: exact.selection_reason
            };
            this.core.caches.groups[cacheKey] = this.core.deepClone(chosen);
            return chosen;
        }

        tokens = this.core.tokenize(name);
        canonicalTarget = this.core.canonicalUnderscore(name);
        compactTarget = this.core.compactAlphaNum(name);

        if (tokens.length === 0) {
            return { sys_id: '', method: 'not_found', status: 'not_found', count: 0, rows: [] };
        }

        gr = new GlideRecord('sys_user_group');
        for (var i = 0; i < tokens.length; i++) {
            gr.addQuery('name', 'CONTAINS', tokens[i]);
        }
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);

        chosen = this.chooseBestMatch(this.collectMatches(gr, 'name', (function (self) {
            return function (groupGr, row) {
                var candidateName = row.name;
                var extra = { score: 0, reasons: [] };
                if (self.core.canonicalUnderscore(candidateName) === canonicalTarget) {
                    extra.score += 100;
                    extra.reasons.push('canonical_name');
                }
                if (self.core.compactAlphaNum(candidateName) === compactTarget) {
                    extra.score += 100;
                    extra.reasons.push('compact_name');
                }
                if (groupGr.isValidField('active') && String(groupGr.getValue('active')) === 'true') {
                    extra.score += 10;
                    extra.reasons.push('active');
                }
                return extra;
            };
        })(this)), true);

        if (chosen.match) {
            chosen = {
                sys_id: chosen.match.sys_id,
                method: 'canonical_name',
                status: 'matched',
                matched_name: chosen.match.name,
                match: chosen.match,
                count: chosen.count,
                rows: chosen.rows,
                selection_reason: chosen.selection_reason
            };
        } else if (chosen.ambiguous) {
            chosen = {
                sys_id: '',
                method: 'ambiguous',
                status: 'ambiguous',
                count: chosen.count,
                rows: chosen.rows,
                selection_reason: chosen.selection_reason
            };
        } else {
            chosen = {
                sys_id: '',
                method: 'not_found',
                status: 'not_found',
                count: chosen.count || 0,
                rows: chosen.rows || [],
                selection_reason: chosen.selection_reason || 'no_match'
            };
        }

        this.core.caches.groups[cacheKey] = this.core.deepClone(chosen);
        return chosen;
    },

    resolveRecordByIdentifier: function (tableName, identifierObj, trace) {
        var gr;
        var key;
        var validKeyCount = 0;
        if (!this.core.tableExists(tableName, trace) || !this.core.isObject(identifierObj)) {
            return { match: null, count: 0, ambiguous: false, rows: [] };
        }
        gr = new GlideRecord(tableName);
        for (key in identifierObj) {
            if (!this.core.hasOwn(identifierObj, key) || !this.core.hasValue(identifierObj[key]) || !gr.isValidField(key)) {
                continue;
            }
            validKeyCount++;
            gr.addQuery(key, this.core.trimToString(identifierObj[key]));
        }
        if (validKeyCount === 0) {
            this.core.tracePush(trace, 'ci_identifier has no valid keys for table ' + tableName);
            return { match: null, count: 0, ambiguous: false, rows: [], selection_reason: 'no_valid_keys' };
        }
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);
        return this.chooseBestMatch(this.collectMatches(gr, 'name'), true);
    },

    validateCmdbCiSysId: function (sysId, trace) {
        var cacheKey = 'cmdb|' + sysId;
        var gr;
        var out;
        if (!this.core.looksLikeSysId(sysId) || !this.core.tableExists('cmdb_ci', trace)) {
            return null;
        }
        if (typeof this.core.caches.cmdb_by_sysid[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.cmdb_by_sysid[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);
        gr = new GlideRecord('cmdb_ci');
        if (!gr.get(sysId)) {
            this.core.caches.cmdb_by_sysid[cacheKey] = null;
            return null;
        }
        out = {
            sys_id: gr.getUniqueValue(),
            name: this.core.getFieldText(gr, 'name'),
            sys_class_name: this.core.getFieldText(gr, 'sys_class_name'),
            score: 999,
            score_reasons: ['provided_sys_id']
        };
        this.core.caches.cmdb_by_sysid[cacheKey] = this.core.deepClone(out);
        return out;
    },

    resolveCmdbCiByName: function (nameValue, trace) {
        var name = this.core.trimToString(nameValue);
        var cacheKey = 'cmdb_name|' + name;
        var exact;
        var tokens;
        var canonicalTarget;
        var compactTarget;
        var gr;
        var chosen;

        if (!this.core.hasValue(name) || !this.core.tableExists('cmdb_ci', trace)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'empty' };
        }
        if (typeof this.core.caches.cmdb_by_name[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.cmdb_by_name[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        exact = this.queryExactByName(
            'cmdb_ci',
            'name',
            name,
            null,
            (function (self) {
                return function (ciGr, row) {
                    return self.getCmdbCiLookupExtraScore(ciGr, row, '', '');
                };
            })(this),
            true,
            trace
        );
        exact.status = exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found');
        exact.method = 'exact_name';

        if (exact.match || exact.ambiguous) {
            this.core.caches.cmdb_by_name[cacheKey] = this.core.deepClone(exact);
            return exact;
        }

        tokens = this.core.tokenize(name);
        canonicalTarget = this.core.canonicalUnderscore(name);
        compactTarget = this.core.compactAlphaNum(name);

        if (tokens.length === 0) {
            chosen = { match: null, count: 0, ambiguous: false, rows: [], status: 'not_found', method: 'canonical_name' };
            this.core.caches.cmdb_by_name[cacheKey] = this.core.deepClone(chosen);
            return chosen;
        }

        gr = new GlideRecord('cmdb_ci');
        if (!gr.isValidField('name')) {
            chosen = { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: 'canonical_name' };
            this.core.caches.cmdb_by_name[cacheKey] = this.core.deepClone(chosen);
            return chosen;
        }

        for (var i = 0; i < tokens.length; i++) {
            gr.addQuery('name', 'CONTAINS', tokens[i]);
        }
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);

        chosen = this.chooseBestMatch(this.collectMatches(gr, 'name', (function (self) {
            return function (ciGr, row) {
                return self.getCmdbCiLookupExtraScore(ciGr, row, canonicalTarget, compactTarget);
            };
        })(this)), true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = 'canonical_name';

        this.core.caches.cmdb_by_name[cacheKey] = this.core.deepClone(chosen);
        return chosen;
    },

    resolveNodeCmdbCi: function (nodeValue, trace) {
        var nodeText = this.core.trimToString(nodeValue);
        var cacheKey = 'node|' + nodeText;
        var shortNode = '';
        var rows = [];
        var bySysId = {};
        var candidates = [];
        var fields = ['fqdn', 'host_name', 'hostname', 'dns_name', 'ip_address', 'ip_addresss'];
        var i;
        var exact;
        var gr;
        var row;
        var chosen;
        var validated;
        var fieldName;
        var rowIndex;

        if (!this.core.hasValue(nodeText)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'node_lookup' };
        }
        if (typeof this.core.caches.nodes[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.nodes[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        if (this.core.looksLikeSysId(nodeText)) {
            validated = this.validateCmdbCiSysId(nodeText, trace);
            if (validated) {
                chosen = {
                    match: validated,
                    count: 1,
                    ambiguous: false,
                    rows: [validated],
                    status: 'matched',
                    method: 'provided_node_sys_id',
                    selection_reason: 'provided_node_sys_id'
                };
                this.core.caches.nodes[cacheKey] = this.core.deepClone(chosen);
                return chosen;
            }
        }

        candidates.push(nodeText);
        if (nodeText.indexOf('.') > -1) {
            shortNode = nodeText.split('.')[0];
            if (this.core.hasValue(shortNode) && shortNode !== nodeText) {
                candidates.push(shortNode);
            }
        }

        for (i = 0; i < candidates.length; i++) {
            exact = this.queryExactByName(
                'cmdb_ci',
                'name',
                candidates[i],
                function (candidateGr) {
                    if (candidateGr.isValidField('sys_class_name')) {
                        candidateGr.addQuery('sys_class_name', '!=', 'cmdb_ci_service');
                        candidateGr.addQuery('sys_class_name', '!=', 'service_offering');
                    }
                },
                (function (nodeTextLocal, candidateValue) {
                    return function () {
                        return {
                            score: (candidateValue === nodeTextLocal ? 80 : 60),
                            reasons: [candidateValue === nodeTextLocal ? 'node_name_exact' : 'node_short_name_exact']
                        };
                    };
                })(nodeText, candidates[i]),
                false,
                trace
            );
            if (this.core.isArray(exact.rows)) {
                for (rowIndex = 0; rowIndex < exact.rows.length; rowIndex++) {
                    this.mergeCandidateRow(rows, bySysId, exact.rows[rowIndex]);
                }
            }
        }

        for (i = 0; i < fields.length; i++) {
            gr = new GlideRecord('cmdb_ci');
            if (!gr.isValidField(fields[i])) {
                continue;
            }
            fieldName = fields[i];
            gr.addQuery(fieldName, nodeText);
            if (gr.isValidField('sys_class_name')) {
                gr.addQuery('sys_class_name', '!=', 'cmdb_ci_service');
                gr.addQuery('sys_class_name', '!=', 'service_offering');
            }
            gr.setLimit(this.core.MAX_QUERY_ROWS);
            this.queryNow(gr, trace);
            while (gr.next()) {
                row = this.buildMatchRowFromRecord(gr, 'name', function () {
                    return { score: 70, reasons: ['node_field_exact_' + fieldName] };
                });
                this.mergeCandidateRow(rows, bySysId, row);
            }
        }

        chosen = this.chooseBestMatch(rows, true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = 'node_lookup';
        chosen.lookup_table = 'cmdb_ci';
        this.core.caches.nodes[cacheKey] = this.core.deepClone(chosen);
        return chosen;
    },

    buildNodeNeighborhood: function (nodeSysId, trace) {
        var cacheKey = 'related|' + nodeSysId;
        var frontier = [nodeSysId];
        var visited = {};
        var depthMap = {};
        var next = [];
        var depth = 0;
        var relGr;
        var current;
        var other;
        var i;
        var fieldParent;
        var fieldChild;
        var totalVisited = 0;

        if (!this.core.looksLikeSysId(nodeSysId) || !this.core.tableExists('cmdb_rel_ci', trace)) {
            return { sys_ids: {}, depth_map: {} };
        }
        if (typeof this.core.caches.related_nodes[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.related_nodes[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        visited[nodeSysId] = true;
        depthMap[nodeSysId] = 0;
        totalVisited = 1;

        while (frontier.length > 0 && depth < this.core.NODE_RELATION_MAX_DEPTH && totalVisited < this.core.NODE_RELATION_MAX_NODES) {
            next = [];
            for (i = 0; i < frontier.length; i++) {
                current = frontier[i];
                relGr = new GlideRecord('cmdb_rel_ci');
                fieldParent = this.getQueryField(relGr, ['parent', 'parent_ci']);
                fieldChild = this.getQueryField(relGr, ['child', 'child_ci']);
                if (!this.core.hasValue(fieldParent) || !this.core.hasValue(fieldChild)) {
                    break;
                }
                relGr.addQuery(fieldParent, current).addOrCondition(fieldChild, current);
                relGr.setLimit(this.core.MAX_QUERY_ROWS);
                this.queryNow(relGr, trace);
                while (relGr.next()) {
                    if (relGr.getValue(fieldParent) === current) {
                        other = relGr.getValue(fieldChild);
                    } else {
                        other = relGr.getValue(fieldParent);
                    }
                    if (!this.core.looksLikeSysId(other) || visited[other]) {
                        continue;
                    }
                    visited[other] = true;
                    depthMap[other] = depth + 1;
                    next.push(other);
                    totalVisited++;
                    if (totalVisited >= this.core.NODE_RELATION_MAX_NODES) {
                        break;
                    }
                }
                if (totalVisited >= this.core.NODE_RELATION_MAX_NODES) {
                    break;
                }
            }
            frontier = next;
            depth++;
        }

        this.core.caches.related_nodes[cacheKey] = this.core.deepClone({ sys_ids: visited, depth_map: depthMap });
        return { sys_ids: visited, depth_map: depthMap };
    },

    getExistingFields: function (gr, candidates) {
        var out = [];
        var i;
        if (!gr || !gr.isValidField || !this.core.isArray(candidates)) {
            return out;
        }
        for (i = 0; i < candidates.length; i++) {
            if (gr.isValidField(candidates[i])) {
                out.push(candidates[i]);
            }
        }
        return out;
    },

    getResourceSearchFields: function (gr) {
        return this.getExistingFields(gr, [
            'name',
            'display_name',
            'mount_point',
            'mountpoint',
            'mount',
            'path',
            'directory_path',
            'directory',
            'location',
            'device',
            'device_name',
            'logical_name',
            'volume_name',
            'file_system',
            'filesystem',
            'resource',
            'instance_name',
            'share_path',
            'share_name',
            'url',
            'ip_address',
            'mac_address',
            'interface_name',
            'sid',
            'db_name',
            'port',
            'key_attributes'
        ]);
    },

    buildResourceContext: function (resourceValue, nodeValue) {
        var resourceText = this.core.trimToString(resourceValue);
        var nodeText = this.core.trimToString(nodeValue);
        var out;
        var candidateNames = [];
        var candidateMap = {};
        var parts;
        var partIndex;
        var baseText = '';
        var shortNode = '';
        var tokens;
        var push = function (name) {
            if (!name) {
                return;
            }
            if (!candidateMap[name.toLowerCase()]) {
                candidateMap[name.toLowerCase()] = true;
                candidateNames.push(name);
            }
        };

        if (!this.core.hasValue(resourceText)) {
            return null;
        }

        if (resourceText.indexOf('@') > -1) {
            push(resourceText);
            resourceText = resourceText.split('@')[0];
        }

        push(resourceText);
        if (this.core.hasValue(nodeText)) {
            push(resourceText + '@' + nodeText);
            if (nodeText.indexOf('.') > -1) {
                shortNode = nodeText.split('.')[0];
                if (this.core.hasValue(shortNode)) {
                    push(resourceText + '@' + shortNode);
                }
            }
        }

        parts = resourceText.replace(/\\/g, '/').split('/');
        for (partIndex = parts.length - 1; partIndex >= 0; partIndex--) {
            if (this.core.hasValue(parts[partIndex])) {
                baseText = parts[partIndex];
                break;
            }
        }
        if (!this.core.hasValue(baseText)) {
            baseText = resourceText.replace(/^\/+|\/+$/g, '');
        }
        if (this.core.hasValue(baseText)) {
            push(baseText);
        }

        tokens = this.core.tokenize(baseText || resourceText);

        out = {
            resource_text: this.core.trimToString(resourceValue),
            resource_no_at: resourceText,
            node_text: nodeText,
            short_node: shortNode,
            base_text: baseText,
            candidate_names: candidateNames,
            candidate_map: candidateMap,
            tokens: tokens,
            resource_lower: this.core.lower(resourceText),
            base_lower: this.core.lower(baseText),
            resource_compact: this.core.compactAlphaNum(resourceText),
            base_compact: this.core.compactAlphaNum(baseText)
        };

        return out;
    },

    scoreResourceTextValue: function (textValue, resourceContext, fieldName) {
        var text = this.core.trimToString(textValue);
        var textLower;
        var textCompact;
        var score = 0;
        var reasons = [];
        var i;
        var allTokensPresent = true;
        var fieldBonus = 0;

        if (!this.core.hasValue(text) || !resourceContext) {
            return { score: 0, reasons: [] };
        }

        textLower = this.core.lower(text);
        textCompact = this.core.compactAlphaNum(text);

        if (fieldName === 'mount_point' || fieldName === 'mountpoint' || fieldName === 'mount' || fieldName === 'path' || fieldName === 'directory_path' || fieldName === 'directory') {
            fieldBonus = 45;
        } else if (fieldName === 'device' || fieldName === 'device_name' || fieldName === 'logical_name' || fieldName === 'volume_name') {
            fieldBonus = 35;
        } else if (fieldName === 'ip_address' || fieldName === 'mac_address' || fieldName === 'interface_name') {
            fieldBonus = 40;
        } else if (fieldName === 'name') {
            fieldBonus = 20;
        }

        if (resourceContext.candidate_map[textLower]) {
            score = Math.max(score, 240 + fieldBonus);
            reasons.push('resource_exact_' + fieldName);
        }
        if (textLower === resourceContext.resource_lower) {
            score = Math.max(score, 220 + fieldBonus);
            reasons.push('resource_literal_' + fieldName);
        }
        if (this.core.hasValue(resourceContext.base_lower) && textLower === resourceContext.base_lower) {
            score = Math.max(score, 195 + fieldBonus);
            reasons.push('resource_base_exact_' + fieldName);
        }
        if (textCompact === resourceContext.resource_compact) {
            score = Math.max(score, 185 + fieldBonus);
            reasons.push('resource_compact_' + fieldName);
        }
        if (this.core.hasValue(resourceContext.base_compact) && textCompact === resourceContext.base_compact) {
            score = Math.max(score, 170 + fieldBonus);
            reasons.push('resource_base_compact_' + fieldName);
        }

        for (i = 0; i < resourceContext.tokens.length; i++) {
            if (textLower.indexOf(resourceContext.tokens[i]) === -1) {
                allTokensPresent = false;
                break;
            }
        }
        if (allTokensPresent && resourceContext.tokens.length > 0) {
            score = Math.max(score, 110 + fieldBonus);
            reasons.push('resource_tokens_' + fieldName);
        }

        return { score: score, reasons: reasons };
    },

    getNodeReferenceFields: function (gr) {
        return this.getExistingFields(gr, [
            'computer',
            'host',
            'server',
            'node',
            'parent',
            'parent_ci',
            'cmdb_ci',
            'configuration_item',
            'nic',
            'network_adapter',
            'interface',
            'device'
        ]);
    },

    scoreNodeAffinity: function (gr, nodeInput, nodeMatch, neighborhood, trace) {
        var score = 0;
        var reasons = [];
        var fields;
        var i;
        var value;
        var display;
        var normalizedNode = this.core.lower(nodeInput || '');
        var shortNode = normalizedNode.indexOf('.') > -1 ? normalizedNode.split('.')[0] : normalizedNode;
        var candidateSysId = gr.getUniqueValue();
        var depth;

        if (neighborhood && neighborhood.depth_map && typeof neighborhood.depth_map[candidateSysId] !== 'undefined') {
            depth = neighborhood.depth_map[candidateSysId];
            if (depth === 0) {
                score += 80;
                reasons.push('node_relation_depth0');
            } else if (depth === 1) {
                score += 240;
                reasons.push('node_relation_depth1');
            } else if (depth === 2) {
                score += 180;
                reasons.push('node_relation_depth2');
            }
        }

        fields = this.getNodeReferenceFields(gr);
        for (i = 0; i < fields.length; i++) {
            value = gr.getValue(fields[i]) || '';
            display = this.core.lower(gr.getDisplayValue(fields[i]) || '');
            if (nodeMatch && this.core.hasValue(nodeMatch.sys_id) && value === nodeMatch.sys_id) {
                score += 260;
                reasons.push('node_ref_' + fields[i]);
            }
            if (this.core.hasValue(normalizedNode) && display === normalizedNode) {
                score += 220;
                reasons.push('node_display_exact_' + fields[i]);
            } else if (this.core.hasValue(shortNode) && display === shortNode) {
                score += 200;
                reasons.push('node_display_short_' + fields[i]);
            }
        }

        return { score: score, reasons: reasons };
    },

    searchResourceTable: function (tableName, resourceContext, nodeInput, nodeMatch, neighborhood, classBonus, trace) {
        var rows = [];
        var bySysId = {};
        var gr;
        var fields;
        var candidateNames;
        var i;
        var j;
        var fieldName;
        var candidateValue;
        var row;
        var searchRows;
        var searchGr;
        var searchField;
        var textScore;
        var nodeScore;
        var classBonusValue = classBonus || 0;

        if (!this.core.tableExists(tableName, trace) || !resourceContext) {
            return rows;
        }

        candidateNames = resourceContext.candidate_names || [];

        gr = new GlideRecord(tableName);
        fields = this.getResourceSearchFields(gr);
        for (i = 0; i < fields.length; i++) {
            fieldName = fields[i];

            for (j = 0; j < candidateNames.length; j++) {
                candidateValue = candidateNames[j];
                searchGr = new GlideRecord(tableName);
                if (!searchGr.isValidField(fieldName)) {
                    continue;
                }
                searchGr.addQuery(fieldName, candidateValue);
                searchGr.setLimit(this.core.MAX_QUERY_ROWS);
                this.queryNow(searchGr, trace);

                searchRows = this.collectMatches(searchGr, 'name', (function (self, resourceContextLocal, nodeInputLocal, nodeMatchLocal, neighborhoodLocal, fieldNameLocal, candidateValueLocal, classBonusLocal) {
                    return function (candidateGr, baseRow) {
                        var out = { score: classBonusLocal, reasons: [] };
                        var textValue = candidateGr.getDisplayValue(fieldNameLocal) || candidateGr.getValue(fieldNameLocal) || '';
                        var textResult = self.scoreResourceTextValue(textValue, resourceContextLocal, fieldNameLocal);
                        var nodeResult = self.scoreNodeAffinity(candidateGr, nodeInputLocal, nodeMatchLocal, neighborhoodLocal, trace);
                        out.score += textResult.score + nodeResult.score;
                        out.reasons = out.reasons.concat(textResult.reasons).concat(nodeResult.reasons);
                        if (candidateValueLocal === resourceContextLocal.resource_no_at + '@' + resourceContextLocal.node_text) {
                            out.score += 30;
                            out.reasons.push('resource_at_node_query');
                        }
                        return out;
                    };
                })(this, resourceContext, nodeInput, nodeMatch, neighborhood, fieldName, candidateValue, classBonusValue));

                for (var r = 0; r < searchRows.length; r++) {
                    this.mergeCandidateRow(rows, bySysId, searchRows[r]);
                }
            }
        }

        return rows;
    },

    searchResourceCategoryFallback: function (resourceContext, nodeInput, nodeMatch, neighborhood, ciTypeTable, trace) {
        var rows = [];
        var bySysId = {};
        var gr;
        var fields;
        var fieldName;
        var searchValue;
        var i;
        var candidateValues = [];
        var seen = {};
        var rRows;
        var classNameBonus = 0;

        if (!resourceContext || !this.core.tableExists('cmdb_ci', trace)) {
            return rows;
        }

        candidateValues.push(resourceContext.resource_no_at);
        if (this.core.hasValue(resourceContext.base_text)) {
            candidateValues.push(resourceContext.base_text);
        }

        for (i = 0; i < candidateValues.length; i++) {
            searchValue = candidateValues[i];
            if (!this.core.hasValue(searchValue) || seen[searchValue]) {
                continue;
            }
            seen[searchValue] = true;

            gr = new GlideRecord('cmdb_ci');
            if (gr.isValidField('category')) {
                gr.addQuery('category', 'resource');
            }
            if (this.core.hasValue(ciTypeTable) && gr.isValidField('sys_class_name')) {
                gr.addQuery('sys_class_name', 'INSTANCEOF', ciTypeTable);
                classNameBonus = 50;
            } else {
                classNameBonus = 0;
            }

            fields = this.getResourceSearchFields(gr);
            for (var f = 0; f < fields.length; f++) {
                fieldName = fields[f];
                if (!gr.isValidField(fieldName)) {
                    continue;
                }
                rRows = [];
                gr = new GlideRecord('cmdb_ci');
                if (gr.isValidField('category')) {
                    gr.addQuery('category', 'resource');
                }
                if (this.core.hasValue(ciTypeTable) && gr.isValidField('sys_class_name')) {
                    gr.addQuery('sys_class_name', 'INSTANCEOF', ciTypeTable);
                }
                if (!gr.isValidField(fieldName)) {
                    continue;
                }
                gr.addQuery(fieldName, searchValue);
                gr.setLimit(this.core.MAX_QUERY_ROWS);
                this.queryNow(gr, trace);
                rRows = this.collectMatches(gr, 'name', (function (self, resourceContextLocal, nodeInputLocal, nodeMatchLocal, neighborhoodLocal, fieldNameLocal, classBonusLocal) {
                    return function (candidateGr) {
                        var out = { score: classBonusLocal + 20, reasons: ['category_resource'] };
                        var textValue = candidateGr.getDisplayValue(fieldNameLocal) || candidateGr.getValue(fieldNameLocal) || '';
                        var textResult = self.scoreResourceTextValue(textValue, resourceContextLocal, fieldNameLocal);
                        var nodeResult = self.scoreNodeAffinity(candidateGr, nodeInputLocal, nodeMatchLocal, neighborhoodLocal, trace);
                        out.score += textResult.score + nodeResult.score;
                        out.reasons = out.reasons.concat(textResult.reasons).concat(nodeResult.reasons);
                        return out;
                    };
                })(this, resourceContext, nodeInput, nodeMatch, neighborhood, fieldName, classNameBonus));
                for (var rr = 0; rr < rRows.length; rr++) {
                    this.mergeCandidateRow(rows, bySysId, rRows[rr]);
                }
            }
        }
        return rows;
    },

    resolveResourceBackedCmdbCi: function (mapped, ciTypeTable, trace) {
        var resourceContext = this.buildResourceContext(mapped.resource, mapped.node);
        var nodeResolution;
        var nodeMatch = null;
        var neighborhood = { sys_ids: {}, depth_map: {} };
        var rows = [];
        var bySysId = {};
        var chosen;
        var resourceTables = [];
        var i;
        var searchRows;

        if (!resourceContext) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'resource' };
        }

        if (this.core.hasValue(mapped.node)) {
            nodeResolution = this.resolveNodeCmdbCi(mapped.node, trace);
            if (nodeResolution && nodeResolution.match) {
                nodeMatch = nodeResolution.match;
                neighborhood = this.buildNodeNeighborhood(nodeMatch.sys_id, trace);
            }
        }

        if (this.core.hasValue(ciTypeTable) && this.core.tableExists(ciTypeTable, trace)) {
            resourceTables.push(ciTypeTable);
        }
        if (resourceTables.indexOf('cmdb_ci') === -1) {
            resourceTables.push('cmdb_ci');
        }

        for (i = 0; i < resourceTables.length; i++) {
            searchRows = this.searchResourceTable(resourceTables[i], resourceContext, mapped.node, nodeMatch, neighborhood, resourceTables[i] === ciTypeTable ? 80 : 0, trace);
            for (var r = 0; r < searchRows.length; r++) {
                this.mergeCandidateRow(rows, bySysId, searchRows[r]);
            }
        }

        searchRows = this.searchResourceCategoryFallback(resourceContext, mapped.node, nodeMatch, neighborhood, ciTypeTable, trace);
        for (i = 0; i < searchRows.length; i++) {
            this.mergeCandidateRow(rows, bySysId, searchRows[i]);
        }

        chosen = this.chooseBestMatch(rows, true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = this.core.hasValue(ciTypeTable) ? 'resource_mode_ci_type' : 'resource_mode_any';
        chosen.lookup_table = this.core.hasValue(ciTypeTable) ? ciTypeTable : 'cmdb_ci';
        chosen.input = {
            node: mapped.node || '',
            resource: mapped.resource || '',
            ci_type: ciTypeTable || ''
        };
        return chosen;
    },

    resolveServiceFromAssoc: function (ciSysId, trace) {
        var cacheKey = 'service_assoc|' + ciSysId;
        var gr;
        var ciField;
        var serviceField;
        var serviceSysId;
        var serviceGr;
        var rows = [];
        var chosen;

        if (!this.core.hasValue(ciSysId) || !this.core.tableExists('svc_ci_assoc', trace) || !this.core.tableExists('cmdb_ci_service', trace)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'svc_ci_assoc' };
        }

        if (typeof this.core.caches.service_assoc[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.service_assoc[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        gr = new GlideRecord('svc_ci_assoc');
        ciField = this.getQueryField(gr, ['ci', 'cmdb_ci', 'configuration_item', 'ci_id']);
        serviceField = this.getQueryField(gr, ['service', 'business_service', 'cmdb_ci_service', 'service_id']);
        if (!this.core.hasValue(ciField) || !this.core.hasValue(serviceField)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: 'svc_ci_assoc' };
        }

        gr.addQuery(ciField, ciSysId);
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);

        while (gr.next()) {
            serviceSysId = gr.getValue(serviceField);
            if (!this.core.looksLikeSysId(serviceSysId)) {
                continue;
            }
            serviceGr = new GlideRecord('cmdb_ci_service');
            if (!serviceGr.get(serviceSysId)) {
                continue;
            }
            rows.push(this.buildMatchRowFromRecord(serviceGr, 'name', function () {
                return { score: 120, reasons: ['service_association'] };
            }));
        }

        chosen = this.chooseBestMatch(rows, false);
        chosen.status = chosen.match ? 'matched' : 'not_found';
        chosen.method = 'svc_ci_assoc';
        this.core.caches.service_assoc[cacheKey] = this.core.deepClone(chosen);
        return chosen;
    },

    resolveServiceByName: function (nameValue, trace) {
        var cacheKey = 'service|' + this.core.trimToString(nameValue);
        var exact;
        if (!this.core.hasValue(nameValue)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'exact_name' };
        }
        if (typeof this.core.caches.services[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.services[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);
        exact = this.queryExactByName('cmdb_ci_service', 'name', nameValue, null, null, true, trace);
        exact.status = exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found');
        exact.method = 'exact_name';
        this.core.caches.services[cacheKey] = this.core.deepClone(exact);
        return exact;
    },

    resolveBusinessAppByCarId: function (carIdValue, trace) {
        var cacheKey = 'car|' + this.core.trimToString(carIdValue);
        var gr;
        var chosen;
        if (!this.core.hasValue(carIdValue) || !this.core.tableExists('cmdb_ci_business_app', trace)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: 'u_car_id' };
        }
        if (typeof this.core.caches.business_apps[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.business_apps[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        gr = new GlideRecord('cmdb_ci_business_app');
        if (!gr.isValidField('u_car_id')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: 'u_car_id' };
        }
        gr.addQuery('u_car_id', this.core.trimToString(carIdValue));
        if (gr.isValidField('sys_class_name')) {
            gr.addQuery('sys_class_name', 'cmdb_ci_business_app');
        }
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);
        chosen = this.chooseBestMatch(this.collectMatches(gr, 'name'), true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = 'u_car_id';
        this.core.caches.business_apps[cacheKey] = this.core.deepClone(chosen);
        return chosen;
    },

    resolveOfferingByName: function (nameValue, serviceSysId, trace) {
        var cacheKey = 'offering|' + this.core.trimToString(nameValue) + '|' + this.core.trimToString(serviceSysId);
        var gr;
        var chosen;
        if (!this.core.hasValue(nameValue) || !this.core.tableExists('service_offering', trace)) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'not_attempted', method: this.core.hasValue(serviceSysId) ? 'name_and_parent' : 'name' };
        }
        if (typeof this.core.caches.offerings[cacheKey] !== 'undefined') {
            this.core.bumpMetric(trace, 'cache_hits', 1);
            return this.core.deepClone(this.core.caches.offerings[cacheKey]);
        }
        this.core.bumpMetric(trace, 'cache_misses', 1);

        gr = new GlideRecord('service_offering');
        if (!gr.isValidField('name')) {
            return { match: null, count: 0, ambiguous: false, rows: [], status: 'lookup_unavailable', method: this.core.hasValue(serviceSysId) ? 'name_and_parent' : 'name' };
        }
        gr.addQuery('name', this.core.trimToString(nameValue));
        if (this.core.hasValue(serviceSysId) && gr.isValidField('parent')) {
            gr.addQuery('parent', serviceSysId);
        }
        gr.setLimit(this.core.MAX_QUERY_ROWS);
        this.queryNow(gr, trace);
        chosen = this.chooseBestMatch(this.collectMatches(gr, 'name', function (offeringGr) {
            var extra = { score: 0, reasons: [] };
            if (serviceSysId && offeringGr.isValidField('parent') && offeringGr.getValue('parent') === serviceSysId) {
                extra.score += 120;
                extra.reasons.push('service_parent_match');
            }
            return extra;
        }), true);
        chosen.status = chosen.match ? 'matched' : (chosen.ambiguous ? 'ambiguous' : 'not_found');
        chosen.method = this.core.hasValue(serviceSysId) ? 'name_and_parent' : 'name';
        this.core.caches.offerings[cacheKey] = this.core.deepClone(chosen);
        return chosen;
    },

    getSupportGroupForCi: function (ciSysId, trace) {
        var gr;
        var supportValue;
        if (!this.core.looksLikeSysId(ciSysId) || !this.core.tableExists('cmdb_ci', trace)) {
            return { sys_id: '', status: 'not_attempted', method: 'support_group' };
        }
        gr = new GlideRecord('cmdb_ci');
        if (!gr.get(ciSysId)) {
            return { sys_id: '', status: 'not_found', method: 'support_group' };
        }
        if (!gr.isValidField('support_group')) {
            return { sys_id: '', status: 'lookup_unavailable', method: 'support_group' };
        }
        supportValue = gr.getValue('support_group');
        if (this.core.looksLikeSysId(supportValue)) {
            return {
                sys_id: supportValue,
                status: 'matched',
                method: 'cmdb_ci_support_group',
                match: {
                    sys_id: supportValue,
                    name: gr.getDisplayValue('support_group'),
                    score: 999,
                    score_reasons: ['cmdb_ci_support_group']
                },
                count: 1,
                rows: []
            };
        }
        return { sys_id: '', status: 'not_found', method: 'cmdb_ci_support_group' };
    },

    resolvePrimaryCmdbCi: function (ctx) {
        var resolution = {
            status: 'not_attempted',
            method: '',
            count: 0,
            rows: [],
            selection_reason: '',
            lookup_table: ''
        };
        var result = null;
        var exact;
        var nameValue = '';
        var ciTypeTable = '';
        var dummyCi = '';
        var nodeResolution;
        var explicitCmdbCiInput = this.core.hasValue(ctx.mapped.cmdb_ci);

        if (this.core.hasValue(ctx.mapped.ci_type)) {
            ctx.ci_type_resolution = this.resolveCiTypeTable(ctx.mapped.ci_type, ctx.debug);
            this.core.traceLookup(ctx.debug, 'ci_type', ctx.ci_type_resolution);
            if (ctx.ci_type_resolution && this.core.hasValue(ctx.ci_type_resolution.table_name)) {
                ctx.mapped.ci_type = ctx.ci_type_resolution.table_name;
                ciTypeTable = ctx.ci_type_resolution.table_name;
            }
        }

        if (this.core.hasValue(ctx.mapped.cmdb_ci)) {
            ctx.attempts.ci = true;
            if (this.core.looksLikeSysId(ctx.mapped.cmdb_ci)) {
                result = this.validateCmdbCiSysId(ctx.mapped.cmdb_ci, ctx.debug);
                resolution = {
                    status: result ? 'matched' : 'not_found',
                    method: 'provided_sys_id',
                    count: result ? 1 : 0,
                    rows: result ? [result] : [],
                    match: result,
                    selection_reason: result ? 'provided_sys_id' : 'not_found',
                    lookup_table: 'cmdb_ci'
                };
            } else {
                exact = this.resolveCmdbCiByName(ctx.mapped.cmdb_ci, ctx.debug);
                resolution = {
                    status: exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found'),
                    method: exact.method || 'cmdb_ci_name',
                    count: exact.count,
                    rows: exact.rows,
                    match: exact.match,
                    selection_reason: exact.selection_reason,
                    lookup_table: 'cmdb_ci'
                };
                if (exact.match) {
                    result = exact.match;
                }
            }
            this.core.traceLookup(ctx.debug, 'cmdb_ci', resolution);
        }

        if (!result && this.core.hasValue(ciTypeTable) && ctx.ci_identifier_obj) {
            ctx.attempts.ci = true;
            exact = this.resolveRecordByIdentifier(ciTypeTable, ctx.ci_identifier_obj, ctx.debug);
            resolution = {
                status: exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found'),
                method: 'ci_type_and_ci_identifier',
                count: exact.count,
                rows: exact.rows,
                match: exact.match,
                selection_reason: exact.selection_reason,
                lookup_table: ciTypeTable
            };
            if (exact.match) {
                result = exact.match;
            }
            this.core.traceLookup(ctx.debug, 'ci_identifier', resolution);
        }

        if (!result && this.core.hasValue(ctx.mapped.resource)) {
            ctx.attempts.ci = true;
            exact = this.resolveResourceBackedCmdbCi(ctx.mapped, ciTypeTable, ctx.debug);
            resolution = exact;
            if (exact.match) {
                result = exact.match;
            }
            this.core.traceLookup(ctx.debug, 'resource_mode', resolution);
        }

        if (!result && this.core.hasValue(ctx.mapped.node)) {
            ctx.attempts.ci = true;
            nodeResolution = this.resolveNodeCmdbCi(ctx.mapped.node, ctx.debug);
            resolution = nodeResolution;
            if (nodeResolution.match) {
                result = nodeResolution.match;
            }
            this.core.traceLookup(ctx.debug, 'node', nodeResolution);
        }

        if (!result && !this.core.hasValue(ctx.mapped.node)) {
            if (this.core.isObject(ctx.user_additional_info) && this.core.hasValue(ctx.user_additional_info.name)) {
                nameValue = ctx.user_additional_info.name;
                delete ctx.user_additional_info.name;
                ctx.attempts.ci = true;
            }
            if (this.core.hasValue(nameValue)) {
                exact = this.resolveCmdbCiByName(nameValue, ctx.debug);
                resolution = {
                    status: exact.match ? 'matched' : (exact.ambiguous ? 'ambiguous' : 'not_found'),
                    method: exact.method || 'name_fallback',
                    count: exact.count,
                    rows: exact.rows,
                    match: exact.match,
                    selection_reason: exact.selection_reason,
                    lookup_table: 'cmdb_ci'
                };
                if (exact.match) {
                    result = exact.match;
                }
                this.core.traceLookup(ctx.debug, 'name_fallback', resolution);
            }
        }

        if (result && this.core.hasValue(result.sys_id)) {
            ctx.resolved.cmdb_ci_sys_id = result.sys_id;
            ctx.mapped.cmdb_ci = result.sys_id;
            return result;
        }

        if (explicitCmdbCiInput) {
            ctx.resolved.cmdb_ci_sys_id = '';
            ctx.mapped.cmdb_ci = '';
            return result;
        }

        if (this.core.shouldUseDummyCi(ctx)) {
            dummyCi = this.core.getDefaultCmdbCiSysId(ctx.debug);
            if (this.core.looksLikeSysId(dummyCi)) {
                ctx.resolved.cmdb_ci_sys_id = dummyCi;
                ctx.mapped.cmdb_ci = dummyCi;
                ctx.resolved.dummy_ci_used = true;
                this.core.traceNote(ctx.debug, 'dummy cmdb_ci used');
            }
        }

        return result;
    },

    resolveAssignmentAndCorrelations: function (ctx) {
        var businessAppMatch;
        var serviceMatch;
        var offeringMatch;
        var inputGroupMatch;
        var supportGroupMatch;
        var finalGroup = '';
        var dummyGroup = '';

        if (this.core.hasValue(ctx.special.usbem_car_id)) {
            businessAppMatch = this.resolveBusinessAppByCarId(ctx.special.usbem_car_id, ctx.debug);
            this.core.traceLookup(ctx.debug, 'usbem_car_id', businessAppMatch);
            if (businessAppMatch && businessAppMatch.match) {
                ctx.resolved.cmdb_ci_business_app = businessAppMatch.match.sys_id;
            }
        }

        if (this.core.hasValue(ctx.special.usbem_service)) {
            serviceMatch = this.resolveServiceByName(ctx.special.usbem_service, ctx.debug);
            this.core.traceLookup(ctx.debug, 'usbem_service', serviceMatch);
        } else if (this.core.hasValue(ctx.resolved.cmdb_ci_sys_id)) {
            serviceMatch = this.resolveServiceFromAssoc(ctx.resolved.cmdb_ci_sys_id, ctx.debug);
            this.core.traceLookup(ctx.debug, 'svc_ci_assoc', serviceMatch);
        }
        if (serviceMatch && serviceMatch.match) {
            ctx.resolved.cmdb_ci_service = serviceMatch.match.sys_id;
            if (!this.core.hasValue(ctx.mapped.service)) {
                ctx.mapped.service = serviceMatch.match.sys_id;
            }
        }

        if (this.core.hasValue(ctx.special.usbem_offering)) {
            offeringMatch = this.resolveOfferingByName(ctx.special.usbem_offering, ctx.resolved.cmdb_ci_service, ctx.debug);
            this.core.traceLookup(ctx.debug, 'usbem_offering', offeringMatch);
            if (offeringMatch && offeringMatch.match) {
                ctx.resolved.cmdb_ci_service_offering = offeringMatch.match.sys_id;
                if (!this.core.hasValue(ctx.mapped.service_offering)) {
                    ctx.mapped.service_offering = offeringMatch.match.sys_id;
                }
            }
        }

        if (this.core.hasValue(ctx.resolved.cmdb_ci_sys_id)) {
            supportGroupMatch = this.getSupportGroupForCi(ctx.resolved.cmdb_ci_sys_id, ctx.debug);
            this.core.traceLookup(ctx.debug, 'cmdb_ci_support_group', supportGroupMatch);
            if (supportGroupMatch && this.core.hasValue(supportGroupMatch.sys_id)) {
                ctx.resolved.support_group_sys_id = supportGroupMatch.sys_id;
                finalGroup = supportGroupMatch.sys_id;
            }
        }

        if (this.core.hasValue(ctx.special.assignment_group)) {
            ctx.attempts.assignment_group = true;
            inputGroupMatch = this.resolveAssignmentGroup(ctx.special.assignment_group, ctx.debug);
            this.core.traceLookup(ctx.debug, 'assignment_group', inputGroupMatch);
            if (!this.core.hasValue(finalGroup) && inputGroupMatch && this.core.hasValue(inputGroupMatch.sys_id)) {
                finalGroup = inputGroupMatch.sys_id;
            }
        }

        if (!this.core.hasValue(finalGroup)) {
            dummyGroup = this.core.getDefaultAssignmentGroupSysId(ctx.debug);
            if (this.core.looksLikeSysId(dummyGroup)) {
                finalGroup = dummyGroup;
                ctx.resolved.dummy_assignment_group_used = true;
                this.core.traceNote(ctx.debug, 'dummy assignment_group used');
            }
        }

        if (this.core.hasValue(finalGroup)) {
            ctx.resolved.assignment_group_sys_id = finalGroup;
        }
    },

    resolveAll: function (ctx) {
        this.resolvePrimaryCmdbCi(ctx);
        this.resolveAssignmentAndCorrelations(ctx);
    },

    type: 'USBEM_Lookups'
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = USBEM_Lookups;
}


if (typeof Class === 'undefined') {
    var Class = {
        create: function () {
            return function () {
                if (typeof this.initialize === 'function') {
                    this.initialize.apply(this, arguments);
                }
            };
        }
    };
}

var USBEM_Debug = Class.create();
USBEM_Debug.prototype = {
    initialize: function (core) {
        this.core = core;
        this.ATTACHMENTS = [
            { key: 'raw_payload', name: '01_raw_payload.json', type: 'application/json' },
            { key: 'normalized_payload', name: '02_normalized_payload.json', type: 'application/json' },
            { key: 'mapped_event', name: '03_mapped_event.json', type: 'application/json' },
            { key: 'lookup_trace', name: '04_lookup_trace.json', type: 'application/json' },
            { key: 'candidate_scores', name: '05_candidate_scores.json', type: 'application/json' },
            { key: 'correlation_hints', name: '06_correlation_hints.json', type: 'application/json' },
            { key: 'performance', name: '07_performance.json', type: 'application/json' },
            { key: 'response_summary', name: '08_response_summary.json', type: 'application/json' },
            { key: 'dti_timeline', name: '09_dti_timeline.json', type: 'application/json' },
            { key: 'error_context', name: '10_error_context.json', type: 'application/json' }
        ];
    },

    shouldCreateDebugEvent: function (contexts, rawPayloadText) {
        var i;
        if (this.core.rawPayloadLooksDebugEnabled(rawPayloadText)) {
            return true;
        }
        if (!this.core.isArray(contexts)) {
            return false;
        }
        for (i = 0; i < contexts.length; i++) {
            if (contexts[i] && contexts[i].flags && contexts[i].flags.debug_enabled === true) {
                return true;
            }
        }
        return false;
    },

    buildPayloadSet: function (rawPayloadText, responseObject, contexts, errorText) {
        var normalizedPayload = [];
        var mappedEvent = [];
        var lookupTrace = [];
        var candidateScores = [];
        var correlationHints = [];
        var performance = [];
        var dtiTimeline = [];
        var i;
        var ctx;
        var out = {};

        out.raw_payload = this.core.hasValue(rawPayloadText) ? String(rawPayloadText) : '';

        for (i = 0; i < contexts.length; i++) {
            ctx = contexts[i];
            if (!ctx) {
                continue;
            }

            normalizedPayload.push({
                record_index: i,
                normalized_input: this.core.deepClone(ctx.snapshots.normalized_input || {}),
                raw_event: this.core.deepClone(ctx.raw_event || {})
            });

            mappedEvent.push({
                record_index: i,
                event_sys_id: ctx.result ? ctx.result.event_sys_id : '',
                final_event: this.core.deepClone(ctx.snapshots.final_event || {})
            });

            lookupTrace.push({
                record_index: i,
                steps: this.core.deepClone((ctx.debug && ctx.debug.steps) ? ctx.debug.steps : []),
                lookups: this.core.deepClone((ctx.debug && ctx.debug.lookups) ? ctx.debug.lookups : {}),
                notes: this.core.deepClone((ctx.debug && ctx.debug.notes) ? ctx.debug.notes : []),
                errors: this.core.deepClone((ctx.debug && ctx.debug.errors) ? ctx.debug.errors : [])
            });

            candidateScores.push({
                record_index: i,
                candidates: this.core.deepClone((ctx.debug && ctx.debug.candidates) ? ctx.debug.candidates : {})
            });

            correlationHints.push({
                record_index: i,
                event_sys_id: ctx.result ? ctx.result.event_sys_id : '',
                message_key: ctx.mapped ? ctx.mapped.message_key : '',
                source: ctx.mapped ? ctx.mapped.source : '',
                event_class: ctx.mapped ? ctx.mapped.event_class : '',
                node: ctx.mapped ? ctx.mapped.node : '',
                resource: ctx.mapped ? ctx.mapped.resource : '',
                ci_type: ctx.mapped ? ctx.mapped.ci_type : '',
                cmdb_ci: ctx.resolved ? ctx.resolved.cmdb_ci_sys_id : '',
                assignment_group: ctx.resolved ? ctx.resolved.assignment_group_sys_id : '',
                cmdb_ci_service: ctx.resolved ? ctx.resolved.cmdb_ci_service : '',
                cmdb_ci_service_offering: ctx.resolved ? ctx.resolved.cmdb_ci_service_offering : '',
                cmdb_ci_business_app: ctx.resolved ? ctx.resolved.cmdb_ci_business_app : '',
                dummy_ci_used: ctx.resolved ? ctx.resolved.dummy_ci_used === true : false,
                dummy_assignment_group_used: ctx.resolved ? ctx.resolved.dummy_assignment_group_used === true : false
            });

            performance.push({
                record_index: i,
                processing_ms: ctx.result ? ctx.result.usbem_processing_ms : '',
                perf: this.core.deepClone((ctx.debug && ctx.debug.perf) ? ctx.debug.perf : {}),
                quality: this.core.deepClone((ctx.debug && ctx.debug.quality) ? ctx.debug.quality : {})
            });

            if ((ctx.flags && (ctx.flags.usbem_wait_for_alert || ctx.flags.dti_wait_for_incident || ctx.flags.direct_to_incident))) {
                dtiTimeline.push({
                    record_index: i,
                    direct_to_incident: ctx.flags.direct_to_incident === true,
                    wait_for_alert: ctx.flags.usbem_wait_for_alert === true,
                    wait_for_incident: ctx.flags.dti_wait_for_incident === true,
                    dti: this.core.deepClone(ctx.dti || {}),
                    result: this.core.deepClone(ctx.result || {})
                });
            }
        }

        out.normalized_payload = this.core.safeJSONStringify(normalizedPayload);
        out.mapped_event = this.core.safeJSONStringify(mappedEvent);
        out.lookup_trace = this.core.safeJSONStringify(lookupTrace);
        out.candidate_scores = this.core.safeJSONStringify(candidateScores);
        out.correlation_hints = this.core.safeJSONStringify(correlationHints);
        out.performance = this.core.safeJSONStringify(performance);
        out.response_summary = this.core.safeJSONStringify(responseObject || {});
        if (dtiTimeline.length > 0) {
            out.dti_timeline = this.core.safeJSONStringify(dtiTimeline);
        }
        if (this.core.hasValue(errorText)) {
            out.error_context = this.core.safeJSONStringify({ error: String(errorText) });
        }

        return out;
    },

    createDebugEvent: function (rawPayloadText, responseObject, contexts, errorText) {
        var payloads;
        var parentEventIds = [];
        var parentMessageKeys = [];
        var i;
        var debugAi = {};
        var debugGr;
        var attachGr;
        var attachment;
        var debugSysId = '';
        var title = 'USBEM debug capture';
        var ctx;

        if (!this.shouldCreateDebugEvent(contexts, rawPayloadText)) {
            return '';
        }

        payloads = this.buildPayloadSet(rawPayloadText, responseObject, contexts || [], errorText);

        for (i = 0; i < contexts.length; i++) {
            ctx = contexts[i];
            if (ctx && ctx.result && this.core.hasValue(ctx.result.event_sys_id)) {
                parentEventIds.push(String(ctx.result.event_sys_id));
            }
            if (ctx && ctx.mapped && this.core.hasValue(ctx.mapped.message_key)) {
                parentMessageKeys.push(String(ctx.mapped.message_key));
            }
        }

        if (parentEventIds.length > 0) {
            title += ' for ' + parentEventIds.length + ' event(s)';
        }

        debugAi.usbem_debug_capture_mode = 'late_companion_event';
        debugAi.usbem_version = this.core.VERSION;
        if (parentEventIds.length > 0) {
            debugAi.usbem_debug_parent_event_sys_ids = parentEventIds.join(',');
        }
        if (parentMessageKeys.length > 0) {
            debugAi.usbem_debug_parent_message_keys = parentMessageKeys.join(',');
        }

        debugGr = new GlideRecord('em_event');
        debugGr.initialize();
        this.core.setIfPresent(debugGr, 'source', this.core.DEBUG_EVENT_SOURCE);
        this.core.setIfPresent(debugGr, 'event_class', this.core.DEBUG_EVENT_CLASS);
        this.core.setIfPresent(debugGr, 'severity', this.core.DEBUG_EVENT_SEVERITY);
        this.core.setIfPresent(debugGr, 'description', this.core.truncateString(title, 4000));
        if (debugGr.isValidField('message_key')) {
            debugGr.setValue('message_key', this.core.truncateString('USBEM_DEBUG_' + gs.generateGUID(), this.core.MESSAGE_KEY_MAX));
        }
        if (debugGr.isValidField('time_of_event')) {
            debugGr.setValue('time_of_event', new GlideDateTime().getValue());
        }
        if (debugGr.isValidField('state')) {
            try {
                debugGr.setDisplayValue('state', this.core.DEBUG_EVENT_STATE);
            } catch (eState) {
                debugGr.setValue('state', this.core.DEBUG_EVENT_STATE);
            }
        }
        debugGr.setValue('additional_info', this.core.buildAdditionalInfoString(debugAi));
        debugSysId = debugGr.insert();

        if (!this.core.hasValue(debugSysId)) {
            return '';
        }

        attachGr = new GlideRecord('em_event');
        if (!attachGr.get(debugSysId)) {
            return debugSysId;
        }

        attachment = new GlideSysAttachment();
        for (i = 0; i < this.ATTACHMENTS.length; i++) {
            if (this.core.hasValue(payloads[this.ATTACHMENTS[i].key])) {
                try {
                    attachment.write(
                        attachGr,
                        this.ATTACHMENTS[i].name,
                        this.ATTACHMENTS[i].type,
                        payloads[this.ATTACHMENTS[i].key]
                    );
                } catch (eAttach) {
                }
            }
        }

        return debugSysId;
    },

    type: 'USBEM_Debug'
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = USBEM_Debug;
}


if (typeof Class === 'undefined') {
    var Class = {
        create: function () {
            return function () {
                if (typeof this.initialize === 'function') {
                    this.initialize.apply(this, arguments);
                }
            };
        }
    };
}

var USBEM_DTI = Class.create();
USBEM_DTI.prototype = {
    initialize: function (core) {
        this.core = core;
        this.PROPERTY_FAST_DTI_EVENT_NAME = 'x_usbna_usb_event.fast_dti_event_name';
        this.PROPERTY_FAST_DTI_INLINE_WAIT_SECONDS = 'x_usbna_usb_event.fast_dti_inline_wait_seconds';
        this.PROPERTY_FAST_DTI_LINK_DELAY_SECONDS = 'x_usbna_usb_event.fast_dti_link_delay_seconds';
        this.PROPERTY_FAST_DTI_LINK_MAX_RETRIES = 'x_usbna_usb_event.fast_dti_link_max_retries';
        this.PROPERTY_DTI_MAP_TABLE = 'x_usbna_usb_event.dti_map_table';
        this.PROPERTY_DTI_MAP_PENDING_WAIT_MS = 'x_usbna_usb_event.dti_map_pending_wait_ms';

        this.DEFAULT_FAST_DTI_EVENT_NAME = 'x_usbna_usb_event.link_alert_later';
        this.DEFAULT_FAST_DTI_INLINE_WAIT_SECONDS = 20;
        this.DEFAULT_FAST_DTI_LINK_DELAY_SECONDS = 10;
        this.DEFAULT_FAST_DTI_LINK_MAX_RETRIES = 6;
        this.DEFAULT_DTI_MAP_PENDING_WAIT_MS = 1500;
        this.PENDING_MAP_POLL_MS = 100;
    },

    queryNow: function (gr, trace) {
        this.core.bumpMetric(trace, 'query_count', 1);
        gr.query();
    },

    getStringProperty: function (name, defaultValue, trace) {
        return this.core.trimToString(this.core.getProperty(name, defaultValue, trace));
    },

    getIntProperty: function (name, defaultValue, trace) {
        return this.core.toInt(this.core.getProperty(name, String(defaultValue), trace), defaultValue);
    },

    getFastDtiEventName: function (trace) {
        return this.getStringProperty(this.PROPERTY_FAST_DTI_EVENT_NAME, this.DEFAULT_FAST_DTI_EVENT_NAME, trace);
    },

    getFastDtiInlineWaitSeconds: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_FAST_DTI_INLINE_WAIT_SECONDS, this.DEFAULT_FAST_DTI_INLINE_WAIT_SECONDS, trace);
        if (n < 0) {
            n = this.DEFAULT_FAST_DTI_INLINE_WAIT_SECONDS;
        }
        return n;
    },

    getFastDtiLinkDelaySeconds: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_FAST_DTI_LINK_DELAY_SECONDS, this.DEFAULT_FAST_DTI_LINK_DELAY_SECONDS, trace);
        if (n < 0) {
            n = this.DEFAULT_FAST_DTI_LINK_DELAY_SECONDS;
        }
        return n;
    },

    getFastDtiLinkMaxRetries: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_FAST_DTI_LINK_MAX_RETRIES, this.DEFAULT_FAST_DTI_LINK_MAX_RETRIES, trace);
        if (n < 0) {
            n = this.DEFAULT_FAST_DTI_LINK_MAX_RETRIES;
        }
        return n;
    },

    getDtiMapPendingWaitMs: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_DTI_MAP_PENDING_WAIT_MS, this.DEFAULT_DTI_MAP_PENDING_WAIT_MS, trace);
        if (n < 0) {
            n = this.DEFAULT_DTI_MAP_PENDING_WAIT_MS;
        }
        return n;
    },

    getDtiMapTable: function (trace) {
        var tableName = this.getStringProperty(this.PROPERTY_DTI_MAP_TABLE, '', trace);
        if (!this.core.hasValue(tableName)) {
            return '';
        }
        if (!this.core.tableExists(tableName, trace)) {
            return '';
        }
        return tableName;
    },

    getEventBySysId: function (eventSysId) {
        var gr;
        if (!this.core.looksLikeSysId(eventSysId) || !this.core.tableExists('em_event')) {
            return null;
        }
        gr = new GlideRecord('em_event');
        if (gr.get(eventSysId)) {
            return gr;
        }
        return null;
    },

    getAlertBySysId: function (alertSysId) {
        var gr;
        if (!this.core.looksLikeSysId(alertSysId) || !this.core.tableExists('em_alert')) {
            return null;
        }
        gr = new GlideRecord('em_alert');
        if (gr.get(alertSysId)) {
            return gr;
        }
        return null;
    },

    getAlertFromEvent: function (eventGr) {
        var alertSysId;
        if (!eventGr || !eventGr.isValidField('alert')) {
            return null;
        }
        alertSysId = eventGr.getValue('alert');
        if (!this.core.looksLikeSysId(alertSysId)) {
            return null;
        }
        return this.getAlertBySysId(alertSysId);
    },

    getEventStateInfo: function (eventGr) {
        var rawValue = '';
        var displayValue = '';
        var normalized = '';
        if (eventGr && eventGr.isValidField('state')) {
            rawValue = eventGr.getValue('state') || '';
            displayValue = eventGr.getDisplayValue('state') || rawValue || '';
        }
        normalized = this.core.normalizeKey(displayValue || rawValue);
        return {
            raw: rawValue,
            display: displayValue,
            normalized: normalized
        };
    },

    isReadyEventState: function (stateInfo) {
        if (!stateInfo) {
            return true;
        }
        return stateInfo.normalized === '' || stateInfo.normalized === 'ready';
    },

    findAlertByMessageKey: function (messageKey, source, eventClass, trace) {
        var gr;
        if (!this.core.hasValue(messageKey) || !this.core.tableExists('em_alert', trace)) {
            return null;
        }
        gr = new GlideRecord('em_alert');
        if (!gr.isValidField('message_key')) {
            return null;
        }
        gr.addQuery('message_key', messageKey);
        if (this.core.hasValue(source) && gr.isValidField('source')) {
            gr.addQuery('source', source);
        }
        if (this.core.hasValue(eventClass) && gr.isValidField('event_class')) {
            gr.addQuery('event_class', eventClass);
        }
        if (gr.isValidField('sys_updated_on')) {
            gr.orderByDesc('sys_updated_on');
        }
        if (gr.isValidField('sys_created_on')) {
            gr.orderByDesc('sys_created_on');
        }
        gr.setLimit(1);
        this.queryNow(gr, trace);
        if (gr.next()) {
            return gr;
        }
        return null;
    },

    waitForAlert: function (ctx) {
        var deadlineMs = new Date().getTime() + ctx.flags.wait_ms;
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
            nextPollAt = now + this.core.WAIT_ALERT_POLL_MS;

            if (this.core.looksLikeSysId(ctx.result.event_sys_id)) {
                eventGr = this.getEventBySysId(ctx.result.event_sys_id);
                if (eventGr) {
                    stateInfo = this.getEventStateInfo(eventGr);
                    if ((stateInfo.display || stateInfo.raw) !== lastState) {
                        lastState = stateInfo.display || stateInfo.raw || '';
                        if (this.core.hasValue(lastState)) {
                            this.core.tracePush(ctx.debug, 'event state observed: ' + lastState);
                        }
                    }

                    alertGr = this.getAlertFromEvent(eventGr);
                    if (alertGr) {
                        this.core.tracePush(ctx.debug, 'alert located via em_event.alert');
                        return alertGr;
                    }

                    if (!this.isReadyEventState(stateInfo) && this.core.hasValue(ctx.mapped.message_key)) {
                        alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
                        if (alertGr) {
                            this.core.tracePush(ctx.debug, 'alert located by message_key after event left Ready');
                            return alertGr;
                        }
                    }
                }
            }

            if (this.core.hasValue(ctx.mapped.message_key)) {
                alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
                if (alertGr) {
                    this.core.tracePush(ctx.debug, 'alert located by message_key');
                    return alertGr;
                }
            }
        }

        if (this.core.hasValue(ctx.mapped.message_key)) {
            alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
            if (alertGr) {
                return alertGr;
            }
        }
        if (this.core.looksLikeSysId(ctx.result.event_sys_id)) {
            eventGr = this.getEventBySysId(ctx.result.event_sys_id);
            if (eventGr) {
                alertGr = this.getAlertFromEvent(eventGr);
                if (alertGr) {
                    return alertGr;
                }
            }
        }
        this.core.tracePush(ctx.debug, 'alert wait timed out');
        return null;
    },

    getIncidentFromAlert: function (alertGr) {
        var sysId;
        var inc;

        if (!alertGr) {
            return null;
        }
        if (alertGr.isValidField('incident')) {
            sysId = alertGr.getValue('incident');
            if (this.core.looksLikeSysId(sysId)) {
                inc = new GlideRecord('incident');
                if (inc.get(sysId)) {
                    return inc;
                }
            }
        }
        if (alertGr.isValidField('task')) {
            sysId = alertGr.getValue('task');
            if (this.core.looksLikeSysId(sysId)) {
                inc = new GlideRecord('incident');
                if (inc.get(sysId)) {
                    return inc;
                }
            }
        }
        return null;
    },

    waitForIncidentOnAlert: function (ctx, alertGr) {
        var deadlineMs = new Date().getTime() + ctx.flags.wait_ms;
        var alertSysId;
        var now;
        var nextPollAt = 0;
        var refreshedAlert;
        var incidentGr;

        if (!alertGr) {
            return null;
        }

        incidentGr = this.getIncidentFromAlert(alertGr);
        if (incidentGr) {
            this.core.tracePush(ctx.debug, 'incident already linked on alert');
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
            nextPollAt = now + this.core.WAIT_ALERT_POLL_MS;

            refreshedAlert = this.getAlertBySysId(alertSysId);
            if (!refreshedAlert) {
                break;
            }

            incidentGr = this.getIncidentFromAlert(refreshedAlert);
            if (incidentGr) {
                this.core.tracePush(ctx.debug, 'incident linked on alert after polling');
                return incidentGr;
            }
        }

        refreshedAlert = this.getAlertBySysId(alertSysId);
        if (refreshedAlert) {
            incidentGr = this.getIncidentFromAlert(refreshedAlert);
            if (incidentGr) {
                return incidentGr;
            }
        }

        this.core.tracePush(ctx.debug, 'incident wait timed out on alert');
        return null;
    },

    setWorkNotesIfPresent: function (incGr, value) {
        if (!this.core.hasValue(value)) {
            return;
        }
        if (incGr.isValidField('work_notes')) {
            incGr.setValue('work_notes', String(value));
        } else if (incGr.isValidField('comments')) {
            incGr.setValue('comments', String(value));
        }
    },

    setCorrelationIfPresent: function (incGr, ctx) {
        if (!ctx || !ctx.mapped || !this.core.hasValue(ctx.mapped.message_key)) {
            return;
        }
        if (incGr.isValidField('correlation_id')) {
            incGr.setValue('correlation_id', ctx.mapped.message_key);
        }
        if (incGr.isValidField('correlation_display')) {
            incGr.setValue('correlation_display', 'USBEM DTI');
        }
    },

    claimAlertForIncident: function (alertSysId, incidentSysId) {
        var claimGr;
        if (!this.core.looksLikeSysId(alertSysId) || !this.core.looksLikeSysId(incidentSysId)) {
            return { claimed: false, incident: null };
        }

        claimGr = new GlideRecord('em_alert');
        claimGr.addQuery('sys_id', alertSysId);
        if (claimGr.isValidField('task')) {
            claimGr.addNullQuery('task');
        } else if (claimGr.isValidField('incident')) {
            claimGr.addNullQuery('incident');
        }
        claimGr.setLimit(1);
        this.queryNow(claimGr);
        if (!claimGr.next()) {
            claimGr = new GlideRecord('em_alert');
            if (claimGr.get(alertSysId)) {
                return { claimed: false, incident: this.getIncidentFromAlert(claimGr) };
            }
            return { claimed: false, incident: null };
        }

        if (claimGr.isValidField('incident')) {
            claimGr.setValue('incident', incidentSysId);
        }
        if (claimGr.isValidField('task')) {
            claimGr.setValue('task', incidentSysId);
        }
        claimGr.update();
        return { claimed: true, incident: null };
    },

    createIncidentRecord: function (ctx) {
        var inc;
        var sysId;
        var shortDescription;
        var description;
        var incident;

        if (!this.core.tableExists('incident', ctx.debug)) {
            return null;
        }

        inc = new GlideRecord('incident');
        inc.initialize();

        shortDescription = this.core.hasValue(ctx.special.dti_short_description) ? ctx.special.dti_short_description : ctx.mapped.description;
        description = ctx.mapped.description;

        this.core.setIfPresent(inc, 'short_description', this.core.truncateString(shortDescription, 160));
        this.core.setIfPresent(inc, 'description', this.core.truncateString(description, 4000));
        this.core.setIfPresent(inc, 'impact', ctx.dti.impact);
        this.core.setIfPresent(inc, 'urgency', ctx.dti.urgency);
        this.setCorrelationIfPresent(inc, ctx);

        if (this.core.hasValue(ctx.resolved.assignment_group_sys_id) && this.core.looksLikeSysId(ctx.resolved.assignment_group_sys_id)) {
            this.core.setIfPresent(inc, 'assignment_group', ctx.resolved.assignment_group_sys_id);
        }
        if (this.core.hasValue(ctx.resolved.cmdb_ci_sys_id) && this.core.looksLikeSysId(ctx.resolved.cmdb_ci_sys_id)) {
            this.core.setIfPresent(inc, 'cmdb_ci', ctx.resolved.cmdb_ci_sys_id);
        }
        if (this.core.hasValue(ctx.resolved.cmdb_ci_service) && this.core.looksLikeSysId(ctx.resolved.cmdb_ci_service)) {
            if (inc.isValidField('business_service')) {
                inc.setValue('business_service', ctx.resolved.cmdb_ci_service);
            } else if (inc.isValidField('service')) {
                inc.setValue('service', ctx.resolved.cmdb_ci_service);
            }
        }
        if (this.core.hasValue(ctx.resolved.cmdb_ci_service_offering) && this.core.looksLikeSysId(ctx.resolved.cmdb_ci_service_offering) && inc.isValidField('service_offering')) {
            inc.setValue('service_offering', ctx.resolved.cmdb_ci_service_offering);
        }

        this.setWorkNotesIfPresent(inc, ctx.special.dti_work_note);

        sysId = inc.insert();
        if (!this.core.looksLikeSysId(sysId)) {
            return null;
        }

        incident = new GlideRecord('incident');
        if (incident.get(sysId)) {
            return incident;
        }
        return null;
    },

    deleteIncidentBestEffort: function (incidentGr) {
        try {
            if (incidentGr && incidentGr.isValidRecord && incidentGr.isValidRecord()) {
                incidentGr.deleteRecord();
            }
        } catch (e) {
        }
    },

    createOrReuseIncidentForAlert: function (ctx, alertGr) {
        var existingIncident;
        var createdIncident;
        var claim;
        var refreshedAlert;

        if (!alertGr) {
            return { incident: null, status: 'alert_not_found' };
        }

        refreshedAlert = this.getAlertBySysId(alertGr.getUniqueValue());
        existingIncident = this.getIncidentFromAlert(refreshedAlert || alertGr);
        if (existingIncident) {
            return { incident: existingIncident, status: 'existing' };
        }

        if (!ctx.dti.allow_incident) {
            return { incident: null, status: 'suppressed_by_severity_map' };
        }

        existingIncident = this.getExistingIncidentByCorrelationId(ctx.mapped.message_key, ctx.debug);
        if (existingIncident) {
            claim = this.claimAlertForIncident(alertGr.getUniqueValue(), existingIncident.getUniqueValue());
            if (claim.claimed) {
                this.core.tracePush(ctx.debug, 'existing incident claimed onto alert by correlation_id');
                return { incident: existingIncident, status: 'existing_from_correlation_id' };
            }
            if (claim.incident) {
                this.core.tracePush(ctx.debug, 'alert already linked while claiming existing correlation incident');
                return { incident: claim.incident, status: 'existing_after_race' };
            }
        }

        createdIncident = this.createIncidentRecord(ctx);
        if (!createdIncident) {
            return { incident: null, status: 'create_failed' };
        }

        claim = this.claimAlertForIncident(alertGr.getUniqueValue(), createdIncident.getUniqueValue());
        if (claim.claimed) {
            this.core.tracePush(ctx.debug, 'incident created and linked: ' + createdIncident.getUniqueValue());
            return { incident: createdIncident, status: 'created' };
        }

        if (claim.incident) {
            this.core.tracePush(ctx.debug, 'incident race detected, existing linked incident reused');
            this.deleteIncidentBestEffort(createdIncident);
            return { incident: claim.incident, status: 'existing_after_race' };
        }

        return { incident: createdIncident, status: 'created_unlinked' };
    },

    getExistingIncidentByCorrelationId: function (messageKey, trace) {
        var gr;
        if (!this.core.hasValue(messageKey) || !this.core.tableExists('incident', trace)) {
            return null;
        }
        gr = new GlideRecord('incident');
        if (!gr.isValidField('correlation_id')) {
            return null;
        }
        gr.addQuery('correlation_id', messageKey);
        if (gr.isValidField('sys_updated_on')) {
            gr.orderByDesc('sys_updated_on');
        }
        if (gr.isValidField('sys_created_on')) {
            gr.orderByDesc('sys_created_on');
        }
        gr.setLimit(1);
        this.queryNow(gr, trace);
        if (gr.next()) {
            return gr;
        }
        return null;
    },

    getMapRowByMessageKey: function (tableName, messageKey, trace) {
        var gr;
        if (!this.core.hasValue(tableName) || !this.core.hasValue(messageKey)) {
            return null;
        }
        gr = new GlideRecord(tableName);
        if (!gr.isValidField('u_message_key')) {
            return null;
        }
        gr.addQuery('u_message_key', messageKey);
        if (gr.isValidField('sys_updated_on')) {
            gr.orderByDesc('sys_updated_on');
        }
        gr.setLimit(1);
        this.queryNow(gr, trace);
        if (gr.next()) {
            return gr;
        }
        return null;
    },

    insertPendingMapRow: function (tableName, messageKey, eventSysId, trace) {
        var gr;
        var sysId = '';
        if (!this.core.hasValue(tableName) || !this.core.hasValue(messageKey)) {
            return { owner: false, row: null };
        }

        gr = new GlideRecord(tableName);
        gr.initialize();
        if (gr.isValidField('u_message_key')) {
            gr.setValue('u_message_key', messageKey);
        }
        if (this.core.looksLikeSysId(eventSysId) && gr.isValidField('u_last_event')) {
            gr.setValue('u_last_event', eventSysId);
        }
        if (gr.isValidField('u_state')) {
            gr.setValue('u_state', 'pending');
        }
        if (gr.isValidField('u_last_status')) {
            gr.setValue('u_last_status', 'pending');
        }

        try {
            sysId = gr.insert();
        } catch (eInsert) {
            sysId = '';
        }

        if (this.core.looksLikeSysId(sysId)) {
            gr = new GlideRecord(tableName);
            if (gr.get(sysId)) {
                return { owner: true, row: gr };
            }
        }

        gr = this.getMapRowByMessageKey(tableName, messageKey, trace);
        return { owner: false, row: gr };
    },

    updateMapRowIncident: function (rowGr, incidentSysId, eventSysId, statusValue) {
        if (!rowGr || !rowGr.isValidRecord || !rowGr.isValidRecord()) {
            return;
        }
        if (this.core.looksLikeSysId(incidentSysId) && rowGr.isValidField('u_incident')) {
            rowGr.setValue('u_incident', incidentSysId);
        }
        if (this.core.looksLikeSysId(eventSysId) && rowGr.isValidField('u_last_event')) {
            rowGr.setValue('u_last_event', eventSysId);
        }
        if (rowGr.isValidField('u_state')) {
            rowGr.setValue('u_state', this.core.hasValue(incidentSysId) ? 'linked' : 'pending');
        }
        if (rowGr.isValidField('u_last_status')) {
            rowGr.setValue('u_last_status', statusValue || '');
        }
        rowGr.update();
    },

    waitForMapIncident: function (tableName, rowSysId, trace) {
        var deadlineMs;
        var nextPollAt = 0;
        var now;
        var rowGr;
        var incidentGr;
        if (!this.core.hasValue(tableName) || !this.core.looksLikeSysId(rowSysId)) {
            return null;
        }

        deadlineMs = new Date().getTime() + this.getDtiMapPendingWaitMs(trace);

        while (true) {
            now = new Date().getTime();
            if (now >= deadlineMs) {
                break;
            }
            if (now < nextPollAt) {
                continue;
            }
            nextPollAt = now + this.PENDING_MAP_POLL_MS;
            rowGr = new GlideRecord(tableName);
            if (!rowGr.get(rowSysId)) {
                break;
            }
            if (rowGr.isValidField('u_incident')) {
                incidentGr = new GlideRecord('incident');
                if (incidentGr.get(rowGr.getValue('u_incident'))) {
                    return incidentGr;
                }
            }
        }

        rowGr = new GlideRecord(tableName);
        if (rowGr.get(rowSysId) && rowGr.isValidField('u_incident')) {
            incidentGr = new GlideRecord('incident');
            if (incidentGr.get(rowGr.getValue('u_incident'))) {
                return incidentGr;
            }
        }

        return null;
    },

    upsertMapWithIncident: function (messageKey, incidentSysId, eventSysId, trace) {
        var tableName = this.getDtiMapTable(trace);
        var row;
        var inserted;
        if (!this.core.hasValue(tableName) || !this.core.hasValue(messageKey) || !this.core.looksLikeSysId(incidentSysId)) {
            return;
        }
        row = this.getMapRowByMessageKey(tableName, messageKey, trace);
        if (!row) {
            inserted = this.insertPendingMapRow(tableName, messageKey, eventSysId, trace);
            row = inserted.row;
        }
        if (row) {
            this.updateMapRowIncident(row, incidentSysId, eventSysId, 'incident_ready');
        }
    },

    getFastDtiInlineWaitMs: function (ctx) {
        var waitMs = ctx && ctx.flags ? this.core.toInt(ctx.flags.wait_ms, 0) : 0;
        if (waitMs > 0) {
            return waitMs;
        }
        return this.getFastDtiInlineWaitSeconds(ctx ? ctx.debug : null) * 1000;
    },

    waitForAlertForFastDti: function (ctx) {
        return this.waitForAlert({
            flags: { wait_ms: this.getFastDtiInlineWaitMs(ctx) },
            result: { event_sys_id: ctx.result.event_sys_id || '' },
            mapped: {
                message_key: ctx.mapped.message_key || '',
                source: ctx.mapped.source || '',
                event_class: ctx.mapped.event_class || ''
            },
            debug: ctx.debug
        });
    },

    buildAsyncLinkPayload: function (ctx, incidentGr, retryCount) {
        return this.core.safeJSONStringify({
            event_sys_id: ctx.result.event_sys_id || '',
            message_key: ctx.mapped.message_key || '',
            source: ctx.mapped.source || '',
            event_class: ctx.mapped.event_class || '',
            description: ctx.mapped.description || '',
            short_description: ctx.special.dti_short_description || '',
            impact: ctx.dti.impact || '',
            urgency: ctx.dti.urgency || '',
            allow_incident: ctx.dti.allow_incident === true,
            assignment_group_sys_id: ctx.resolved.assignment_group_sys_id || '',
            cmdb_ci_sys_id: ctx.resolved.cmdb_ci_sys_id || '',
            cmdb_ci_service: ctx.resolved.cmdb_ci_service || '',
            cmdb_ci_service_offering: ctx.resolved.cmdb_ci_service_offering || '',
            dti_work_note: ctx.special.dti_work_note || '',
            retry_count: typeof retryCount === 'number' ? retryCount : 0
        });
    },

    parseAsyncLinkPayload: function (parm1, parm2) {
        var parsed = this.core.tryParseJSON(parm2);
        var out = this.core.isObject(parsed) ? parsed : {};
        if (!this.core.hasValue(out.event_sys_id) && this.core.hasValue(parm1)) {
            out.event_sys_id = String(parm1);
        }
        if (!this.core.hasValue(out.retry_count)) {
            out.retry_count = 0;
        } else {
            out.retry_count = this.core.toInt(out.retry_count, 0);
        }
        return out;
    },

    buildAsyncIncidentContext: function (payload) {
        return {
            mapped: {
                message_key: payload.message_key || '',
                source: payload.source || '',
                event_class: payload.event_class || '',
                description: payload.description || ''
            },
            special: {
                dti_short_description: payload.short_description || '',
                dti_work_note: payload.dti_work_note || ''
            },
            dti: {
                impact: payload.impact || '',
                urgency: payload.urgency || '',
                allow_incident: !(payload.allow_incident === false || String(payload.allow_incident) === 'false')
            },
            resolved: {
                assignment_group_sys_id: payload.assignment_group_sys_id || '',
                cmdb_ci_sys_id: payload.cmdb_ci_sys_id || '',
                cmdb_ci_service: payload.cmdb_ci_service || '',
                cmdb_ci_service_offering: payload.cmdb_ci_service_offering || ''
            },
            result: {
                event_sys_id: payload.event_sys_id || ''
            },
            debug: null
        };
    },

    getAsyncAnchorRecord: function (currentGr, payload) {
        if (currentGr && currentGr.isValidRecord && currentGr.isValidRecord()) {
            return currentGr;
        }
        if (payload && this.core.looksLikeSysId(payload.event_sys_id)) {
            return this.getEventBySysId(payload.event_sys_id);
        }
        return null;
    },

    queueScheduledLinkEvent: function (anchorGr, payload, trace) {
        var eventName;
        var delaySeconds;
        var processTime;
        var payloadText;
        if (!anchorGr || !anchorGr.isValidRecord || !anchorGr.isValidRecord()) {
            return false;
        }

        eventName = this.getFastDtiEventName(trace);
        if (!this.core.hasValue(eventName)) {
            return false;
        }
        delaySeconds = this.getFastDtiLinkDelaySeconds(trace);
        payloadText = this.core.isObject(payload) ? this.core.safeJSONStringify(payload) : String(payload || '');

        try {
            if (typeof gs.eventQueueScheduled === 'function') {
                processTime = new GlideDateTime();
                processTime.addSecondsLocalTime(delaySeconds);
                gs.eventQueueScheduled(eventName, anchorGr, payload.event_sys_id || '', payloadText, processTime);
            } else {
                gs.eventQueue(eventName, anchorGr, payload.event_sys_id || '', payloadText);
            }
            return true;
        } catch (eQueue) {
            try {
                gs.eventQueue(eventName, anchorGr, payload.event_sys_id || '', payloadText);
                return true;
            } catch (eQueueFallback) {
                return false;
            }
        }
    },

    queueAlertLinkLater: function (ctx, incidentGr) {
        var eventGr;
        var payload;
        var queued;
        if (!this.core.looksLikeSysId(ctx.result.event_sys_id)) {
            return false;
        }
        eventGr = this.getEventBySysId(ctx.result.event_sys_id);
        if (!eventGr) {
            return false;
        }
        payload = this.parseAsyncLinkPayload(ctx.result.event_sys_id, this.buildAsyncLinkPayload(ctx, incidentGr, 0));
        queued = this.queueScheduledLinkEvent(eventGr, payload, ctx.debug);
        if (queued) {
            ctx.result.dti_link_status = 'queued';
            ctx.result.dti_link_event_name = this.getFastDtiEventName(ctx.debug);
        } else {
            ctx.result.dti_link_status = 'queue_failed';
        }
        return queued;
    },

    relinkAlertToIncidentAsync: function (currentGr, parm1, parm2) {
        var payload;
        var anchorGr;
        var alertGr = null;
        var ctx;
        var outcome;
        var maxRetries;
        var shouldRetry = false;

        payload = this.parseAsyncLinkPayload(parm1, parm2);
        anchorGr = this.getAsyncAnchorRecord(currentGr, payload);

        if (this.core.looksLikeSysId(payload.event_sys_id)) {
            alertGr = this.getAlertFromEvent(this.getEventBySysId(payload.event_sys_id));
        }
        if (!alertGr && this.core.hasValue(payload.message_key)) {
            alertGr = this.findAlertByMessageKey(payload.message_key, payload.source, payload.event_class);
        }

        if (!alertGr) {
            maxRetries = this.getFastDtiLinkMaxRetries();
            if (payload.retry_count < maxRetries) {
                payload.retry_count = payload.retry_count + 1;
                shouldRetry = this.queueScheduledLinkEvent(anchorGr, payload);
                return {
                    status: shouldRetry ? 'retry_queued' : 'alert_not_found',
                    retry_count: String(payload.retry_count)
                };
            }
            return {
                status: 'alert_not_found',
                retry_count: String(payload.retry_count)
            };
        }

        ctx = this.buildAsyncIncidentContext(payload);
        outcome = this.createOrReuseIncidentForAlert(ctx, alertGr);
        if (outcome.incident) {
            this.upsertMapWithIncident(payload.message_key, outcome.incident.getUniqueValue(), payload.event_sys_id, null);
            return {
                status: outcome.status || 'existing',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: outcome.incident.getUniqueValue()
            };
        }
        return {
            status: outcome.status || 'create_failed',
            alert_sys_id: alertGr.getUniqueValue()
        };
    },

    handleFastDti: function (ctx) {
        var alertGr;
        var outcome;
        if (!ctx.flags.direct_to_incident) {
            return ctx.result;
        }

        alertGr = this.waitForAlertForFastDti(ctx);
        if (alertGr) {
            this.core.mergeDeep(ctx.result, this.core.summarizeAlert(alertGr));
            outcome = this.createOrReuseIncidentForAlert(ctx, alertGr);
            ctx.result.dti_mode = 'inline_after_alert';
            ctx.result.dti_incident_status = outcome.status || '';
            if (outcome.incident) {
                this.core.mergeDeep(ctx.result, this.core.summarizeIncident(outcome.incident));
                this.upsertMapWithIncident(ctx.mapped.message_key, outcome.incident.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
            }
            return ctx.result;
        }

        ctx.result.dti_mode = 'deferred_after_response';
        if (!ctx.dti.allow_incident) {
            ctx.result.dti_incident_status = 'suppressed_by_severity_map';
            return ctx.result;
        }
        ctx.result.dti_incident_status = 'queued';
        this.queueAlertLinkLater(ctx, null);
        return ctx.result;
    },

    handlePostInsert: function (ctx) {
        var alertGr = null;
        var incidentGr = null;
        var dtiOutcome;

        if (ctx.flags.direct_to_incident && !ctx.flags.dti_wait_for_incident) {
            return this.handleFastDti(ctx);
        }

        if (ctx.flags.usbem_wait_for_alert) {
            alertGr = this.waitForAlert(ctx);
            if (alertGr) {
                this.core.mergeDeep(ctx.result, this.core.summarizeAlert(alertGr));
            } else {
                ctx.result.alert_wait_status = 'timeout';
            }
        }

        if (ctx.flags.direct_to_incident && ctx.flags.dti_wait_for_incident) {
            if (!alertGr) {
                alertGr = this.waitForAlert(ctx);
                if (alertGr) {
                    this.core.mergeDeep(ctx.result, this.core.summarizeAlert(alertGr));
                }
            }

            dtiOutcome = this.createOrReuseIncidentForAlert(ctx, alertGr);
            ctx.result.dti_mode = 'wait_for_incident';
            ctx.result.dti_incident_status = dtiOutcome.status || '';
            incidentGr = dtiOutcome.incident;
            if (incidentGr) {
                this.core.mergeDeep(ctx.result, this.core.summarizeIncident(incidentGr));
                this.upsertMapWithIncident(ctx.mapped.message_key, incidentGr.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
            }
        }

        return ctx.result;
    },

    type: 'USBEM_DTI'
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = USBEM_DTI;
}

(function process(/*RESTAPIRequest*/ request, body) {
    var core = new USBEM_Core({ request: request });
    var lookups = new USBEM_Lookups(core);
    var debugHelper = new USBEM_Debug(core);
    var rawPayloadText = '';

    try {
        rawPayloadText = (typeof body === 'string') ? body : core.safeJSONStringify(body);
    } catch (eRaw) {
        rawPayloadText = '';
    }

    function processSingleEvent(rawEvent, envelope) {
        var ctx = core.createRecordContext(rawEvent, envelope);
        var finalAdditionalInfo;
        var dtiHelper;

        lookups.resolveAll(ctx);

        finalAdditionalInfo = core.addOperationalAdditionalInfo(ctx);
        core.insertEventRecord(ctx, finalAdditionalInfo);

        if (ctx.flags.direct_to_incident || ctx.flags.wait_requested) {
            dtiHelper = new USBEM_DTI(core);
            dtiHelper.handlePostInsert(ctx);
        }

        if (ctx.flags.debug_enabled) {
            ctx.result.debug_enabled = 'true';
            ctx.result.debug_capture_mode = 'companion_event';
        }

        core.finalizeContext(ctx, finalAdditionalInfo);
        return ctx;
    }

    try {
        var payload = (typeof body === 'string') ? JSON.parse(body) : body;
        var envelope = {};
        var records = [];
        var contexts = [];
        var results = [];
        var i;
        var response;
        var debugEventSysId = '';

        if (core.isArray(payload)) {
            records = payload;
        } else if (core.isObject(payload) && core.isArray(payload.records)) {
            envelope = core.deepClone(payload);
            delete envelope.records;
            records = payload.records;
        } else if (core.isObject(payload) && core.isArray(payload.events)) {
            envelope = core.deepClone(payload);
            delete envelope.events;
            records = payload.events;
        } else {
            records = [payload];
        }

        for (i = 0; i < records.length; i++) {
            contexts.push(processSingleEvent(records[i], envelope));
            results.push(contexts[i].result);
        }

        response = {
            status: 'success',
            inserted: String(results.length),
            sys_ids: [],
            results: results,
            version: core.VERSION
        };

        for (i = 0; i < contexts.length; i++) {
            response.sys_ids.push(contexts[i].result.event_sys_id);
        }

        if (results.length === 1) {
            core.mergeDeep(response, results[0]);
        }

        debugEventSysId = debugHelper.createDebugEvent(rawPayloadText, response, contexts, '');
        if (core.hasValue(debugEventSysId)) {
            response.debug_raw_event_sys_id = debugEventSysId;
        }

        return JSON.stringify(response);
    } catch (er) {
        var errorResponse;
        var errorDebugEventSysId = '';

        gs.error('USBEM genericJsonV2 transform failed: ' + er);
        if (typeof status !== 'undefined') {
            status = 500;
        }

        errorResponse = {
            status: 'error',
            message: String(er),
            version: core.VERSION
        };

        errorDebugEventSysId = debugHelper.createDebugEvent(rawPayloadText, errorResponse, [], String(er));
        if (core.hasValue(errorDebugEventSysId)) {
            errorResponse.debug_raw_event_sys_id = errorDebugEventSysId;
        }

        return JSON.stringify(errorResponse);
    }
})(request, body);

