/* eslint-disable */
/**
 * qa-dashboard Playwright fixtures — opt-in native network capture.
 *
 * The reporter (qa-dashboard-reporter.js) runs in Playwright's manager
 * process and cannot see BrowserContext objects directly. This file
 * extends Playwright's `test` fixture so every BrowserContext created
 * by a test has request/response listeners attached. The captured
 * flows are serialized to a JSON test attachment named
 * `qa-dashboard-network`, which the reporter picks up in onTestEnd.
 *
 * Usage:
 *
 *   // In your tests, change this:
 *   //   import { test, expect } from '@playwright/test';
 *   // to this:
 *   const { test, expect } = require('./qa-dashboard-fixtures');
 *
 * Body capture is bounded by MAX_BODY_BYTES (default 100 KB) to match
 * the server-side mitm addon. Pass `qaDashboard: { maxBodyBytes: ... }`
 * via test.use() to override.
 */
'use strict';

const base = require('@playwright/test');

const MAX_BODY_BYTES = 100 * 1024;

function isJsonContentType(ct) {
  return /(\/json|\+json)\b/i.test(String(ct || ''));
}

function isTextContentType(ct) {
  ct = String(ct || '').toLowerCase();
  return (
    ct === '' || ct.startsWith('text/')
    || ct.includes('xml') || ct.includes('html')
    || ct.includes('javascript') || ct.includes('form-urlencoded')
  );
}

function headersToLowerMap(headers) {
  const out = {};
  if (!headers) return out;
  for (const k of Object.keys(headers)) {
    out[k.toLowerCase()] = String(headers[k]);
  }
  return out;
}

function decodeBody(buf, contentType, limit) {
  if (!buf || buf.length === 0) {
    return { encoding: 'empty', body: '', size: 0 };
  }
  const size = buf.length;
  if (size > limit) {
    return { encoding: 'omitted', body: null, size };
  }
  const ct = String(contentType || '').toLowerCase();
  if (isJsonContentType(ct) || buf[0] === 0x7b || buf[0] === 0x5b) {
    try {
      const text = buf.toString('utf-8');
      const parsed = JSON.parse(text);
      return { encoding: 'json', body: parsed, size };
    } catch (_) { /* fall through */ }
  }
  if (isTextContentType(ct)) {
    try {
      return { encoding: 'text', body: buf.toString('utf-8'), size };
    } catch (_) { /* fall through */ }
  }
  return { encoding: 'base64', body: buf.toString('base64'), size };
}

function urlParts(u) {
  try {
    const parsed = new URL(u);
    return { host: parsed.hostname, path: parsed.pathname || '/' };
  } catch (_) {
    return { host: '', path: '/' };
  }
}

function isoNow(d) {
  return (d || new Date()).toISOString().replace(/(\.\d{3})\d+/, '$1');
}

const test = base.test.extend({
  qaDashboard: [{ maxBodyBytes: MAX_BODY_BYTES, enabled: true }, { option: true }],

  context: async ({ context, qaDashboard }, use, testInfo) => {
    if (!qaDashboard || qaDashboard.enabled === false) {
      await use(context);
      return;
    }
    const limit = qaDashboard.maxBodyBytes || MAX_BODY_BYTES;
    const flows = [];
    const pending = new Map();  // request -> { id, started, startedAtMs }
    let nextId = 0;

    const onRequest = (req) => {
      const id = nextId++;
      pending.set(req, { id, started: new Date(), startedAtMs: Date.now() });
    };

    const onResponse = async (resp) => {
      const req = resp.request();
      const meta = pending.get(req) || {
        id: nextId++, started: new Date(), startedAtMs: Date.now(),
      };
      pending.delete(req);
      let url = '';
      let method = 'GET';
      let reqHeaders = {};
      let reqCt = '';
      let reqBody = { encoding: 'empty', body: '', size: 0 };
      let respHeaders = {};
      let respCt = '';
      let respBody = { encoding: 'empty', body: '', size: 0 };
      let status = 0;
      try { url = req.url(); } catch (_) {}
      try { method = (req.method() || 'GET').toUpperCase(); } catch (_) {}
      try {
        reqHeaders = headersToLowerMap(await req.allHeaders());
      } catch (_) {}
      reqCt = reqHeaders['content-type'] || '';
      try {
        const post = req.postDataBuffer();
        if (post) reqBody = decodeBody(post, reqCt, limit);
      } catch (_) {}
      try {
        respHeaders = headersToLowerMap(await resp.allHeaders());
      } catch (_) {}
      respCt = respHeaders['content-type'] || '';
      try { status = resp.status() || 0; } catch (_) {}
      try {
        const body = await resp.body();
        if (body) respBody = decodeBody(body, respCt, limit);
      } catch (_) {
        // some responses (redirects, 204s, prefetch) don't expose a body
      }
      const parts = urlParts(url);
      flows.push({
        id: meta.id,
        timestamp: isoNow(meta.started),
        method,
        url,
        host: parts.host,
        path: parts.path,
        status_code: status,
        duration_ms: Math.max(0, Date.now() - meta.startedAtMs),
        step_id: null,
        request: {
          headers: reqHeaders,
          content_type: reqCt,
          body_encoding: reqBody.encoding,
          body_size_bytes: reqBody.size,
          body: reqBody.body,
        },
        response: {
          headers: respHeaders,
          content_type: respCt,
          body_encoding: respBody.encoding,
          body_size_bytes: respBody.size,
          body: respBody.body,
        },
      });
    };

    const onRequestFailed = (req) => {
      const meta = pending.get(req);
      if (!meta) return;
      pending.delete(req);
      let url = ''; let method = 'GET'; let reqHeaders = {};
      try { url = req.url(); } catch (_) {}
      try { method = (req.method() || 'GET').toUpperCase(); } catch (_) {}
      try { reqHeaders = headersToLowerMap(req.headers()); } catch (_) {}
      const parts = urlParts(url);
      flows.push({
        id: meta.id,
        timestamp: isoNow(meta.started),
        method,
        url,
        host: parts.host,
        path: parts.path,
        status_code: 0,
        duration_ms: Math.max(0, Date.now() - meta.startedAtMs),
        step_id: null,
        request: {
          headers: reqHeaders,
          content_type: reqHeaders['content-type'] || '',
          body_encoding: 'empty', body_size_bytes: 0, body: '',
        },
        response: {
          headers: {}, content_type: '',
          body_encoding: 'empty', body_size_bytes: 0, body: '',
        },
      });
    };

    context.on('request', onRequest);
    context.on('response', onResponse);
    context.on('requestfailed', onRequestFailed);

    try {
      await use(context);
    } finally {
      try { context.off('request', onRequest); } catch (_) {}
      try { context.off('response', onResponse); } catch (_) {}
      try { context.off('requestfailed', onRequestFailed); } catch (_) {}
      try {
        await testInfo.attach('qa-dashboard-network', {
          contentType: 'application/json',
          body: Buffer.from(JSON.stringify(flows), 'utf-8'),
        });
      } catch (_) {
        // Best-effort; never fail a test because of capture errors.
      }
    }
  },
});

module.exports = { test, expect: base.expect };
module.exports.test = test;
module.exports.expect = base.expect;
module.exports.default = test;
