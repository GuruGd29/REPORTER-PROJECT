/* eslint-disable */
/**
 * qa-dashboard WebdriverIO reporter.
 *
 * Emits qa-dashboard's native schema (manifest.json + per-test JSONs)
 * directly from a WebdriverIO run. Works with WDIO + Mocha, Jasmine,
 * or Cucumber. Survives multi-worker (`maxInstances > 1`) runs by
 * sharing a single run_id across workers via a lockfile in outputDir.
 *
 * Usage in wdio.conf.(c)js / wdio.conf.ts:
 *
 *   const QaDashboardReporter = require('./qa-dashboard-wdio-reporter');
 *
 *   exports.config = {
 *     reporters: [
 *       'spec',
 *       [QaDashboardReporter, { outputDir: 'captures' }],
 *     ],
 *     // ...
 *   };
 *
 * Then:
 *   npx wdio run wdio.conf.js
 *   qa-dashboard captures/run_*
 *   open captures/run_*\/index.html
 *
 * What you get automatically:
 *   - Per-test pass/fail/skip with durations
 *   - Suite hierarchy in test nodeids ("Suite > Sub-suite > test name")
 *   - Auto-capture of `browser.takeScreenshot()` results (base64 PNG)
 *   - Auto-capture of `browser.saveScreenshot(path)` files
 *   - Failure error message + stack
 *   - stdout/stderr log lines per test
 *   - Cucumber steps surface as qa-dashboard steps when running under
 *     @wdio/cucumber-framework
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');
const childProcess = require('child_process');

const SCHEMA_VERSION = 1;

// WDIO's @wdio/reporter base class is what the runner expects to see;
// extending it gets us proper synchronisation (the runner waits on
// isSynchronised before exiting). If it isn't installed, fall back to
// a plain class so the reporter still loads.
let BaseReporter;
try {
  const mod = require('@wdio/reporter');
  BaseReporter = mod && (mod.default || mod);
  if (typeof BaseReporter !== 'function') BaseReporter = class {};
} catch (_) {
  BaseReporter = class {};
}

function nowIso(d) {
  d = d || new Date();
  return d.toISOString().replace(/(\.\d{3})\d+/, '$1');
}

function sanitize(s, maxLen) {
  maxLen = maxLen || 80;
  s = String(s || '');
  s = s.replace(/[\/]/g, '_').replace(/::/g, '_').replace(/[\[\]]/g, '_');
  s = s.replace(/[^A-Za-z0-9_]/g, '_').replace(/_+/g, '_');
  s = s.replace(/^_+|_+$/g, '');
  return s.slice(0, maxLen);
}

function gitTry(args) {
  try {
    return childProcess
      .execFileSync('git', args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 2000 })
      .trim() || null;
  } catch (_) {
    return null;
  }
}

function wdioStateToQa(state) {
  // WDIO: 'passed' | 'failed' | 'skipped' | 'pending'
  if (state === 'passed') return 'pass';
  if (state === 'failed') return 'fail';
  if (state === 'skipped' || state === 'pending') return 'skip';
  return 'fail';
}

function makeRunId(d) {
  const ts = d.toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '_');
  const suffix = crypto.randomBytes(3).toString('hex');
  return 'run_' + ts + '_' + suffix;
}

// -----------------------------------------------------------------------
// Multi-worker run_id coordination.
//
// Each WDIO worker spawns its own reporter instance. We need them all to
// converge on a single run directory. Use an atomic-create lockfile at
// `<outputDir>/.qa-dashboard-current-run-id`. First worker writes,
// others read.
// -----------------------------------------------------------------------
function resolveSharedRunId(outputDir) {
  fs.mkdirSync(outputDir, { recursive: true });
  const lockPath = path.join(outputDir, '.qa-dashboard-current-run-id');

  // Stale lock check: if older than 6 hours, ignore it (previous run crashed).
  if (fs.existsSync(lockPath)) {
    try {
      const stat = fs.statSync(lockPath);
      const ageMs = Date.now() - stat.mtimeMs;
      if (ageMs > 6 * 3600 * 1000) {
        fs.unlinkSync(lockPath);
      }
    } catch (_) { /* ignore */ }
  }

  // Try atomic-create first (first worker wins).
  const runId = makeRunId(new Date());
  try {
    fs.writeFileSync(lockPath, runId, { flag: 'wx', encoding: 'utf-8' });
    return runId;
  } catch (e) {
    if (e && e.code === 'EEXIST') {
      try {
        const existing = fs.readFileSync(lockPath, 'utf-8').trim();
        if (existing) return existing;
      } catch (_) { /* fall through */ }
    }
    return runId; // give up coordinating; isolated dir is better than nothing
  }
}

