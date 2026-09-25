/*
 * Background Script: CI support tier fields for USBEM DTI.
 *
 * Creates the reference fields that USBEM_Lookups reads when picking the assignment group
 * for a DTI incident, in this order:
 *     cmdb_ci.support_group            (out of box)
 *     cmdb_ci.u_level_2_support_assignee_group
 *     cmdb_ci.u_level_3_support_assignee_group   (created here; add to the chain when wanted)
 *
 * Idempotent: an existing field is left alone except for its label, which is corrected.
 * Select the update set you want these captured in BEFORE running this.
 *
 * Note: adding a column to cmdb_ci alters every extended CI table and can run for several
 * minutes. Run it from the Scripts - Background UI rather than over a REST/HTTP client, so a
 * client-side timeout cannot cut the transaction short before the update set records are
 * written. That is exactly what happened on dev382837 on 2026-09-25: the columns were created
 * but nothing was captured.
 */
(function () {
    var DRY_RUN = false;                 // true prints the plan and writes nothing
    var TABLE = 'cmdb_ci';
    var REFERENCE = 'sys_user_group';
    var FIELDS = [
        { element: 'u_level_2_support_assignee_group', label: 'Level 2 Support Assignee Group' },
        { element: 'u_level_3_support_assignee_group', label: 'Level 3 Support Assignee Group' }
    ];

    var out = { table: TABLE, dry_run: DRY_RUN, fields: [] };

    function dictionaryRow(element) {
        var gr = new GlideRecord('sys_dictionary');
        gr.addQuery('name', TABLE);
        gr.addQuery('element', element);
        gr.setLimit(1);
        gr.query();
        return gr.next() ? gr : null;
    }

    for (var i = 0; i < FIELDS.length; i++) {
        var field = FIELDS[i];
        var existing = dictionaryRow(field.element);

        if (existing) {
            var currentType = String(existing.getValue('internal_type'));
            var currentRef = String(existing.getValue('reference'));
            var mismatch = (currentType !== 'reference' || currentRef !== REFERENCE);
            var entry = {
                element: field.element,
                action: mismatch ? 'left alone: type/reference differs' : 'already present',
                internal_type: currentType,
                reference: currentRef,
                sys_id: String(existing.getUniqueValue())
            };
            if (!mismatch && String(existing.getValue('column_label')) !== field.label) {
                entry.action = 'label corrected';
                if (!DRY_RUN) {
                    existing.setValue('column_label', field.label);
                    existing.update();
                }
            }
            out.fields.push(entry);
            continue;
        }

        if (DRY_RUN) {
            out.fields.push({ element: field.element, action: 'would create' });
            continue;
        }

        var created = new GlideRecord('sys_dictionary');
        created.initialize();
        created.setValue('name', TABLE);
        created.setValue('element', field.element);
        created.setValue('column_label', field.label);
        created.setValue('internal_type', 'reference');
        created.setValue('reference', REFERENCE);
        created.setValue('max_length', 32);
        created.setValue('active', true);
        created.setValue('read_only', false);
        var sysId = String(created.insert());
        out.fields.push({ element: field.element, action: sysId ? 'created' : 'insert failed', sys_id: sysId });
    }

    // Read back through GlideRecord so the answer reflects the real column, not just the
    // dictionary row: on a busy instance the row appears well before the column does.
    var probe = new GlideRecord(TABLE);
    probe.initialize();
    out.usable = {};
    for (var j = 0; j < FIELDS.length; j++) {
        out.usable[FIELDS[j].element] = probe.isValidField(FIELDS[j].element);
    }

    gs.print(JSON.stringify(out, null, 2));
})();
