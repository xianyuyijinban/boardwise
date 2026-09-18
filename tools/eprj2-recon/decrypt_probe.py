import sqlite3, base64, gzip, json, collections
from Crypto.Cipher import AES

P = r"C:\Users\xiangyu\Desktop\CH340G.eprj2"
con = sqlite3.connect('file:' + P + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row
keys = {r['uuid']: r['key'] for r in
        con.execute('SELECT uuid, key FROM project_history_31ae28a5bbd24351a77f4a60a281d692')}
order = {r['uuid']: r['id'] for r in
         con.execute('SELECT uuid, id FROM project_history_31ae28a5bbd24351a77f4a60a281d692')}

def decrypt(data_str, hu):
    key, iv = bytes.fromhex(keys[hu]), bytes.fromhex(hu)
    blob = base64.b64decode(data_str)
    return gzip.decompress(
        AES.new(key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(blob[:-16], blob[-16:])
    ).decode('utf-8')

docs = []
for r in con.execute('SELECT id, uuid, history_uuid, dataStr FROM history_data ORDER BY id'):
    text = decrypt(r['dataStr'], r['history_uuid'])
    types = collections.Counter()
    for line in text.split('\n'):
        if not line.strip() or '||' not in line:
            continue
        try:
            env = json.loads(line.rstrip('|').split('||', 1)[0])
        except Exception:
            continue
        if env.get('type') == 'DOCHEAD':
            try:
                body = json.loads(line.rstrip('|').split('||', 1)[1])
                types[body.get('docType')] += 1
            except Exception:
                pass
    docs.append((r['id'], order.get(r['history_uuid'], 0), len(text), dict(types), text))

print(f"{'id':>4} {'hist':>4} {'chars':>7}  docTypes")
for i, h, n, t, _ in docs:
    if t:
        print(f'{i:>4} {h:>4} {n:>7}  {t}')

pcb = [d for d in docs if 'PCB' in d[3]]
print('\nrecords containing a PCB document:', [(d[0], d[2]) for d in pcb])
if pcb:
    best = max(pcb, key=lambda d: d[2])
    print('largest PCB record id', best[0], 'chars', best[2])
    open(r'C:\Users\xiangyu\WorkBuddy\2026-09-12-20-03-15\ch340g_decrypted.epru', 'w',
         encoding='utf-8').write(best[4])
    print('written to ch340g_decrypted.epru')
