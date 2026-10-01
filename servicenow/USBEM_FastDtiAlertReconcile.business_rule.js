/*
 * Business Rule: USBEM Fast DTI Alert Reconcile
 *
 * Required record configuration:
 *   Table      em_alert
 *   When       after          <-- NOT async. Event Management best practice: "Do not write
 *                                 async business rules for alert tables."
 *   Insert     true
 *   Update     true
 *   Order      150
 *   Condition  ((current.getValue('additional_info') || '').indexOf('direct_to_incident') > -1 ||
 *               (current.getValue('additional_info') || '').indexOf('work_notes') > -1) &&
 *              (current.incident.nil() || '6,7,8'.indexOf(current.incident.state.toString()) > -1)
 *
 * scripts/deploy_usbem.py holds that condition as BR_CONDITION and writes it with the script, so
 * the two cannot drift. It keeps the rule off the vast majority of alert writes: it runs only for
 * an alert whose event asked for an incident or carried a work note, and only while that alert has
 * no incident or holds a finished one. ('alert_work_notes' contains 'work_notes', so one test
 * covers both spellings.) The Closed-alert and message-key guards are in the script instead,
 * because they need to read the alert.
 *
 * Keep this fast. The same guidance says a rule here must not take "more than a few
 * milliseconds", and that an inefficient one "can cause incident creation for an alert to fail
 * and the alert impact calculation to fail". In the common case the script costs one query: if
 * no open USBEM DTI incident exists for the key, reconcileAlertIncident returns
 * no_usbemdti_incident and writes nothing.
 *
 * If incident.correlation_id is not indexed on your instance, add an index before enabling this
 * at volume; the lookup queries incident by correlation_id.
 */
(function executeRule(current, previous /*null when async*/) {
    // Version stamp, logged with every outcome. The Script Includes report their own versions in
    // the endpoint response; this rule has no response, so the log line is where its version
    // shows up. Keep it in step with the release the rest of the project is on.
    var BR_VERSION = '2026.09.30.1';
    var core;
    var dti;
    var outcome;

    try {
        core = new x_usbna_usb_event.USBEM_Core();
        dti = new x_usbna_usb_event.USBEM_DTI(core);
        outcome = dti.reconcileAlertIncident(current, null);
        if (outcome && (outcome.status === 'linked' || outcome.status === 'relinked_to_fast_incident')) {
            outcome.business_rule_version = BR_VERSION;
            gs.info('USBEM fast DTI alert reconcile [v' + BR_VERSION + '] outcome: ' + core.safeJSONStringify(outcome));
        }
    } catch (e) {
        gs.error('USBEM fast DTI alert reconcile [v' + BR_VERSION + '] failed: ' + e);
    }
})(current, previous);
