import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { LocateFixed, Route } from 'lucide-react';
import { sampleTrack } from './simulation.js';

const number = value => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(value);
const latLon = (point) => [point[1], point[0]];
const driverIcon = L.divIcon({ className: 'driver-marker', iconSize: [44, 44], iconAnchor: [22, 22], html: '<span><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h11v11H3zM14 10h4l3 4v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg></span>' });

function FitRoute({ positions }) {
  const map = useMap();
  useEffect(() => {
    if (!positions?.length) return;
    let frame;
    const fit = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => { map.invalidateSize(); map.fitBounds(positions, { padding: [40, 40], maxZoom: 15 }); }); };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(map.getContainer());
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [positions, map]);
  return null;
}

export default function MapPanel({ result, track, fraction, running, mapRef }) {
  const [tileError, setTileError] = useState(false);
  const positions = useMemo(() => track?.coordinates.map(latLon), [track]);
  const sample = track ? sampleTrack(track, fraction) : null;
  return <div className="map-shell">
    <MapContainer center={[32.6, -7.25]} zoom={6} ref={mapRef} scrollWheelZoom={false} className="journey-map" aria-label="Carte de l’itinéraire et position simulée">
      <TileLayer url={import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' eventHandlers={{ tileerror: () => setTileError(true), load: () => setTileError(false) }} />
      {positions && <><FitRoute positions={positions} />
        <Polyline positions={positions} pathOptions={{ color: 'var(--route)', weight: 5, opacity: .85 }} />
        {fraction > 0 && <Polyline positions={sample.travelled.map(latLon)} pathOptions={{ color: 'var(--sidebar)', weight: 6 }} />}
        <CircleMarker center={positions[0]} radius={7} pathOptions={{ color: 'var(--surface)', weight: 3, fillColor: 'var(--brand)', fillOpacity: 1 }}><Popup>Départ : {result.route.departure.label}</Popup></CircleMarker>
        <CircleMarker center={positions.at(-1)} radius={7} pathOptions={{ color: 'var(--surface)', weight: 3, fillColor: 'var(--warning)', fillOpacity: 1 }}><Popup>Arrivée : {result.route.arrival.label}</Popup></CircleMarker>
        <Marker position={latLon(sample.position)} icon={driverIcon} alt="Livreur simulé"><Popup>Position simulée · {number(fraction * 100)} % du trajet</Popup></Marker>
      </>}
    </MapContainer>
    <div className="map-caption"><span className="map-caption-icon"><Route size={17} /></span><span>{result ? `${result.route.departure.label.split(',')[0]} · ${result.route.arrival.label.split(',')[0]}` : 'Maroc · choisissez votre itinéraire'}</span></div>
    {result && <button type="button" className="map-recenter" title="Recentrer l’itinéraire" aria-label="Recentrer l’itinéraire" onClick={() => mapRef.current?.fitBounds(positions, { padding: [55, 55] })}><LocateFixed size={19} /></button>}
    <div className="map-mode"><span className={running ? 'pulse-dot' : 'small-square'} />{running ? 'Simulation en cours' : 'Aucun suivi GPS réel'}</div>
    {tileError && <div className="tile-error" role="status">Fond de carte indisponible. L’itinéraire reste utilisable.</div>}
  </div>;
}

