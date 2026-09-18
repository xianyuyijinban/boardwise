import assert from 'node:assert/strict';
import test from 'node:test';

import {
  describeRandom,
  describeRandomHost,
  generateToken,
} from '../dist/esm/random.mjs';

/** A stand-in Web Crypto that fills the buffer deterministically. */
function fakeCrypto(fill) {
  return {
    getRandomValues: (array) => {
      array.fill(fill & 0xff);
      return array;
    },
  };
}

// --------------------------------------------------------------------------
// the happy path: the platform CSPRNG
// --------------------------------------------------------------------------


test('Web Crypto is used when the host offers it', () => {
  const generated = generateToken({ crypto: fakeCrypto(0xab) });

  assert.equal(generated.source, 'webcrypto');
  assert.equal(generated.token, 'ab'.repeat(32), '32 bytes, lowercase hex');
  assert.match(generated.token, /^[0-9a-f]{64}$/);
  assert.equal(generated.detail, 'crypto=ok');
});

test('a throwing getRandomValues falls through instead of losing the connector', () => {
  // The editor realm is not a browser realm; a getRandomValues that exists but
  // throws is a real possibility, and it must not become an unhandled error.
  const generated = generateToken({
    crypto: {
      getRandomValues: () => {
        throw new TypeError('not allowed in this realm');
      },
    },
    mathRandom: () => 0.5,
  });

  assert.equal(generated.source, 'math');
  assert.match(generated.token, /^[0-9a-f]{64}$/);
  assert.match(generated.detail, /threw TypeError/, `detail was: ${generated.detail}`);
  assert.equal(
    generated.detail.match(/threw/g).length,
    1,
    'the reason must be stated once, not appended twice',
  );
});

test('the description calls getRandomValues instead of trusting typeof', () => {
  // 0.2.1 reported `crypto=ok` on a realm where no token ever appeared, and that
  // "ok" sent the investigation down the wrong path for a round trip. A function
  // that exists and throws must never be described as usable.
  let called = 0;
  assert.equal(
    describeRandomHost({
      getRandomValues: (array) => {
        called += 1;
        array.fill(7);
        return array;
      },
    }),
    'crypto=ok',
  );
  assert.equal(called, 1, 'the verdict must come from a real call, not a typeof');

  assert.equal(
    describeRandomHost({
      getRandomValues: () => {
        throw new TypeError('blocked in this context');
      },
    }),
    'crypto=getRandomValues threw TypeError',
  );
});

test('a crypto object without getRandomValues is reported as such', () => {
  const generated = generateToken({ crypto: {}, mathRandom: () => 0 });

  assert.equal(generated.source, 'math');
  assert.equal(generated.detail, 'crypto=object, getRandomValues=undefined');
});

// --------------------------------------------------------------------------
// the fallback 0.2.0 did not have — and the honest reporting around it
// --------------------------------------------------------------------------


test('a host with no crypto at all still gets a token, and says how', () => {
  // This is the real editor on 2026-09-13: bare `crypto` did not resolve.
  const generated = generateToken({ crypto: undefined, mathRandom: () => 0.25 });

  assert.equal(generated.source, 'math', 'the fallback ran');
  assert.equal(generated.token, '40'.repeat(32), '0.25 * 256 = 64 = 0x40');
  assert.equal(generated.detail, 'crypto=unavailable');
});

test('the fallback is disclosed, never silent', () => {
  const generated = generateToken({ crypto: undefined, mathRandom: () => 0.1 });

  assert.equal(generated.source, 'math');
  // A caller that ignores `source` cannot warn; that is what `source` is for.
  assert.notEqual(generated.source, 'webcrypto');
  assert.ok(generated.detail.length > 0, 'a source we cannot describe is a bug');
});

test('two Math.random tokens differ — a repeated token is not a secret', () => {
  const first = generateToken({ crypto: undefined });
  const second = generateToken({ crypto: undefined });

  assert.match(first.token, /^[0-9a-f]{64}$/);
  assert.notEqual(first.token, second.token);
});

test('no source at all is reported as none with an empty token', () => {
  const generated = generateToken({ crypto: undefined, mathRandom: undefined });

  assert.equal(generated.source, 'none');
  assert.equal(generated.token, '');
  assert.equal(generated.detail, 'crypto=unavailable');
});

// --------------------------------------------------------------------------
// the diagnosis strings: readable, and never a secret
// --------------------------------------------------------------------------


test('describeRandomHost names each shape a host can present', () => {
  assert.equal(describeRandomHost(undefined), 'crypto=unavailable');
  assert.equal(describeRandomHost(null), 'crypto=unavailable');
  assert.equal(describeRandomHost('nope'), 'crypto=string');
  assert.equal(describeRandomHost({}), 'crypto=object, getRandomValues=undefined');
  assert.equal(
    describeRandomHost({ getRandomValues: () => {} }),
    'crypto=ok',
  );
});

test('the diagnosis never contains the token it describes', () => {
  // `detail` goes into the log panel and `About…`, both of which are visible
  // and exportable — the same rule the token itself lives under.
  for (const host of [
    { crypto: fakeCrypto(0x5a) },
    { crypto: undefined },
    { crypto: undefined, mathRandom: undefined },
  ]) {
    const generated = generateToken(host);
    if (generated.token) {
      assert.ok(
        !generated.detail.includes(generated.token),
        `detail leaked the token: ${generated.detail}`,
      );
    }
  }
});

test('describeRandom reports a host without throwing, injected or ambient', () => {
  // The editor realm may have no `crypto` at all; either way the function must
  // answer, because `About…` calls it with the facade's host.
  assert.match(describeRandom(), /^crypto=/);
  assert.match(describeRandom({ crypto: undefined }), /^crypto=unavailable$/);
});
