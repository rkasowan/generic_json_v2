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

