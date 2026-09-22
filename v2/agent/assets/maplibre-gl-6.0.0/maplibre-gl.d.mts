/** The consumed MapLibre 6 API; vendored implementation stays untouched. */
type Coordinates = number[];
type Bounds = Coordinates[];
interface BoundsOptions { padding: number | { top: number; right: number; bottom: number; left: number }; duration: number }
export class Map {
  constructor(options: { container: string; style: string; bounds: Bounds; fitBoundsOptions: BoundsOptions; cooperativeGestures: boolean; dragRotate: boolean; attributionControl: boolean });
  getContainer(): HTMLElement;
  project(coordinates: Coordinates): { x: number; y: number };
  isStyleLoaded(): boolean;
  getPaintProperty(layer: string, property: string): unknown;
  getFilter(layer: string): unknown;
  jumpTo(options: { center: Coordinates; zoom: number }): this;
  queryRenderedFeatures(options: { layers: string[] }): { properties: Record<string, unknown> }[];
  touchPitch: { disable(): void };
  keyboard: { disableRotation(): void };
  addControl(control: NavigationControl | AttributionControl, position: "top-right" | "bottom-right"): this;
  resize(): this;
  fitBounds(bounds: Bounds, options: BoundsOptions): this;
  on(event: "load", callback: () => void): this;
  on(event: "error", callback: (event: { error: Error }) => void): this;
  addSource(id: string, source: { type: "geojson"; data: { type: string; features: { type: string; properties: object; geometry: { type: string; coordinates: number[][][] } }[] } }): this;
  addLayer(layer: { id: string; type: "line"; source: string; minzoom?: number; filter?: (string | string[])[]; layout: { "line-cap": "round"; "line-join": "round" }; paint: { "line-color": string | (string | string[])[]; "line-width": number | (string | string[] | number)[]; "line-opacity"?: number; "line-dasharray"?: number[] } }): this;
}
export class NavigationControl { constructor(options: { showCompass: boolean }); }
export class AttributionControl { constructor(options: { customAttribution: string; compact: boolean }); }
export class Marker {
  constructor(options: { element: HTMLElement; anchor: "center" | "bottom" | "top" });
  setLngLat(coordinates: Coordinates): this;
  addTo(map: Map): this;
}
