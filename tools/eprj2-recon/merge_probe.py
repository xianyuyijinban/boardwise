import sqlite3, base64, gzip, json, collections
from Crypto.Cipher import AES

P = r"C:\Users\xiangyu\Desktop\CH340G.eprj2"
con = sqlite3.connect('file:' + P + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row
hist = {r['uuid']: r for r in
        con.execute('SELECT * FROM project_history_31ae28a5bbd24351a77f4a60a281d692')}

def decrypt(data_str, hu):
    key, iv = bytes.fromhex(hist[hu]['key']), bytes.fromhex(hu)
    blob = base64.b64decode(data_str)
    return gzip.decompress(
        AES.new(key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(blob[:-16], blob[-16:])
    ).decode('utf-8')

rows = list(con.execute('SELECT id, uuid, history_uuid, dataStr FROM history_data'))
rows.sort(key=lambda r: (hist[r['history_uuid']]['id'], r['id']))

chunks = []
for r in rows:
    chunks.append(decrypt(r['dataStr'], r['history_uuid']))
merged = '\n'.join(chunks)
print('merged chars:', len(merged))
open(r'C:\Users\xiangyu\WorkBuddy\2026-09-12-20-03-15\ch340g_merged.epru', 'w',
     encoding='utf-8').write(merged)

# census by document segment
cur = None
seg_types = collections.defaultdict(collections.Counter)
all_types = collections.Counter()
nrec = 0
for line in merged.split('\n'):
    if not line.strip():
        continue
    core = line[:-1] if line.endswith('|') else line
    if '||' not in core:
        continue
    nrec += 1
    es, bs = core.split('||', 1)
    try:
        env = json.loads(es); body = json.loads(bs) if bs.strip() else None
    except Exception:
        continue
    t = env.get('type')
    all_types[t] += 1
    if t == 'DOCHEAD' and body:
        cur = body.get('docType')
    seg_types[cur][t] += 1
print('total lines:', nrec)
print('documents:', {k: sum(v.values()) for k, v in seg_types.items()})
print()
print('PCB segment types:', dict(seg_types['PCB'].most_common(15)))
print()
for doc in ('FOOTPRINT', 'SYMBOL'):
    print(f'{doc} docs:', seg_types[doc].get('DOCHEAD'), ' PADs:', seg_types[doc].get('PAD'))
print('overall PAD:', all_types['PAD'], 'VIA:', all_types['VIA'], 'LINE:', all_types['LINE'],
      'FILL:', all_types['FILL'], 'POLY:', all_types['POLY'])
