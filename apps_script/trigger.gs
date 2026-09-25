/**
 * Padiz Shorts — reliable scheduler (Google Apps Script).
 *
 * Why this exists: GitHub's own cron for *private* repositories frequently
 * fires late (30 min - 2 h) or not at all, so the 5 daily uploads cannot be
 * trusted to a `schedule:` trigger alone. A Google-hosted time trigger is free
 * and fires within a minute of the target time.
 *
 * Setup (one time, ~2 minutes):
 *   1. github.com → Settings → Developer settings → Personal access tokens →
 *      Fine-grained tokens → Generate new token:
 *        Repository access: only rasoolpadiz/padiz-shorts-automation
 *        Permissions: Actions = Read and write, Metadata = Read-only
 *      Copy the token (starts with github_pat_).
 *   2. script.google.com → New project → replace the editor content with this file.
 *   3. Project Settings (gear icon):
 *        - Time zone: (GMT+03:30) Tehran
 *        - Script properties → Add property: GH_TOKEN = <the token>
 *   4. Run the function `createTriggers` once and accept the authorization prompt.
 *   5. Done — the workflow is dispatched every day at 09:30, 13:30, 17:30,
 *      20:30 and 23:30 Tehran time.
 *
 * Safety: the publishing workflow itself enforces a minimum gap between uploads
 * (MIN_GAP_MINUTES in run_daily.py), so a GitHub cron run and an Apps Script
 * dispatch landing close together can never publish two Shorts at once.
 */

const CONFIG = {
  owner: 'rasoolpadiz',
  repo: 'padiz-shorts-automation',
  workflow: 'scheduled_shorts.yml',
  ref: 'main',
  // Tehran hours; 9.5 = 09:30. Must fall on :00/:15/:30/:45 for nearMinute().
  slots: [9.5, 13.5, 17.5, 20.5, 23.5],
};

function createTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    ScriptApp.deleteTrigger(trigger);
  });

  CONFIG.slots.forEach(function (slot) {
    const hour = Math.floor(slot);
    const minute = Math.round((slot - hour) * 60);
    ScriptApp.newTrigger('dispatchShortsWorkflow')
      .timeBased()
      .atHour(hour)
      .nearMinute(minute)
      .everyDays(1)
      .create();
  });

  Logger.log('Created ' + ScriptApp.getProjectTriggers().length + ' daily triggers.');
}

function dispatchShortsWorkflow() {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) {
    Logger.log('GH_TOKEN script property is missing.');
    return;
  }

  const url = 'https://api.github.com/repos/' + CONFIG.owner + '/' + CONFIG.repo +
    '/actions/workflows/' + CONFIG.workflow + '/dispatches';

  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
    },
    payload: JSON.stringify({ ref: CONFIG.ref }),
    muteHttpExceptions: true,
  });

  Logger.log('dispatch status ' + response.getResponseCode() + ' at ' + new Date());
}

/**
 * Optional watchdog: run once a day (e.g. 23:55 Tehran). If no Short has been
 * published in the last 6 hours, dispatch an extra run. Useful when everything
 * upstream (GitHub cron) was skipped.
 */
function watchdog() {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  const url = 'https://api.github.com/repos/' + CONFIG.owner + '/' + CONFIG.repo +
    '/actions/workflows/' + CONFIG.workflow + '/runs?per_page=5';
  const response = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    muteHttpExceptions: true,
  });

  if (response.getResponseCode() !== 200) {
    Logger.log('cannot read runs: ' + response.getResponseCode());
    return;
  }

  const runs = JSON.parse(response.getContentText()).workflow_runs || [];
  const now = Date.now();
  const latestSuccess = runs
    .filter(function (run) { return run.conclusion === 'success'; })
    .map(function (run) { return Date.parse(run.updated_at); })
    .sort(function (a, b) { return b - a; })[0];

  const hoursSince = latestSuccess ? (now - latestSuccess) / 3600000 : 999;
  Logger.log('hours since last successful run: ' + hoursSince.toFixed(1));

  if (hoursSince > 6) {
    dispatchShortsWorkflow();
  }
}