class QaDashboardWdioReporter extends BaseReporter {
  constructor(options) {
    // @wdio/reporter requires { stdout: true|false } in opts to know
    // whether to capture; we don't write to wdio's stream, so true is fine.
    super(Object.assign({ stdout: false }, options || {}));
    options = options || {};
    this.opts = options;
    this.outputDir = path.resolve(options.outputDir || 'captures');
    this.runStartedAt = new Date();
    this.runId = resolveSharedRunId(this.outputDir);
    this.runDir = path.join(this.outputDir, this.runId);
    fs.mkdirSync(path.join(this.runDir, 'tests'), { recursive: true });
    fs.mkdirSync(path.join(this.runDir, 'assets', 'screenshots'), { recursive: true });

    this.testSeq = 0;
    this.activeTestUid = null;
    this.testsByUid = Object.create(null);
    this.suiteStack = [];                  // titles for nodeid composition
    this.cucumberStepStack = Object.create(null); // uid -> active step ref
    this.runnerCid = null;
    this.runnerCaps = null;

    // Track the last screenshot file each test wrote, so saveScreenshot()
    // results get attached to the right test.
    this._knownScreenshotFiles = new Set();

    // Cleanup of stale screenshot files we already imported.
    this._importedScreenshotPaths = new Set();
  }

  // -------------------------------------------------------------
  // WDIO's @wdio/reporter base watches `isSynchronised` to know
  // when it's safe to shut down. We do writes synchronously, so we
  // are always synchronised.
  // -------------------------------------------------------------
  get isSynchronised() { return true; }

  // -------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------

  onRunnerStart(runner) {
    this.runnerCid = runner && runner.cid;
    this.runnerCaps = runner && (runner.capabilities || runner.sanitizedCapabilities);
    this.runnerSpecs = (runner && runner.specs) || [];
  }

  onSuiteStart(suite) {
    if (suite && suite.title) this.suiteStack.push(suite.title);
  }

  onSuiteEnd(_suite) {
    this.suiteStack.pop();
  }

  onTestStart(test) {
    const uid = (test && test.uid) || (test && test.fullTitle) || ('t' + Date.now());
    this.testSeq++;
    const seq = String(this.testSeq).padStart(3, '0');
    const nodeid =
      [...this.suiteStack, test && test.title].filter(Boolean).join(' > ') ||
      (test && test.fullTitle) || uid;
    const testId = 't' + seq + '_' + sanitize(nodeid);

    const rec = {
      testId,
      seq,
      uid,
      nodeid,
      name: (test && test.title) || nodeid,
      file: (test && test.file) || (this.runnerSpecs && this.runnerSpecs[0]) || '',
      line: null,
      startedAt: new Date(),
      endedAt: null,
      status: 'pass',
      steps: [],
      screenshots: [],
      console: [],
      device: this._deviceFromCaps(),
      app: null,
      tags: [],
      parameters: null,
      outcome: null,
      _shotSeqByStep: Object.create(null),
    };
    this.testsByUid[uid] = rec;
    this.activeTestUid = uid;
  }

