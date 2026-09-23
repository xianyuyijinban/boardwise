/**
 * Candidate member names per namespace, read out of the offline type package.
 *
 * **Generated — do not edit by hand.** Regenerate with:
 *
 *     python tools/api_names.py --emit-ts connector/src/api-names.ts sch_ManufactureData dmt_EditorControl dmt_Schematic dmt_Pcb sch_Document sch_PrimitiveComponent sch_PrimitivePin pcb_Drc sch_Drc sys_FileManager sys_Tool
 *
 * Why a generated table instead of enumerating the live object: on
 * 2026-09-14 the on-machine probe died on *every* namespace with
 * "Cannot read properties of undefined (reading 'prototype')", because the
 * editor's extension host hands out *exotic* objects whose
 * `getOwnPropertyNames`/`getPrototypeOf` throw. Enumeration is therefore a
 * measurement that can fail on exactly the object under study.
 *
 * `typeof ns[name]` cannot fail that way: property access walks the prototype
 * chain as part of the language. So the stable path is
 *
 *     for each name the type package declares: typeof ns[name]
 *
 * and this module supplies "each name the type package declares" without
 * asking the running editor anything.
 *
 * A namespace missing here is not an error — the enumerate mode of
 * `sys.probe` still covers it. This table is the *complete declared surface*
 * for the namespaces the roadmap depends on.
 */

