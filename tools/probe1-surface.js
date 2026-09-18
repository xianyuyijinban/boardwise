return {
  edaType: typeof eda,
  globalEdaType: typeof globalThis.eda,
  same: globalThis.eda === eda,
  hasWs: typeof eda.sys_WebSocket,
  hasGlobalWs: globalThis.eda ? typeof globalThis.eda.sys_WebSocket : 'no-global-eda',
  wsKeys: eda.sys_WebSocket ? Object.keys(eda.sys_WebSocket) : []
};