  // -------------------------------------------------------------
  // Cucumber step support — when running under
  // @wdio/cucumber-framework, each Gherkin step fires onHookStart /
  // onHookEnd-style events. WDIO exposes them via onBeforeCommand
  // and via dedicated events depending on version; we hook the
  // documented onSuiteStart with type === 'scenario' / 'step'.
  // -------------------------------------------------------------

  onHookStart(_hook) { /* noop — keep hooks out of step list */ }
  onHookEnd(_hook) { /* noop */ }

  // -------------------------------------------------------------
  // Command interception — automatically capture screenshots.
  // -------------------------------------------------------------

  onAfterCommand(commandArgs) {
    if (!commandArgs) return;
    const command = commandArgs.command || commandArgs.endpoint || '';
    const result = commandArgs.result;

    // WebDriver classic & W3C: 'takeScreenshot' returns { value: <base64> }
    if (/(^|\W)(takeScreenshot|screenshot)(\W|$)/i.test(String(command))) {
      const b64 = result && (result.value || result);
      if (typeof b64 === 'string' && b64.length > 100) {
        try {
          const buf = Buffer.from(b64, 'base64');
          this._attachScreenshot(buf, 'png', 'auto-screenshot');
        } catch (_) { /* ignore */ }
      }
    }

    // browser.saveScreenshot('foo.png') writes to disk; the result is
    // the file contents (Buffer) — capture that path/file too.
    if (/saveScreenshot/i.test(String(command)) && commandArgs.body) {
      const body = commandArgs.body;
      const filename = (body && (body.file || body[0])) || null;
      if (filename && fs.existsSync(filename) && !this._importedScreenshotPaths.has(filename)) {
        try {
          const buf = fs.readFileSync(filename);
          const ext = (path.extname(filename).slice(1) || 'png').toLowerCase();
          this._attachScreenshot(buf, ext, path.basename(filename));
          this._importedScreenshotPaths.add(filename);
        } catch (_) { /* ignore */ }
      }
    }
  }

  _attachScreenshot(buf, ext, label) {
    const uid = this.activeTestUid;
    if (!uid) return;
    const rec = this.testsByUid[uid];
    if (!rec) return;

    // Attach to last (or only synthetic) step — step id 1 by default.
    const stepId = 1;
    rec._shotSeqByStep[stepId] = (rec._shotSeqByStep[stepId] || 0) + 1;
    const seqStr = String(rec._shotSeqByStep[stepId]).padStart(3, '0');
    const shotId = rec.testId + '_step_' + stepId + '_' + seqStr;
    const filename = shotId + '.' + ext;
    const dst = path.join(this.runDir, 'assets', 'screenshots', filename);
    try {
      fs.writeFileSync(dst, buf);
    } catch (_) {
      return;
    }
    rec.screenshots.push({
      id: shotId,
      step_id: stepId,
      captured_at: nowIso(),
      filename,
      asset_path: 'assets/screenshots/' + filename,
      width: null,
      height: null,
      size_bytes: buf.length,
      label: label || 'screenshot',
    });
  }

  // -------------------------------------------------------------
  // Test outcomes
  // -------------------------------------------------------------

  onTestPass(test) {
    const rec = this._recForTest(test);
    if (rec) rec.status = 'pass';
  }

  onTestFail(test) {
    const rec = this._recForTest(test);
    if (!rec) return;
    rec.status = 'fail';
    const err = (test && (test.error || (test.errors && test.errors[0]))) || null;
    if (err) {
      const stack = String(err.stack || err.message || '');
      rec._error = {
        type: err.name || 'Error',
        message: String(err.message || ''),
        traceback: stack,
      };
    }
  }

  onTestSkip(test) {
    const rec = this._recForTest(test);
    if (rec) rec.status = 'skip';
  }

