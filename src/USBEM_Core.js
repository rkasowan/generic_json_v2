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
