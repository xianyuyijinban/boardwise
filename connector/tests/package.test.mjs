/**
 * Verifies the `.eext` is a real ZIP, not just bytes that happen to be written.
 *
 * The packager has no zip dependency to lean on, so nothing else checks that
 * the CRCs, sizes and central directory are consistent — a reader (in this
 * case, the test) is the only proof. The archive is parsed here the way a
 * reader does: end-of-central-directory record, then the central directory,
 * then each local header. Wrapping it in `zipfile` on the Python side would
 * test the same bytes against a different implementation; this keeps the
 * connector's own verification self-contained.
 */

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { crc32, inflateRawSync } from 'node:zlib';

const CONNECTOR = new URL('../', import.meta.url);
const SCRIPT = fileURLToPath(new URL('package.mjs', CONNECTOR));

const SIGNATURE = {
  local: 0x04034b50,
  central: 0x02014b50,
  end: 0x06054b50,
};

/** Walk the central directory, the way any zip reader starts. */
function centralDirectory(buffer) {
  const eocd = buffer.length - 22;
  assert.equal(buffer.readUInt32LE(eocd), SIGNATURE.end, 'no end-of-central-directory record');
  const count = buffer.readUInt16LE(eocd + 10);
  let offset = buffer.readUInt32LE(eocd + 16);

  const entries = [];
  for (let index = 0; index < count; index += 1) {
    assert.equal(
      buffer.readUInt32LE(offset),
      SIGNATURE.central,
      `bad central directory signature at entry ${index}`,
    );
    const nameLength = buffer.readUInt16LE(offset + 28);
    const extraLength = buffer.readUInt16LE(offset + 30);
    const commentLength = buffer.readUInt16LE(offset + 32);
    entries.push({
      name: buffer.subarray(offset + 46, offset + 46 + nameLength).toString('utf8'),
      method: buffer.readUInt16LE(offset + 10),
      crc: buffer.readUInt32LE(offset + 16),
      compressedSize: buffer.readUInt32LE(offset + 20),
      uncompressedSize: buffer.readUInt32LE(offset + 24),
      localOffset: buffer.readUInt32LE(offset + 42),
    });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

/** Pull one entry's bytes out via its local header. */
function extract(buffer, entry) {
  const base = entry.localOffset;
  assert.equal(buffer.readUInt32LE(base), SIGNATURE.local, `bad local header for ${entry.name}`);
  const nameLength = buffer.readUInt16LE(base + 26);
  const extraLength = buffer.readUInt16LE(base + 28);
  const start = base + 30 + nameLength + extraLength;
  const raw = buffer.subarray(start, start + entry.compressedSize);
  return entry.method === 8 ? inflateRawSync(raw) : raw;
}

function buildArchive() {
  const dir = mkdtempSync(join(tmpdir(), 'boardwise-eext-'));
  const out = join(dir, 'connector.eext');
  execFileSync(process.execPath, [SCRIPT, '--out', out], {
    cwd: CONNECTOR,
    stdio: 'pipe',
  });
  return readFileSync(out);
}

test('the .eext is a valid zip carrying the manifest and the entry bundle', () => {
  const buffer = buildArchive();
  const entries = centralDirectory(buffer);

  assert.deepEqual(
    entries.map((entry) => entry.name).sort(),
    ['dist/index.js', 'extension.json'],
    'dist/esm is test-only and must not ship',
  );

  for (const entry of entries) {
    assert.equal(entry.method, 8, `${entry.name} should be deflated`);
    const content = extract(buffer, entry);
    assert.equal(content.length, entry.uncompressedSize, `${entry.name} size mismatch`);
    assert.equal(crc32(content), entry.crc, `${entry.name} CRC mismatch`);
    // Round-tripping against the file on disk proves the archive carries the
    // current build rather than a stale copy.
    const onDisk = readFileSync(new URL(`../${entry.name}`, import.meta.url));
    assert.ok(content.equals(onDisk), `${entry.name} differs from the built file`);
  }
});

test('the manifest entry field points at a file the archive actually contains', () => {
  // The editor reads `entry` from the manifest and appends `.js`; if the two
  // ever disagree the extension loads nothing, silently.
  const buffer = buildArchive();
  const entries = centralDirectory(buffer);
  const manifestEntry = entries.find((entry) => entry.name === 'extension.json');
  assert.ok(manifestEntry, 'extension.json is missing from the archive');
  const manifest = JSON.parse(extract(buffer, manifestEntry).toString('utf8'));
  const names = entries.map((entry) => entry.name);

  assert.equal(manifest.entry, './dist/index');
  const resolved = `${manifest.entry.replace(/^\.\//, '')}.js`;
  assert.ok(names.includes(resolved), `manifest entry ${resolved} is not in the archive`);
  assert.match(manifest.uuid, /^[0-9a-f]{32}$/);
});