  onTestRetry(test) {
    // WDIO retries clear and re-run the same test. Reset state so the
    // final attempt is what we record.
    const rec = this._recForTest(test);
    if (!rec) return;
    rec.status = 'pass';
    rec.screenshots = [];
    rec._error = null;
    rec._shotSeqByStep = Object.create(null);
  }

  onTestEnd(test) {
    const rec = this._recForTest(test);
    if (!rec) return;
    rec.endedAt = new Date();

    const duration = (test && typeof test.duration === 'number')
      ? test.duration
      : (rec.endedAt.getTime() - rec.startedAt.getTime());

    const errInfo = rec._error;
    const longrepr = errInfo ? errInfo.traceback : null;
    const firstLine = longrepr ? longrepr.split(/\r?\n/)[0] : null;
    rec.outcome = {
      phase: 'call',
      longrepr,
      traceback_summary: firstLine,
      stdout_tail: '',
      stderr_tail: '',
    };

    if (rec.steps.length === 0) {
      rec.steps.push({
        id: 1,
        name: 'Test execution',
        status: rec.status === 'fail' ? 'fail' : (rec.status === 'skip' ? 'skip' : 'pass'),
        started_at: nowIso(rec.startedAt),
        ended_at: nowIso(rec.endedAt),
        duration_ms: duration,
        substeps: [],
        screenshot_ids: rec.screenshots.map(s => s.id),
        flow_ids: [],
        error: errInfo || null,
        skip_reason: rec.status === 'skip' ? 'skipped by webdriverio' : null,
      });
    }

    const record = {
      schema_version: SCHEMA_VERSION,
      test_id: rec.testId,
      nodeid: rec.nodeid,
      name: rec.name,
      file: rec.file,
      line: rec.line,
      status: rec.status,
      started_at: nowIso(rec.startedAt),
      ended_at: nowIso(rec.endedAt),
      duration_ms: duration,
      tags: rec.tags,
      parameters: rec.parameters,
      outcome: rec.outcome,
      steps: rec.steps,
      flows: [],
      screenshots: rec.screenshots,
      console: rec.console,
      device: rec.device,
      app: rec.app,
    };
    try {
      fs.writeFileSync(
        path.join(this.runDir, 'tests', rec.testId + '.json'),
        JSON.stringify(record, null, 2),
        'utf-8',
      );
    } catch (e) {
      // Last-resort: stderr so user sees it.
      try { process.stderr.write('qa-dashboard: failed to write ' + rec.testId + ': ' + e.message + '\n'); }
      catch (_) {}
    }
    this.activeTestUid = null;
  }

  onRunnerEnd(_runner) {
    // Each worker rewrites manifest.json. Last writer wins; output is
    // generated by scanning tests/*.json, so the result is the same
    // regardless of order.
    try {
      this._rewriteManifest();
    } catch (e) {
      try { process.stderr.write('qa-dashboard: manifest write failed: ' + e.message + '\n'); }
      catch (_) {}
    }
    // Print friendly hint once per worker (cheap).
    process.stdout.write(
      '\nqa-dashboard: run data written to ' + this.runDir +
      '\nqa-dashboard: render HTML with -> qa-dashboard "' + this.runDir + '"\n'
    );
  }

  // -------------------------------------------------------------
  // Manifest assembly — scan tests/ on every flush so we don't lose
  // results from other workers that flushed before us.
  // -------------------------------------------------------------

