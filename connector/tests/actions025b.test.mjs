/**
 * 025 batch 2: `sys.get_project_file`, and the shared archive read it moved into.
 *
 * Why these tests exist rather than one more in `actions025.test.mjs`: the batch-2
 * action is the *same code path* as the batch-1 document read — one
 * `readArchive` now serves both — so the failure this file guards against is not
 * "the new action is broken" but "the new action quietly changed the old one's
 * answer". Two facts make that concrete and are pinned here:
 *
 * 1. **The gates are per call.** `getProjectFile` is documented under
 *    工程管理 > 下载工程, `getDocumentFile` under 工程设计图 > 文件导出. A refusal
 *    that quoted the wrong one would send the user to the wrong editor setting,
 *    which is the one thing a refusal must not do.
 * 2. **The scopes differ, and one of them was measured.** `getDocumentFile`
 *    returns the *focused document* (probe P1), `getProjectFile` the project, so
 *    both answers carry `scope` — a caller that assumed project scope would
 *    silently review a single page.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

const ZIP_BYTES = [0x50, 0x4b, 0x03, 0x04, 9, 8, 7];

/** A host `File` stand-in carrying an archive-looking payload. */
function fileLike(bytes = ZIP_BYTES, name = 'ProPrj_test_2026-09-23.epro2') {
  return { name, type: 'zip', arrayBuffer: async () => new Uint8Array(bytes).buffer };
}

function fakeEda(overrides = {}) {
  const calls = { projectFile: [], documentFile: [] };
  const eda = {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({ uuid: 'page-1', name: 'P1', documentType: 1, tabId: 't1' }),
    },
    sys_FileManager: {
      getProjectFile: async (...args) => {
        calls.projectFile.push(args);
        return fileLike();
      },
      getDocumentFile: async (...args) => {
        calls.documentFile.push(args);
        return fileLike(ZIP_BYTES, 'ProDoc_P1.epro2');
      },
      getDocumentSource: async () => '{"type":"DOCHEAD"}||{"docType":"SCH_PAGE"}|',
    },
    ...overrides,
  };
  return { eda, calls };
}

test('sys.get_project_file passes the declaration arguments in order and says scope=project', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['sys.get_project_file']({});

  assert.deepEqual(calls.projectFile, [[undefined, undefined, 'epro2']]);
  assert.equal(data.scope, 'project');
  assert.equal(data.source, 'sys_FileManager.getProjectFile');
  assert.equal(data.fileType, 'epro2');
  assert.equal(data.isZip, true);
  assert.equal(data.encoding, 'base64');
  assert.equal(data.name, 'ProPrj_test_2026-09-23.epro2');
  assert.ok(data.data.startsWith('UEsD'));
  assert.equal(data.note, undefined, 'a real archive needs no note');
});

test('sys.get_project_file quotes its own gate, not the document export one', async () => {
  // The whole point of naming a gate: the user has to go and enable *that* one.
  const { eda } = fakeEda({
    sys_FileManager: {
      getProjectFile: async () => {
        throw new Error('download project is not permitted');
      },
    },
  });
  await assert.rejects(() => buildHandlers(eda)['sys.get_project_file']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /download project is not permitted/);
    assert.match(error.detail.gate, /下载工程/);
    assert.ok(!/^工程设计图/.test(error.detail.gate), 'the document gate must not be quoted here');
    assert.equal(error.detail.thrown, true);
    return true;
  });
});

test('sys.get_document_file keeps its own gate and now reports scope=document', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['sys.get_document_file']({});
  assert.deepEqual(calls.documentFile, [[undefined, undefined, 'epro2']]);
  assert.equal(data.scope, 'document', 'the shared reader must not relabel the old action');

  const refusing = fakeEda({
    sys_FileManager: {
      getDocumentFile: async () => {
        throw new Error('nope');
      },
    },
  });
  await assert.rejects(() => buildHandlers(refusing.eda)['sys.get_document_file']({}), (error) => {
    assert.match(error.detail.gate, /文件导出/);
    return true;
  });
});

test('a read whose declaration names no gate says so instead of borrowing one', async () => {
  // `getDocumentSource` is documented `@beta` with no permission note; quoting
  // the document-export gate for it would be an invented fact.
  const { eda } = fakeEda({
    sys_FileManager: {
      getDocumentSource: async () => {
        throw new Error('boom');
      },
    },
  });
  await assert.rejects(() => buildHandlers(eda)['sys.get_document_source']({}), (error) => {
    assert.equal(error.detail.gate, null);
    assert.match(error.message, /documents no permission gate for this call/);
    return true;
  });
});

test('sys.get_project_file names a missing method and refuses a bad fileType', async () => {
  const gone = fakeEda({ sys_FileManager: {} });
  await assert.rejects(() => buildHandlers(gone.eda)['sys.get_project_file']({}), (error) => {
    assert.equal(error.code, 'NOT_IMPLEMENTED');
    assert.match(error.message, /sys_FileManager\.getProjectFile/);
    return true;
  });

  const { eda, calls } = fakeEda();
  await assert.rejects(() => buildHandlers(eda)['sys.get_project_file']({ fileType: 'zip' }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /epro2 or epro/);
    return true;
  });
  assert.deepEqual(calls.projectFile, [], 'a bad argument never reaches the editor');
});

test('sys.probe call mode reaches sys.get_project_file through the registered handler', async () => {
  const { eda, calls } = fakeEda();
  const handlers = buildHandlers(eda);
  assert.ok('sys.get_project_file' in handlers, 'the action must be registered');

  const frame = await handlers['sys.probe']({
    call: { action: 'sys.get_project_file', params: { fileType: 'epro2' } },
  });
  assert.equal(frame.call.action, 'sys.get_project_file');
  assert.equal(frame.call.result.scope, 'project');
  assert.equal(frame.call.result.bytes, ZIP_BYTES.length);
  assert.deepEqual(calls.projectFile, [[undefined, undefined, 'epro2']]);
});
