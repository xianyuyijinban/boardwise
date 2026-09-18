// Minimal stand-in for `@jlceda/pro-api-types/index.d.ts`.
//
// It exists so the *parser* in `tools/api_names.py` is testable without the
// real package installed — and so the shapes that broke it have a permanent,
// readable home. Each block below is a former bug, not filler.

declare global {
	/**
	 * A namespace whose `{@link https://example.com}` prose contains a brace.
	 *
	 * @remarks
	 * See {@link https://example.com/docs} for more, and note the nested
	 * {@link https://example.com/x{a}} variant.
	 */
	class SCH_Thing {
		/**
		 * Does the thing.
		 *
		 * ADD since EDA v3.2.170
		 * @beta
		 * @public
		 */
		public doIt(width?: number): Promise<{ ok: boolean }>;
		/**
		 * Gets the thing.
		 *
		 * @public
		 */
		public getIt(): Promise<{ text: string; value: string }>;
		/** @internal */
		private extensionUuid?: string;
	}

	/** A class immediately after, to prove the body ended. */
	class SCH_Other {
		/** @public */
		public onlyThis(): boolean;
	}

	class EDA {
		public sch_Thing: SCH_Thing;
		public sch_Other: SCH_Other;
	}
	const eda: EDA;
}

export {};
