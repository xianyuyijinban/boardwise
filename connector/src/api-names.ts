/**
 * Candidate member names per namespace, read out of the offline type package.
 *
 * **Generated — do not edit by hand.** Regenerate with:
 *
 *     python tools/api_names.py --emit-ts connector/src/api-names.ts sch_ManufactureData dmt_EditorControl dmt_Schematic dmt_Pcb sch_Document sch_PrimitiveComponent sch_PrimitivePin
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
};
