import sqlite3, base64, itertools, re
from Crypto.Cipher import AES

P = r"C:\Users\xiangyu\Desktop\CH340G.eprj2"
con = sqlite3.connect('file:' + P + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row

keys = {}
for r in con.execute('SELECT uuid, key FROM project_history_31ae28a5bbd24351a77f4a60a281d692'):
    keys[r['uuid']] = r['key']

row = con.execute('SELECT * FROM history_data ORDER BY id LIMIT 1').fetchone()
hu = row['history_uuid']
data = base64.b64decode(row['dataStr'])
k = keys.get(hu)
print('history_uuid:', hu)
print('key:', k, 'len', len(k))
print('dataStr len(chars):', len(row['dataStr']), 'decoded bytes:', len(data), 'mod16:', len(data) % 16)
print('first 32 bytes:', data[:32].hex())

candidates = []
if k:
    try:
        candidates.append(('hex16', bytes.fromhex(k)))
    except ValueError:
        pass
    candidates.append(('ascii32', k.encode()))

def score(pt: bytes) -> float:
    printable = sum(1 for b in pt if 32 <= b < 127 or b in (9, 10, 13))
    return printable / max(len(pt), 1)

def show(name, pt):
    s = score(pt)
    flag = '  <== LOOKS LIKE TEXT' if s > 0.9 else ''
    print(f'  {name:44s} score={s:.3f}{flag}')
    if s > 0.9:
        print('     ', pt[:180])

for kname, key in candidates:
    for klen in (len(key),):
        if klen not in (16, 24, 32):
            continue
        # ECB
        try:
            show(f'{kname}/ECB', AES.new(key, AES.MODE_ECB).decrypt(data[:len(data)//16*16]))
        except Exception as e:
            print('  ECB fail', e)
        # CBC zero iv
        try:
            show(f'{kname}/CBC(iv=0)', AES.new(key, AES.MODE_CBC, b'\x00'*16).decrypt(data[:len(data)//16*16]))
        except Exception as e:
            print('  CBC0 fail', e)
        # CBC prepended iv
        try:
            body = data[16:]
            body = body[:len(body)//16*16]
            show(f'{kname}/CBC(iv=ct[:16])', AES.new(key, AES.MODE_CBC, data[:16]).decrypt(body))
        except Exception as e:
            print('  CBCpre fail', e)
        # CTR variants
        for nonce_len, label in ((8, 'ctr8'), (16, 'ctr16'), (12, 'ctr12')):
            try:
                from Crypto.Util import Counter
                if nonce_len == 16:
                    ctr = Counter.new(128, initial_value=int.from_bytes(data[:16], 'big'))
                    ct = data[16:]
                else:
                    ctr = Counter.new(128, prefix=data[:nonce_len], initial_value=0)
                    ct = data[nonce_len:]
                show(f'{kname}/CTR({label})', AES.new(key, AES.MODE_CTR, counter=ctr).decrypt(ct))
            except Exception as e:
                print(f'  CTR {label} fail', e)
        # CFB / OFB
        for mode, mname in ((AES.MODE_CFB, 'CFB'), (AES.MODE_OFB, 'OFB')):
            try:
                show(f'{kname}/{mname}(iv=ct[:16])', AES.new(key, mode, iv=data[:16]).decrypt(data[16:]))
            except Exception as e:
                print(f'  {mname} fail', e)
