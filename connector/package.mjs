/**
 * Package the extension as a sideloadable `.eext`.
 *
 * An `.eext` is a ZIP of the extension folder: the manifest and the entry
 * bundle sit at the archive root, which is where the editor looks for
 * `extension.json` before following its `entry` field (`./dist/index`).
 *
 * **Status: layout conventional, not yet confirmed on a real sideload.** No
 * official `.eext` packaging spec was available when this was written (the
 * official format skill documents *document* formats, not extension packaging).
 * If the editor rejects the archive, installing from the folder works — the
 * archive adds no information the folder does not already have. Once 岳翔宇 has
 * sideloaded once, either confirm this layout here or correct it; do not leave
 * it half-known.
 *
 * Written with `node:zlib` only: a zip store is ~60 lines and a zip dependency
 * would be the connector's fourth, for a build step that runs maybe twice.
 * Output is deterministic (fixed DOS timestamp, fixed entry order) so the same
 * sources produce a byte-identical archive.
 *
 * Usage: node package.mjs [--out <path>]
 */

import { readFile, writeFile } from 'node:fs/promises';
import { deflateRawSync, crc32 } from 'node:zlib';
import { pathToFileURL } from 'node:url';

const manifest = JSON.parse(
  await readFile(new URL('./extension.json', import.meta.url), 'utf8'),
);

/** What ships. `dist/esm/` is deliberately absent: it exists for the tests. */
const ENTRIES = ['extension.json', 'dist/index.js'];

/** 1980-01-01 00:00 in DOS format — the zip epoch, fixed for reproducibility. */
const DOS_TIME = 0;
const DOS_DATE = 0x0021;

function u16(value) {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16LE(value);
  return buffer;
}

function u32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value >>> 0);
  return buffer;
}

/**
 * Build a ZIP from `{name, data}` entries.
 *
 * Stored with deflate (method 8) rather than no compression: the entry bundle
 * is a few hundred kilobytes of JS that compresses well, and a smaller archive
 * is faster to sideload. Sizes and CRC are read from the *compressed* buffer,
 * which is what the format requires.
 */
function zip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;

  for (const { name, data } of entries) {
    const nameBytes = Buffer.from(name, 'utf8');
    const compressed = deflateRawSync(data, { level: 9 });
    const checksum = crc32(data);
    const uncompressedSize = data.length;
    const compressedSize = compressed.length;

    const local = Buffer.concat([
      u32(0x04034b50), // local file header
      u16(20), // version needed
      u16(0), // flags
      u16(8), // method: deflate
      u16(DOS_TIME),
      u16(DOS_DATE),
      u32(checksum),
      u32(compressedSize),
      u32(uncompressedSize),
      u16(nameBytes.length),
      u16(0), // extra length
      nameBytes,
      compressed,
    ]);
    locals.push(local);

    centrals.push(
      Buffer.concat([
        u32(0x02014b50), // central directory header
        u16(20), // version made by
        u16(20), // version needed
        u16(0), // flags
        u16(8), // method
        u16(DOS_TIME),
        u16(DOS_DATE),
        u32(checksum),
        u32(compressedSize),
        u32(uncompressedSize),
        u16(nameBytes.length),
        u16(0), // extra length
        u16(0), // comment length
        u16(0), // disk number
        u16(0), // internal attributes
        u32(0), // external attributes
        u32(offset), // offset of the local header
        nameBytes,
      ]),
    );
    offset += local.length;
  }

  const central = Buffer.concat(centrals);
  const end = Buffer.concat([
    u32(0x06054b50), // end of central directory
    u16(0), // this disk
    u16(0), // disk with central directory
    u16(centrals.length),
    u16(centrals.length),
    u32(central.length),
    u32(offset),
    u16(0), // comment length
  ]);

  return Buffer.concat([...locals, central, end]);
}

const outIndex = process.argv.indexOf('--out');
const out =
  outIndex === -1
    ? new URL(`./${manifest.name}-${manifest.version}.eext`, import.meta.url)
    : pathToFileURL(process.argv[outIndex + 1]);

const entries = [];
for (const name of ENTRIES) {
  entries.push({ name, data: await readFile(new URL(`./${name}`, import.meta.url)) });
}

const archive = zip(entries);
await writeFile(out, archive);

const name = out.pathname.split('/').pop();
console.log(`boardwise connector: ${name}`);
console.log(`  ${entries.length} entries: ${ENTRIES.join(', ')}`);
for (const entry of entries) {
  console.log(`    ${entry.name}  ${entry.data.length} bytes`);
}
console.log(`  archive ${archive.length} bytes`);
