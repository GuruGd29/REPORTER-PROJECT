/* eslint-disable */
/**
 * qa-dashboard Playwright reporter.
 *
 * Emits qa-dashboard's native schema (manifest.json + per-test JSONs)
 * directly from a Playwright JS/TS test run — gives you step-level
 * breakdowns, sub-step timings, and auto-attached screenshots without
 * a separate `qa-dashboard ingest` step.
 *
 * Usage in playwright.config.ts:
 *
 *   import { defineConfig } from '@playwright/test';
 *
 *   export default defineConfig({
 *     reporter: [
 *       ['list'],
 *       ['./qa-dashboard-reporter.js', { outputDir: 'captures' }],
 *     ],
 *     use: { screenshot: 'only-on-failure' },
 *   });
 *
 * Then:
 *   npx playwright test
 *   qa-dashboard captures/run_*
 *   open captures/run_*\/index.html
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');
const childProcess = require('child_process');

const SCHEMA_VERSION = 1;

function nowIso(d) {
  d = d || new Date();
  return d.toISOString().replace(/(\.\d{3})\d+/, '$1');  // keep ms precision
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
    return childProcess.execFileSync('git', args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 2000 }).trim() || null;
  } catch (_) {
    return null;
  }
}

function pwStatusToQa(status) {
  // Playwright: 'passed' | 'failed' | 'timedOut' | 'skipped' | 'interrupted'
  if (status === 'passed') return 'pass';
  if (status === 'failed' || status === 'timedOut') return 'fail';
  if (status === 'skipped') return 'skip';
  if (status === 'interrupted') return 'error';
  return 'fail';
}

function isImageContentType(ct) {
  return typeof ct === 'string' && /^image\/(png|jpe?g|webp)$/i.test(ct);
}

function extForContentType(ct) {
  if (/png/i.test(ct)) return 'png';
  if (/jpe?g/i.test(ct)) return 'jpg';
  if (/webp/i.test(ct)) return 'webp';
  return 'bin';
}

class QaDashboardReporter {
  constructor(options) {
    options = options || {};
    this.outputDir = options.outputDir || 'captures';
    this.runStartedAt = null;
    this.runDir = null;
    this.runId = null;
    this.testSeq = 0;
    this.testMap = new WeakMap();    // PlaywrightTest -> internal record
    this.testRecords = [];           // serialized in insertion order
    this.stepStack = new WeakMap();  // PlaywrightTest -> Array of step refs
  }

  // -------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------

  onBegin(config, _suite) {
    this.runStartedAt = new Date();
    const ts = this.runStartedAt.toISOString()
      .replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '_');
    const suffix = crypto.randomBytes(3).toString('hex');
    this.runId = 'run_' + ts + '_' + suffix;
    this.runDir = path.resolve(this.outputDir, this.runId);
    fs.mkdirSync(path.join(this.runDir, 'tests'), { recursive: true });
    fs.mkdirSync(path.join(this.runDir, 'assets', 'screenshots'), { recursive: true });
    this.config = config;
  }

  onTestBegin(test, _result) {
    this.testSeq++;
    const seq = String(this.testSeq).padStart(3, '0');
    const nodeid = test.titlePath().filter(Boolean).join(' > ');
    const testId = 't' + seq + '_' + sanitize(nodeid);
    const rec = {
      testId, seq,
      pwTest: test,
      nodeid,
      name: test.title,
      file: test.location ? test.location.file : '',
      line: test.location ? test.location.line : null,
      startedAt: new Date(),
      endedAt: null,
      status: 'pass',
      steps: [],
      screenshots: [],
      console: [],
      device: null,
      app: null,
      tags: (test.tags || []).slice(),
      parameters: null,
      outcome: null,
      attachmentIdx: 0,
      _shotSeqByStep: Object.create(null),
    };
    this.testMap.set(test, rec);
    this.stepStack.set(test, []);
  }

  onStepBegin(test, _result, step) {
    // Only record the user's explicit test.step() calls, not internal
    // pw:api/expect/hook events (they'd flood the report).
    if (!step || step.category !== 'test.step') return;
    const rec = this.testMap.get(test);
    if (!rec) return;
    const stack = this.stepStack.get(test);
    const id = rec.steps.length + 1;
    const stepRec = {
      id,
      name: step.title || '(unnamed step)',
      status: 'pass',
      started_at: nowIso(),
      ended_at: null,
      duration_ms: 0,
      substeps: [],
      screenshot_ids: [],
      flow_ids: [],
      error: null,
      skip_reason: null,
      _startedAtMs: Date.now(),
      _parent: stack.length > 0 ? stack[stack.length - 1] : null,
    };
    if (stepRec._parent) {
      // Nested test.step → record as a substep
      stepRec._parent._pendingSubstep = stepRec;
    } else {
      rec.steps.push(stepRec);
    }
    stack.push(stepRec);
  }

  onStepEnd(test, _result, step) {
    if (!step || step.category !== 'test.step') return;
    const rec = this.testMap.get(test);
    if (!rec) return;
    const stack = this.stepStack.get(test);
    const stepRec = stack.pop();
    if (!stepRec) return;
    stepRec.ended_at = nowIso();
    stepRec.duration_ms = Date.now() - stepRec._startedAtMs;
    if (step.error) {
      stepRec.status = 'fail';
      stepRec.error = {
        type: step.error.name || 'Error',
        message: String(step.error.message || ''),
        traceback: String(step.error.stack || step.error.message || ''),
      };
    }
    if (stepRec._parent) {
      // It was a nested step → fold into parent.substeps
      stepRec._parent.substeps.push({
        name: stepRec.name,
        status: stepRec.status === 'fail' ? 'fail' : 'pass',
        duration_ms: stepRec.duration_ms,
      });
      if (stepRec.status === 'fail') {
        stepRec._parent.status = 'fail';
      }
      delete stepRec._parent._pendingSubstep;
    }
    delete stepRec._parent;
    delete stepRec._startedAtMs;
  }

  onStdOut(chunk, test, _result) {
    if (!test) return;
    const rec = this.testMap.get(test);
    if (!rec) return;
    const text = typeof chunk === 'string' ? chunk : chunk.toString('utf-8');
    for (const line of text.split(/\r?\n/)) {
      if (!line) continue;
      rec.console.push({
        ts: nowIso(),
        level: this._inferLogLevel(line),
        logger: 'playwright.stdout',
        message: line,
      });
    }
  }

  onStdErr(chunk, test, _result) {
    if (!test) return;
    const rec = this.testMap.get(test);
    if (!rec) return;
    const text = typeof chunk === 'string' ? chunk : chunk.toString('utf-8');
    for (const line of text.split(/\r?\n/)) {
      if (!line) continue;
      rec.console.push({
        ts: nowIso(),
        level: 'ERROR',
        logger: 'playwright.stderr',
        message: line,
      });
    }
  }

  async onTestEnd(test, result) {
    const rec = this.testMap.get(test);
    if (!rec) return;
    rec.endedAt = new Date();
    rec.status = pwStatusToQa(result.status);

    // outcome.longrepr
    let longrepr = null;
    if (result.error) {
      longrepr = (result.error.stack || result.error.message || '').trim() || null;
    }
    const firstLine = longrepr ? longrepr.split(/\r?\n/)[0] : null;
    rec.outcome = {
      phase: 'call',
      longrepr,
      traceback_summary: firstLine,
      stdout_tail: '',
      stderr_tail: '',
    };

    // If no test.step() was used, synthesize a single "Test execution" step
    if (rec.steps.length === 0) {
      rec.steps.push({
        id: 1,
        name: 'Test execution',
        status: rec.status === 'fail' ? 'fail' : (rec.status === 'skip' ? 'skip' : 'pass'),
        started_at: nowIso(rec.startedAt),
        ended_at: nowIso(rec.endedAt),
        duration_ms: rec.endedAt.getTime() - rec.startedAt.getTime(),
        substeps: [],
        screenshot_ids: [],
        flow_ids: [],
        error: longrepr ? { type: 'Error', message: firstLine || '', traceback: longrepr } : null,
        skip_reason: rec.status === 'skip' ? 'skipped by playwright' : null,
      });
    }

    // Pull flows from the qa-dashboard-network attachment (emitted by
    // qa-dashboard-fixtures.js). Falls back to [] if the user hasn't
    // opted in to the fixtures.
    rec.flows = this._extractFlows(result.attachments || []);

    // Attach screenshots from result.attachments
    const failingStepId = (() => {
      for (const s of rec.steps) {
        if (s.status === 'fail') return s.id;
      }
      return rec.steps.length ? rec.steps[rec.steps.length - 1].id : 1;
    })();

    for (const att of (result.attachments || [])) {
      if (!isImageContentType(att.contentType)) continue;
      const ext = extForContentType(att.contentType);
      const stepId = failingStepId;
      rec._shotSeqByStep[stepId] = (rec._shotSeqByStep[stepId] || 0) + 1;
      const seqStr = String(rec._shotSeqByStep[stepId]).padStart(3, '0');
      const shotId = `${rec.testId}_step_${stepId}_${seqStr}`;
      const filename = `${shotId}.${ext}`;
      const dst = path.join(this.runDir, 'assets', 'screenshots', filename);
      let body;
      try {
        if (att.body) {
          body = att.body;
        } else if (att.path && fs.existsSync(att.path)) {
          body = fs.readFileSync(att.path);
        } else {
          continue;
        }
        fs.writeFileSync(dst, body);
      } catch (_) {
        continue;
      }
      rec.screenshots.push({
        id: shotId,
        step_id: stepId,
        captured_at: nowIso(),
        filename,
        asset_path: `assets/screenshots/${filename}`,
        width: null,
        height: null,
        size_bytes: body.length,
        label: att.name || `attachment ${rec.screenshots.length + 1}`,
      });
      // Attach to the step
      const target = rec.steps.find(s => s.id === stepId);
      if (target) target.screenshot_ids.push(shotId);
    }

    // Persist the per-test record
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
      duration_ms: rec.endedAt.getTime() - rec.startedAt.getTime(),
      tags: rec.tags,
      parameters: rec.parameters,
      outcome: rec.outcome,
      steps: rec.steps.map(this._cleanStep),
      flows: rec.flows || [],
      screenshots: rec.screenshots,
      console: rec.console,
      device: rec.device,
      app: rec.app,
    };
    fs.writeFileSync(
      path.join(this.runDir, 'tests', rec.testId + '.json'),
      JSON.stringify(record, null, 2),
      'utf-8',
    );
    this.testRecords.push(record);
  }

  async onEnd(_result) {
    const ended = new Date();
    const summary = {
      total: this.testRecords.length,
      passed: this.testRecords.filter(t => t.status === 'pass').length,
      failed: this.testRecords.filter(t => t.status === 'fail').length,
      skipped: this.testRecords.filter(t => t.status === 'skip').length,
      error: this.testRecords.filter(t => t.status === 'error').length,
      xfailed: 0,
      xpassed: 0,
    };
    summary.pass_rate = summary.total
      ? Math.round((summary.passed / summary.total) * 1000) / 1000
      : 0;

    const status = summary.error > 0 ? 'error'
                 : summary.failed > 0 ? 'fail'
                 : 'pass';

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
        qa_dashboard: 'playwright-reporter-0.9.0',
        hostname: os.hostname(),
        user: os.userInfo().username,
        cwd: process.cwd(),
        playwright: this._getPlaywrightVersion(),
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
        command_line: ['npx', 'playwright', 'test'].join(' '),
        reporter: 'qa-dashboard-playwright',
      },
      tests: this.testRecords.map(t => ({
        test_id: t.test_id,
        nodeid: t.nodeid,
        name: t.name,
        file: t.file,
        status: t.status,
        started_at: t.started_at,
        duration_ms: t.duration_ms,
        step_count: t.steps.length,
        flow_count: (t.flows || []).length,
        screenshot_count: t.screenshots.length,
        tags: t.tags,
        error_summary: t.outcome ? t.outcome.traceback_summary : null,
      })),
    };

    fs.writeFileSync(
      path.join(this.runDir, 'manifest.json'),
      JSON.stringify(manifest, null, 2),
      'utf-8',
    );

    console.log('\nqa-dashboard: run data written to ' + this.runDir);
    console.log('qa-dashboard: render HTML with → qa-dashboard "' + this.runDir + '"');
  }

  // -------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------

  _cleanStep(step) {
    // strip internal underscores fields
    const out = {};
    for (const k of Object.keys(step)) {
      if (k.startsWith('_')) continue;
      out[k] = step[k];
    }
    return out;
  }

  _extractFlows(attachments) {
    for (const att of attachments) {
      if (!att || att.name !== 'qa-dashboard-network') continue;
      let raw;
      try {
        if (att.body) {
          raw = Buffer.isBuffer(att.body) ? att.body.toString('utf-8') : String(att.body);
        } else if (att.path && fs.existsSync(att.path)) {
          raw = fs.readFileSync(att.path, 'utf-8');
        } else {
          continue;
        }
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) continue;
        // Re-number ids so they are contiguous per test (fixtures emit
        // 0..N-1 already, but a later transform could break that).
        return parsed.map((f, i) => Object.assign({}, f, { id: i }));
      } catch (_) {
        continue;
      }
    }
    return [];
  }

  _inferLogLevel(line) {
    const u = line.toUpperCase();
    if (u.includes('ERROR') || u.includes('FATAL')) return 'ERROR';
    if (u.includes('WARN')) return 'WARN';
    if (u.includes('DEBUG') || u.includes('TRACE')) return 'DEBUG';
    return 'INFO';
  }

  _getPlaywrightVersion() {
    try {
      return require('@playwright/test/package.json').version;
    } catch (_) {
      return null;
    }
  }

  _gitRepoName() {
    const top = gitTry(['rev-parse', '--show-toplevel']);
    return top ? path.basename(top) : null;
  }
}

module.exports = QaDashboardReporter;
module.exports.default = QaDashboardReporter;
