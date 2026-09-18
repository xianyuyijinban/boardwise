const events = [];
try {
  eda.sys_WebSocket.register('probe-bw-1', 'ws://127.0.0.1:61190/eda',
    (ev) => events.push('msg:' + String(ev && ev.data).slice(0, 100)),
    () => events.push('connected-cb'));
} catch (e) {
  return { threw: String(e), events };
}
await new Promise((r) => setTimeout(r, 3000));
try { eda.sys_WebSocket.close('probe-bw-1'); } catch (e) { events.push('close-err:' + String(e)); }
return { threw: null, events };