export const PROBE_CHECKS: Record<string, string[]> = {
  // 8.3 — the acceptance image. `getPngFile`/`getSvgFile` are declared
  // `ADD since EDA v3.2.183`, yet the host (3.2.186) answers NOT_IMPLEMENTED
  // for the render path; this is the check that separates a rename from an
  // absence.
  sch_ManufactureData: [
    'deleteBomTemplate',
    'getAssemblyVariantsConfigs',
    'getBomFile',
    'getBomTemplateFile',
    'getBomTemplates',
    'getExportDocumentFile',
    'getNetlistFile',
    'getPngFile',
    'getSimulationNetlistFile',
    'getSvgFile',
    'placeComponentsOrder',
    'placeSmtComponentsOrder',
    'uploadBomTemplateFile',
  ],
  // 006c — `doc.open`: which tab is focused, and how to move focus. A page
  // created by `sch.doc.new` anchors to the front tab, so this is the pair
  // that makes "draw into page X" verifiable.
  dmt_EditorControl: [
    'activateDocument',
    'activateSplitScreen',
    'closeDocument',
    'createSplitScreen',
    'generateIndicatorMarkers',
    'getCurrentRenderedAreaImage',
    'getSplitScreenIdByTabId',
    'getSplitScreenTree',
    'getTabsBySplitScreenId',
    'mergeAllDocumentFromSplitScreen',
    'moveDocumentToSplitScreen',
    'openDocument',
    'openLibraryDocument',
    'removeIndicatorMarkers',
    'tileAllDocumentToSplitScreen',
    'zoom',
    'zoomTo',
    'zoomToAllPrimitives',
    'zoomToRegion',
    'zoomToSelectedPrimitives',
  ],
  // 006c — page creation. `createSchematic` returned empty on a blank project
  // (measured), so `createSchematicPage` is the shape to verify.
  dmt_Schematic: [
    'copySchematic',
    'copySchematicPage',
    'createSchematic',
    'createSchematicPage',
    'deleteSchematic',
    'deleteSchematicPage',
    'getAllSchematicPagesInfo',
    'getAllSchematicsInfo',
    'getCurrentSchematicAllSchematicPagesInfo',
    'getCurrentSchematicInfo',
    'getCurrentSchematicPageInfo',
    'getSchematicInfo',
    'getSchematicPageInfo',
    'modifySchematicName',
    'modifySchematicPageName',
    'modifySchematicPageTitleBlock',
    'reorderSchematicPages',
  ],
  // The PCB half of the design model — the 001/002 readback line.
  dmt_Pcb: [
    'copyPcb',
    'createPcb',
    'deletePcb',
    'getAllPcbsInfo',
    'getCurrentPcbInfo',
    'getPcbInfo',
    'modifyPcbName',
  ],
  // `save` is the step that makes the netlist export reliable: an unsaved page
  // has no netlist to hand back.
  sch_Document: [
    'autoLayout',
    'autoRouting',
    'getCurrentFilterConfiguration',
    'getPrimitiveAtPoint',
    'getPrimitivesInRegion',
    'importChanges',
    'navigateToCoordinates',
    'navigateToRegion',
    'save',
  ],
  // SCH_PrimitiveComponent
  sch_PrimitiveComponent: [
    'constructor',
    'create',
    'createCbbSymbol',
    'createNetFlag',
    'createNetPort',
    'createShortCircuitFlag',
    'delete',
    'get',
    'getAll',
    'getAllPinsByPrimitiveId',
    'getAllPrimitiveId',
    'getAllPropertyNames',
    'modify',
    'placeCbbSchematicPage',
    'placeComponentWithMouse',
    'placeSymbolWithMouse',
    'setNetFlagComponentUuid_AnalogGround',
    'setNetFlagComponentUuid_Ground',
    'setNetFlagComponentUuid_Power',
    'setNetFlagComponentUuid_ProtectGround',
    'setNetPortComponentUuid_BI',
    'setNetPortComponentUuid_IN',
    'setNetPortComponentUuid_OUT',
  ],
  // SCH_PrimitivePin
  sch_PrimitivePin: [
    'create',
    'delete',
    'get',
    'getAll',
    'getAllPrimitiveId',
    'modify',
  ],
  // 025 — the PCB design-rule check. `check` is @beta and measured (025 §0) to
  // return **per-item** groups, unlike the schematic one: leaves carry
  // ruleName / net / pos / explanation / obj1 / obj2 / layer, which is what a
  // Finding-mapping layer reads. `startRealTimeDrc` / `stopRealTimeDrc` /
  // `getRealTimeDrcStatus` are hard-coded `return false` stubs on the host —
  // listed here so that stays measurable rather than assumed.
  pcb_Drc: [
    'addNetToEqualLengthNetGroup',
    'addNetToNetClass',
    'addPadPairToPadPairGroup',
    'check',
    'createDifferentialPair',
    'createEqualLengthNetGroup',
    'createNetClass',
    'createPadPairGroup',
    'deleteDifferentialPair',
    'deleteEqualLengthNetGroup',
    'deleteNetClass',
    'deletePadPairGroup',
    'deleteRuleConfiguration',
    'getAllDifferentialPairs',
    'getAllEqualLengthNetGroups',
    'getAllNetClasses',
    'getAllPadPairGroups',
    'getAllRuleConfigurations',
    'getCurrentRuleConfiguration',
    'getCurrentRuleConfigurationName',
    'getDefaultRuleConfigurationName',
    'getNetByNetRules',
    'getNetRules',
    'getPadPairGroupMinWireLength',
    'getRealTimeDrcStatus',
    'getRegionRules',
    'getRuleConfiguration',
    'modifyDifferentialPairName',
    'modifyDifferentialPairNegativeNet',
    'modifyDifferentialPairPositiveNet',
    'modifyEqualLengthNetGroupName',
    'modifyNetClassName',
    'modifyPadPairGroupName',
    'overwriteCurrentRuleConfiguration',
    'overwriteNetByNetRules',
    'overwriteNetRules',
    'overwriteRegionRules',
    'removeNetFromEqualLengthNetGroup',
    'removeNetFromNetClass',
    'removePadPairFromPadPairGroup',
    'renameRuleConfiguration',
    'saveRuleConfiguration',
    'setAsDefaultRuleConfiguration',
    'startRealTimeDrc',
    'stopRealTimeDrc',
  ],
  // 025 — the schematic design-rule check. One method, @beta, and measured
  // (025 §0) to answer **aggregate counts only** even with
  // includeVerboseError:true; the per-item detail goes to a bottom panel with
  // no read interface, which is why the offline rule engine still supplies
  // the per-item findings (batch 3).
  sch_Drc: [
    'check',
  ],
  // 025 — where a project leaves the editor: `getDocumentFile` / `getProjectFile`
  // return an .epro/.epro2 as a `File`. Both are documented to **throw** when
  // the extension lacks a grant (工程设计图 > 文件导出 / 工程管理 > 下载工程), which
  // is the permission question batch 1 had to measure rather than read off the
  // declaration. `getDocumentSource` is the unverified second path.
  sys_FileManager: [
    'extractLibInfo',
    'extractProjectInfo',
    'getCbbFileByCbbUuid',
    'getDeviceFileByDeviceUuid',
    'getDocumentFile',
    'getDocumentFootprintSources',
    'getDocumentSource',
    'getFootprintFileByFootprintUuid',
    'getPanelLibraryFileByPanelLibraryUuid',
    'getProjectFile',
    'getProjectFileByProjectUuid',
    'getSchematicFile',
    'getSymbolFileBySymbolUuid',
    'importProjectByProjectFile',
    'setDocumentSource',
  ],
  // 025 — the host's own comparison tools (`netlistComparison`,
  // `schematicComparison`, `pcbComparison`). Probed alongside the DRC
  // namespaces because a "what changed?" review lane would need them, and
  // because the declared surface and the live one have disagreed before.
  sys_Tool: [
    'netlistComparison',
    'pcbComparison',
    'schematicComparison',
  ],
};

/**
 * Methods the type package marks `ADD since EDA v…` — the ones where an
 * `undefined` answer is evidence rather than a surprise.
 */
export const ADDED_SINCE: Record<string, Record<string, string>> = {
  sch_ManufactureData: {
    getPngFile: 'v3.2.183',
    getSvgFile: 'v3.2.183',
  },
  sys_FileManager: {
    getSchematicFile: 'v3.2.183',
  },
};
