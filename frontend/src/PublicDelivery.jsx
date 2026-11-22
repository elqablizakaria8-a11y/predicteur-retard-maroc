import { useEffect, useRef, useState } from 'react';
import { CircleMarker, MapContainer, TileLayer, useMap } from 'react-leaflet';
import { clockLabel, deliveryRequest, events } from './Deliveries.jsx';
import './tracking.css';

function Center({ position }) {
  const map = useMap();
  useEffect(() => { map.panTo([position.latitude, position.longitude]); }, [map, position.latitude, position.longitude]);
  return null;
}

function DriverPage({ token, route }) {
  const [active, setActive] = useState(false), [done, setDone] = useState(Boolean(route.events.delivered));
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const cancel = useRef(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    cancel.current = controller;
    let reading = false;
    function locate() {
      if (controller.signal.aborted || reading) return;
      reading = true;
      navigator.geolocation.getCurrentPosition(async ({ coords, timestamp }) => {
        if (controller.signal.aborted) return;
        try {
          await deliveryRequest('/position', { method: 'POST', token, signal: controller.signal,
            data: { latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy, captured: timestamp / 1000 } });
          setMessage('Position transmise à ' + clockLabel(Date.now() / 1000) + '.');
        } catch (error) {
          if (!controller.signal.aborted) {
            setMessage(error.message);
            if ([404, 409, 410].includes(error.status)) setActive(false);
          }
        } finally { reading = false; }
      }, error => {
        if (controller.signal.aborted) return;
        reading = false;
        setMessage(error.code === 1 ? 'Autorisez la localisation dans votre navigateur pour démarrer.' : 'Signal GPS indisponible. Nouvelle tentative en cours.');
        if (error.code === 1) setActive(false);
      }, { enableHighAccuracy: true, maximumAge: 0, timeout: 12000 });
    }
    locate();
    const timer = setInterval(locate, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [active, token]);

  async function action(name) {
    setMessage('');
    if (name === 'start' && (!window.isSecureContext || !navigator.geolocation)) {
      setMessage('Ouvrez le lien en HTTPS dans un navigateur compatible avec la localisation.'); return;
    }
    if (name !== 'start') { cancel.current?.abort(); setActive(false); }
    setBusy(true);
    try {
      await deliveryRequest('/driver/' + name, { method: 'POST', token });
      if (name === 'start') setActive(true);
      if (name === 'pause') setMessage('Partage arrêté.');
      if (name === 'deliver') setDone(true);
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <section className="card tracking-card"><h2>{done ? 'Livraison terminée' : active ? 'Partage en cours' : 'Espace livreur'}</h2>
    {!done && <><p>Votre position est partagée uniquement pendant cette livraison.</p>
      <button className="primary-button" disabled={busy} onClick={() => action(active ? 'pause' : 'start')}>
        {active ? 'Arrêter le partage' : 'Démarrer la livraison'}</button>
      <button disabled={busy} onClick={() => action('deliver')}>J’ai livré</button></>}
    {message && <p role="status">{message}</p>}
  </section>;
}

export default function PublicDelivery({ role, token }) {
  const driver = role === 'livreur';
  const [route, setRoute] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    const ctrl = new AbortController();
    let timer;
    async function load() {
      try {
        const data = await deliveryRequest(driver ? '/driver/connect' : '/viewer', {
          method: driver ? 'POST' : 'GET', token, signal: ctrl.signal });
        if (ctrl.signal.aborted) return;
        setRoute(data); setError('');
        if (driver || data.events.delivered) return;
      } catch (failure) {
        if (ctrl.signal.aborted) return;
        setError(failure.status === 404 ? 'Ce lien est indisponible ou a expiré.' : 'Connexion au suivi interrompue. Nouvelle tentative en cours.');
        if (failure.status === 404) { setRoute(null); return; }
      }
      timer = setTimeout(load, 5000);
    }
    load();
    return () => { ctrl.abort(); clearTimeout(timer); };
  }, [driver, token]);
  const point = route?.position;
  const diff = route ? Math.round((route.eta - route.planned) / 60) : 0;
  return <main className="public-delivery delivery-workspace">
    <header className="tracking-hero tracking-hero-compact"><div className="tracking-hero-copy">
      <h1>{driver ? 'Votre livraison' : 'Suivi de livraison'}</h1>{route && <p>{route.origin} → {route.destination}</p>}</div></header>
    {error && <p role="alert">{error}</p>}
    {!route && !error && <p role="status">Connexion à la livraison…</p>}
    {route && (driver ? <DriverPage token={token} route={route} /> : <>
      <section className="card tracking-card"><h2>{route.events.delivered ? 'Livrée' : route.paused ? 'Partage en pause' : point ? 'Position du livreur' : 'En attente de la position du livreur'}</h2>
        {point && <><p>{route.stale || Date.now()/1000-point.captured >= 30 ? 'Position ancienne' : 'Position récente'} · Dernière réception {clockLabel(route.updated)} · Précision ±{Math.round(point.accuracy)} m</p>
          <MapContainer center={[point.latitude, point.longitude]} zoom={14} className="tracking-map" scrollWheelZoom={false}>
            <TileLayer url={import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
            <Center position={point} /><CircleMarker center={[point.latitude, point.longitude]} radius={9} pathOptions={{color:'var(--surface)',fillColor:'var(--route)',fillOpacity:1}} />
          </MapContainer></>}
      </section>
      <div className="delivery-columns"><section className="card tracking-card"><h2>{route.events.delivered ? 'Arrivée enregistrée' : route.eta_at ? 'Arrivée estimée' : 'Arrivée prévue au départ'}</h2>
        <strong>{clockLabel(route.eta)}</strong><p>{diff > 0 ? diff + ' min de retard' : diff < 0 ? -diff + ' min d’avance' : 'Dans les temps'} · Prévision initiale {clockLabel(route.planned)}</p>
        {route.eta_at && <small>Dernier calcul · {clockLabel(route.eta_at)}</small>}</section>
      <section className="card tracking-card"><h2>Étapes de livraison</h2><ol className="delivery-events">
        {Object.entries(events).map(([id, name]) => <li key={id}><strong>{name}</strong><span>{route.events[id] ? clockLabel(route.events[id]) : 'En attente'}</span></li>)}
      </ol></section></div>
    </>)}
  </main>;
}
