import sqlite3, base64, gzip, json
from Crypto.Cipher import AES

P = r"C:\Users\xiangyu\Desktop\CH340G.eprj2"
con = sqlite3.connect('file:' + P + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row

keys = {}
for r in con.execute('SELECT uuid, key FROM project_history_31ae28a5bbd24351a77f4a60a281d692'):
    keys[r['uuid']] = r['key']

def decrypt(data_str, history_uuid):
    key = bytes.fromhex(keys[history_uuid])
    iv = bytes.fromhex(history_uuid)
    blob = base64.b64decode(data_str)
    ct, tag = blob[:-16], blob[-16:]
    pt = AES.new(key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(ct, tag)
    return gzip.decompress(pt).decode('utf-8')

ok = fail = 0
for r in con.execute('SELECT id, uuid, history_uuid, dataStr FROM history_data ORDER BY id'):
    hu = r['history_uuid']
    if hu not in keys:
        print(f'  id={r["id"]} no key for {hu}')
        fail += 1
        continue
    try:
        text = decrypt(r['dataStr'], hu)
        ok += 1
        if ok <= 3:
            print(f'--- id={r["id"]} history={hu[:12]} len={len(text)}')
            print(text[:600].replace('\n', ' | ')[:600])
            print()
    except Exception as e:
        fail += 1
        if fail <= 3:
            print(f'  id={r["id"]} FAIL {type(e).__name__}: {e}')
print(f'OK={ok} FAIL={fail}')