  _rewriteManifest() {
    const testsDir = path.join(this.runDir, 'tests');
    let tests = [];
    if (fs.existsSync(testsDir)) {
      const files = fs.readdirSync(testsDir).filter(f => f.endsWith('.json')).sort();
      for (const f of files) {
        try {
          const obj = JSON.parse(fs.readFileSync(path.join(testsDir, f), 'utf-8'));
          tests.push(obj);
        } catch (_) { /* skip corrupt */ }
      }
    }

    const summary = {
      total: tests.length,
      passed: tests.filter(t => t.status === 'pass').length,
      failed: tests.filter(t => t.status === 'fail').length,
      skipped: tests.filter(t => t.status === 'skip').length,
      error: tests.filter(t => t.status === 'error').length,
      xfailed: 0,
      xpassed: 0,
    };
    summary.pass_rate = summary.total
      ? Math.round((summary.passed / summary.total) * 1000) / 1000
      : 0;

    const status = summary.error > 0 ? 'error'
                 : summary.failed > 0 ? 'fail'
                 : 'pass';

    const ended = new Date();
    const manifest = {
      schema_version: SCHEMA_VERSION,
      run_id: this.runId,
      started_at: nowIso(this.runStartedAt),
      ended_at: nowIso(ended),
      duration_ms: ended.getTime() - this.runStartedAt.getTime(),
      status,
      summary,
      environment: {
        pytest: null,
        python: null,
        platform: os.platform() + '-' + os.arch() + '-' + os.release(),
        mitmproxy: null,
        qa_dashboard: 'webdriverio-reporter-0.6.0',
        hostname: os.hostname(),
        user: os.userInfo().username,
        cwd: process.cwd(),
        webdriverio: this._getWdioVersion(),
        node: process.version,
      },
      source: {
        repo: this._gitRepoName(),
        branch: gitTry(['rev-parse', '--abbrev-ref', 'HEAD']),
        commit: gitTry(['rev-parse', '--short', 'HEAD']),
        commit_message: gitTry(['log', '-1', '--pretty=%s']),
        trigger: process.env.CI ? 'ci' : 'local',
      },
      config: {
        mitm_port: null,
        host_filter: null,
        screenshot_on_fail: true,
        command_line: ['npx', 'wdio', 'run'].join(' '),
        reporter: 'qa-dashboard-webdriverio',
      },
      tests: tests.map(t => ({
        test_id: t.test_id,
        nodeid: t.nodeid,
        name: t.name,
        file: t.file,
        status: t.status,
        started_at: t.started_at,
        duration_ms: t.duration_ms,
        step_count: (t.steps || []).length,
        flow_count: 0,
        screenshot_count: (t.screenshots || []).length,
        tags: t.tags || [],
        error_summary: t.outcome ? t.outcome.traceback_summary : null,
      })),
    };

    // Atomic-ish rename to reduce risk of partial writes during concurrent
    // worker flushes.
    const finalPath = path.join(this.runDir, 'manifest.json');
    const tmpPath = finalPath + '.tmp-' + (this.runnerCid || process.pid);
    fs.writeFileSync(tmpPath, JSON.stringify(manifest, null, 2), 'utf-8');
    fs.renameSync(tmpPath, finalPath);
  }

  // -------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------

  _recForTest(test) {
    const uid = test && (test.uid || test.fullTitle);
    if (uid && this.testsByUid[uid]) return this.testsByUid[uid];
    // Fallback: use active test (covers some WDIO event ordering quirks).
    if (this.activeTestUid && this.testsByUid[this.activeTestUid]) {
      return this.testsByUid[this.activeTestUid];
    }
    return null;
  }

  _deviceFromCaps() {
    const caps = this.runnerCaps;
    if (!caps || typeof caps !== 'object') return null;
    const name = caps.browserName || caps['appium:deviceName'] || caps.platformName;
    if (!name) return null;
    return {
      platform: caps.platformName || null,
      browser: caps.browserName || null,
      device: caps['appium:deviceName'] || null,
      version: caps.browserVersion || caps['appium:platformVersion'] || null,
    };
  }

  _getWdioVersion() {
    try {
      return require('webdriverio/package.json').version;
    } catch (_) {
      try {
        return require('@wdio/cli/package.json').version;
      } catch (_) {
        return null;
      }
    }
  }

  _gitRepoName() {
    const top = gitTry(['rev-parse', '--show-toplevel']);
    return top ? path.basename(top) : null;
  }
}

module.exports = QaDashboardWdioReporter;
module.exports.default = QaDashboardWdioReporter;
