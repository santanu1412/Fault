/**
 * MapView — MapLibre GL map using GeoJSON source layers for GPU-accelerated pole rendering.
 * 
 * Uses circle layers instead of DOM markers for poles (3,000+ with 3s polling).
 * DOM markers used only for DTs (fewer, richer popups).
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { PoleData, TransformerData, Ticket } from '../../types';

interface Props {
  poles: PoleData[];
  transformers: TransformerData[];
  selectedTicket: Ticket | null;
}

const CLASSIFICATION_COLORS: Record<string, string> = {
  ok: '#22c55e',
  dark_confirmed: '#ef4444',
  sensor_suspect: '#f97316',
  unknown: '#6b7280',
};

export default function MapView({ poles, transformers, selectedTicket }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const dtMarkersRef = useRef<maplibregl.Marker[]>([]);
  const [mapReady, setMapReady] = useState(false);
  const initialBoundsSet = useRef(false);
  const prevSelectedId = useRef<number | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  // Initialize map
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          'osm-tiles': {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [
          {
            id: 'osm-tiles',
            type: 'raster',
            source: 'osm-tiles',
            minzoom: 0,
            maxzoom: 19,
          },
        ],
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      },
      center: [77.5946, 12.9716], // Bangalore
      zoom: 12,
    });

    map.on('load', () => {
      // Dark overlay for ops console aesthetic
      map.addSource('dark-overlay', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]],
          },
          properties: {},
        },
      });
      map.addLayer({
        id: 'dark-overlay',
        type: 'fill',
        source: 'dark-overlay',
        paint: {
          'fill-color': '#0a0e17',
          'fill-opacity': 0.55,
        },
      });

      // Empty GeoJSON source for poles — will be updated on data changes
      map.addSource('poles', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // Pole circle layer — normal poles
      map.addLayer({
        id: 'poles-layer',
        type: 'circle',
        source: 'poles',
        paint: {
          'circle-radius': [
            'case',
            ['get', 'isInIncident'], 6,
            4
          ],
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.9,
          'circle-stroke-width': [
            'case',
            ['!', ['get', 'hasDevice']], 1,
            ['get', 'isInIncident'], 1.5,
            0
          ],
          'circle-stroke-color': [
            'case',
            ['!', ['get', 'hasDevice']], '#6b7280',
            '#ffffff'
          ],
          'circle-stroke-opacity': 0.6,
        },
      });

      // Glow layer for incident poles
      map.addLayer({
        id: 'poles-glow',
        type: 'circle',
        source: 'poles',
        filter: ['==', ['get', 'isInIncident'], true],
        paint: {
          'circle-radius': 12,
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.15,
          'circle-blur': 1,
        },
      }, 'poles-layer'); // Insert before poles layer

      setMapReady(true);
    });

    // Click handler for pole popups
    map.on('click', 'poles-layer', (e) => {
      if (!e.features || e.features.length === 0) return;
      const f = e.features[0];
      const props = f.properties;
      const coords = (f.geometry as GeoJSON.Point).coordinates as [number, number];
      const color = props?.color || '#6b7280';

      if (popupRef.current) popupRef.current.remove();

      popupRef.current = new maplibregl.Popup({ offset: 8, className: 'dark-popup' })
        .setLngLat(coords)
        .setHTML(`
          <div style="background:#1e293b;color:#e2e8f0;padding:8px;border-radius:6px;font-size:11px;font-family:'JetBrains Mono',monospace;">
            <b>${props?.pole_id || ''}</b><br/>
            DT: ${props?.dt_id || ''}<br/>
            Device: ${props?.device_id || 'NONE'}<br/>
            Status: <span style="color:${color}">${props?.classification || 'unknown'}</span><br/>
            ${props?.pincode ? `PIN: ${props.pincode}` : ''}
          </div>
        `)
        .addTo(map);
    });

    // Cursor change on hover
    map.on('mouseenter', 'poles-layer', () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'poles-layer', () => {
      map.getCanvas().style.cursor = '';
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Build GeoJSON from poles data
  const buildPolesGeoJSON = useCallback((polesData: PoleData[], darkPoleSet: Set<string>) => {
    return {
      type: 'FeatureCollection' as const,
      features: polesData.map(pole => ({
        type: 'Feature' as const,
        geometry: {
          type: 'Point' as const,
          coordinates: [pole.lon, pole.lat],
        },
        properties: {
          pole_id: pole.pole_id,
          dt_id: pole.dt_id,
          device_id: pole.device_id || 'NONE',
          hasDevice: pole.has_device,
          classification: pole.classification,
          pincode: pole.pincode || '',
          color: CLASSIFICATION_COLORS[pole.classification] || '#6b7280',
          isInIncident: darkPoleSet.has(pole.pole_id),
        },
      })),
    };
  }, []);

  // Update GeoJSON source when pole data changes (no DOM creation!)
  useEffect(() => {
    if (!mapRef.current || !mapReady) return;

    const map = mapRef.current;
    const darkPoleSet = new Set(selectedTicket?.incident?.dark_pole_ids || []);
    const source = map.getSource('poles') as maplibregl.GeoJSONSource;

    if (source) {
      source.setData(buildPolesGeoJSON(poles, darkPoleSet));
    }
  }, [poles, selectedTicket, mapReady, buildPolesGeoJSON]);

  // Update DT markers (fewer, need richer popups — DOM markers are fine here)
  useEffect(() => {
    if (!mapRef.current || !mapReady) return;

    const map = mapRef.current;

    // Clear existing DT markers
    dtMarkersRef.current.forEach(m => m.remove());
    dtMarkersRef.current = [];

    transformers.forEach(dt => {
      const el = document.createElement('div');
      el.className = 'dt-marker';
      el.style.cssText = `
        width: 14px; height: 14px; 
        background: #3b82f6; 
        border: 2px solid #93c5fd; 
        border-radius: 3px; 
        cursor: pointer;
        box-shadow: 0 0 6px rgba(59, 130, 246, 0.5);
      `;
      el.title = `${dt.dt_id} (${dt.households_served} households)`;

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([dt.lon, dt.lat])
        .setPopup(
          new maplibregl.Popup({ offset: 10, className: 'dark-popup' })
            .setHTML(`
              <div style="background:#1e293b;color:#e2e8f0;padding:8px;border-radius:6px;font-size:12px;font-family:Inter,sans-serif;">
                <b>${dt.dt_id}</b><br/>
                Feeder: ${dt.feeder_id}<br/>
                Capacity: ${dt.capacity_kva} kVA<br/>
                Households: ${dt.households_served}
              </div>
            `)
        )
        .addTo(map);

      dtMarkersRef.current.push(marker);
    });
  }, [transformers, mapReady]);

  // Initial bounds fit (only once, not on every poll)
  useEffect(() => {
    if (!mapRef.current || !mapReady || initialBoundsSet.current) return;

    const map = mapRef.current;

    if (poles.length > 0 || transformers.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      poles.forEach(p => bounds.extend([p.lon, p.lat]));
      transformers.forEach(dt => bounds.extend([dt.lon, dt.lat]));

      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 50, maxZoom: 15, duration: 1000 });
        initialBoundsSet.current = true;
      }
    }
  }, [poles, transformers, mapReady]);

  // Fly to selected ticket (only when selection changes)
  useEffect(() => {
    if (!mapRef.current || !mapReady) return;

    const currentId = selectedTicket?.id || null;
    if (currentId === prevSelectedId.current) return;
    prevSelectedId.current = currentId;

    if (selectedTicket?.incident) {
      const inc = selectedTicket.incident;
      if (inc.centroid_lat && inc.centroid_lon) {
        mapRef.current.flyTo({
          center: [inc.centroid_lon, inc.centroid_lat],
          zoom: 15,
          duration: 1000,
        });
      }
    }
  }, [selectedTicket, mapReady]);

  return (
    <div ref={containerRef} className="w-full h-full" id="map-view">
      {/* Map legend */}
      <div className="absolute bottom-4 left-4 z-10 panel px-3 py-2 text-[10px] space-y-1">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-grid-live" />
          <span className="text-gray-400">Live</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-grid-dark" />
          <span className="text-gray-400">Dark</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-grid-suspect" />
          <span className="text-gray-400">Suspect</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-grid-unknown border border-dashed border-gray-500" />
          <span className="text-gray-400">No Device</span>
        </div>
        <div className="flex items-center gap-2 pt-1 border-t border-surface-500/30">
          <div className="w-3 h-3 rounded-sm bg-accent-primary border border-blue-300" />
          <span className="text-gray-400">Transformer</span>
        </div>
      </div>
    </div>
  );
}
