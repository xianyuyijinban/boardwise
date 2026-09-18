"""Rebuild the final document state from an .eprj2 history chain.

Model: records are an edit log. For a given (type, id) key the LAST record
wins; a record with an empty body means the element was deleted.
"""
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

records = []  # (order, env, body_or_None)
for r in rows:
    for line in decrypt(r['dataStr'], r['history_uuid']).split('\n'):
        if not line.strip():
            continue
        core = line[:-1] if line.endswith('|') else line
        if '||' not in core:
            continue
        es, bs = core.split('||', 1)
        try:
            env = json.loads(es)
        except ValueError:
            continue
        body = json.loads(bs) if bs.strip() else None
        records.append((env, body))

print('raw records:', len(records))

# last-wins state; each key remembers which document it belongs to
state: dict[tuple, dict] = {}
doc_order: list[tuple] = []          # ordered doc keys (DOCHEAD keys)
doc_members: dict[tuple, list[tuple]] = collections.defaultdict(list)
current_doc: tuple | None = None

for env, body in records:
    t = env.get('type')
    if t == 'EDIT_HEAD':
        continue
    if t == 'DOCHEAD':
        current_doc = ('DOCHEAD', (body or {}).get('uuid'))
        key = current_doc
        if key not in state:
            doc_order.append(key)
    else:
        key = (t, env.get('id'))
        if key not in state:
            doc_members[current_doc].append(key)
    prev = state.get(key)
    state[key] = {'env': env, 'body': body, 'n': (prev['n'] if prev else 0) + 1,
                  'deleted': prev['deleted'] if prev else False}
    if body is None:
        state[key]['deleted'] = True
        state[key]['body'] = prev['body'] if prev else None

all_keys = list(doc_order) + [k for v in doc_members.values() for k in v]
deleted = [k for k in all_keys if k in state and state[k]['deleted']]
dupes = [k for k in all_keys if k in state and state[k]['n'] > 1]
alive = [k for k in all_keys if k in state and not state[k]['deleted']
         and state[k]['body'] is not None]
print('unique keys:', len(state), 'alive:', len(alive), 'deleted:', len(deleted),
      'updated more than once:', len(dupes))
print('deleted by type:', collections.Counter(k[0] for k in deleted).most_common(8))
print('updated-by-type:', collections.Counter(k[0] for k in dupes).most_common(8))

# rebuild: document head first, then its members — in first-seen order
out = []
for doc_key in doc_order:
    st = state.get(doc_key)
    if st is None or st['deleted'] or st['body'] is None:
        continue
    out.append(json.dumps(st['env'], separators=(',', ':')) + '||' +
               json.dumps(st['body'], separators=(',', ':')) + '|')
    for key in doc_members[doc_key]:
        m = state[key]
        if m['deleted'] or m['body'] is None:
            continue
        out.append(json.dumps(m['env'], separators=(',', ':')) + '||' +
                   json.dumps(m['body'], separators=(',', ':')) + '|')
text = '\n'.join(out) + '\n'
open(r'C:\Users\xiangyu\WorkBuddy\2026-09-12-20-03-15\ch340g_final.epru', 'w',
     encoding='utf-8').write(text)
print('rebuilt chars:', len(text))
