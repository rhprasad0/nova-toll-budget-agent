/** The consumed MapLibre 6 API; vendored implementation stays untouched. */
type Coordinates = number[];
type Bounds = Coordinates[];
interface BoundsOptions { padding: number; duration: number }
export class Map {
  constructor(options: { container: string; style: string; bounds: Bounds; fitBoundsOptions: BoundsOptions; maxBounds: Bounds; cooperativeGestures: boolean; dragRotate: boolean; attributionControl: boolean });
  touchPitch: { disable(): void };
  keyboard: { disableRotation(): void };
  addControl(control: NavigationControl | AttributionControl, position: "top-right" | "bottom-right"): this;
  fitBounds(bounds: Bounds, options: BoundsOptions): this;
  on(event: "load", callback: () => void): this;
  on(event: "error", callback: (event: { error: Error }) => void): this;
  addSource(id: string, source: { type: "geojson"; data: { type: string; features: { type: string; properties: object; geometry: { type: string; coordinates: number[][][] } }[] } }): this;
  addLayer(layer: { id: string; type: "line"; source: string; paint: { "line-color": string | (string | string[])[]; "line-width": number; "line-opacity": number } }): this;
}
export class NavigationControl { constructor(options: { showCompass: boolean }); }
export class AttributionControl { constructor(options: { customAttribution: string; compact: boolean }); }
export class Marker {
  constructor(options: { element: HTMLElement; anchor: "center" | "bottom" });
  setLngLat(coordinates: Coordinates): this;
  addTo(map: Map): this;
}
