import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Route, Navigation, MapPin, Clock3, CloudSun, Play, Pause, RotateCcw, Truck, Check, Info, LocateFixed, X, LoaderCircle, CalendarDays, ShieldCheck, ChevronDown, Flag, CircleHelp } from 'lucide-react';
import { advanceSimulation, buildTrack, sampleTrack } from './simulation.js';

const number = (value, digits = 1) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(value);
const durationLabel = (value) => { const minutes = Math.max(0, Math.round(value)); return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}`; };
const clockLabel = (iso) => iso?.slice(11, 16) || '—';
const latLon = (point) => [point[1], point[0]];
const driverIcon = L.divIcon({ className: 'driver-marker', iconSize: [44, 44], iconAnchor: [22, 22], html: '<span><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h11v11H3zM14 10h4l3 4v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg></span>' });

async function request(path, body, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, 90000);
  try {
    const response = await fetch(`/api/${path}`, { method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined, signal: controller.signal });
    let data;
    try { data = await response.json(); } catch { throw new Error('Le serveur ne répond pas correctement. Réessayez dans un instant.'); }
    if (!response.ok) {
      const error = new Error(data.error?.message || 'Impossible de terminer cette demande.');
      error.details = data.error;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Le délai de réponse est dépassé. Vous pouvez réessayer.');
    if (error instanceof TypeError) throw new Error('Connexion au serveur impossible. Vérifiez que le backend est démarré.');
    throw error;
  } finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort); }
}

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

function JourneyMap({ result, track, fraction, running, mapRef }) {
  const [tileError, setTileError] = useState(false);
  const positions = useMemo(() => track?.coordinates.map(latLon), [track]);
  const sample = track ? sampleTrack(track, fraction) : null;
  return <div className="map-shell">
    <MapContainer center={[32.6, -7.25]} zoom={6} ref={mapRef} scrollWheelZoom={false} className="journey-map" aria-label="Carte de l’itinéraire et position simulée">
      <TileLayer url={import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' eventHandlers={{ tileerror: () => setTileError(true), load: () => setTileError(false) }} />
      {positions && <><FitRoute positions={positions} />
        <Polyline positions={positions} pathOptions={{ color: '#17836b', weight: 5, opacity: .85 }} />
        {fraction > 0 && <Polyline positions={sample.travelled.map(latLon)} pathOptions={{ color: '#123f35', weight: 6 }} />}
        <CircleMarker center={positions[0]} radius={7} pathOptions={{ color: 'white', weight: 3, fillColor: '#168269', fillOpacity: 1 }}><Popup>Départ : {result.route.departure.label}</Popup></CircleMarker>
        <CircleMarker center={positions.at(-1)} radius={7} pathOptions={{ color: 'white', weight: 3, fillColor: '#d18c34', fillOpacity: 1 }}><Popup>Arrivée : {result.route.arrival.label}</Popup></CircleMarker>
        <Marker position={latLon(sample.position)} icon={driverIcon} alt="Livreur simulé"><Popup>Position simulée · {number(fraction * 100, 0)} % du trajet</Popup></Marker>
      </>}
    </MapContainer>
    <div className="map-caption"><span className="map-caption-icon"><Route size={17} /></span><span>{result ? `${result.route.departure.label.split(',')[0]} · ${result.route.arrival.label.split(',')[0]}` : 'Maroc · choisissez votre itinéraire'}</span></div>
    {result && <button type="button" className="map-recenter" title="Recentrer l’itinéraire" aria-label="Recentrer l’itinéraire" onClick={() => mapRef.current?.fitBounds(positions, { padding: [55, 55] })}><LocateFixed size={19} /></button>}
    <div className="map-mode"><span className={running ? 'pulse-dot' : 'small-square'} />{running ? 'Simulation en cours' : 'Aucun suivi GPS réel'}</div>
    {tileError && <div className="tile-error" role="status">Fond de carte indisponible. L’itinéraire reste utilisable.</div>}
  </div>;
}

function Metric({ icon: Icon, label, value, suffix, className = '' }) {
  return <div className={`metric ${className}`}><div className="metric-label"><Icon size={16} />{label}</div><div className="metric-value">{value}<span>{suffix}</span></div></div>;
}

export default function App() {
  const [config, setConfig] = useState(null), [configError, setConfigError] = useState('');
  const [form, setForm] = useState({ departure: 'Casablanca', arrival: 'Rabat', departure_time: '', urban: false });
  const [view, setView] = useState('plan'), [about, setAbout] = useState(false);
  const [result, setResult] = useState(null), [lastForm, setLastForm] = useState(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [selection, setSelection] = useState(null);
  const [running, setRunning] = useState(false), [elapsed, setElapsed] = useState(0), [speed, setSpeed] = useState(120);
  const mapRef = useRef(null), dialogRef = useRef(null), mounted = useRef(true);
  const track = useMemo(() => result ? buildTrack(result.route.geometry.coordinates) : null, [result]);
  const duration = result ? result.duree_estimee_min * 60 : 1;
  const fraction = Math.min(1, elapsed / duration), complete = !!result && fraction >= 1;
  const dirty = result && JSON.stringify(form) !== JSON.stringify(lastForm);

  async function loadConfig(signal) {
    setConfigError('');
    try {
      const data = await request('config', null, signal);
      if (signal?.aborted || !mounted.current) return;
      setConfig(data);
      setForm(old => ({ ...old, departure_time: old.departure_time || data.default_departure }));
    } catch (e) { if (!signal?.aborted && mounted.current) setConfigError(e.message); }
  }
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    loadConfig(controller.signal);
    return () => { mounted.current = false; controller.abort(); };
  }, []);
  useEffect(() => {
    if (!running || !result) return;
    let previous = performance.now(), frame;
    const tick = now => {
      const seconds = Math.max(0, (now - previous) / 1000); previous = now;
      setElapsed(old => advanceSimulation(old, seconds, speed, duration));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, speed, duration, result]);
  useEffect(() => { if (complete) setRunning(false); }, [complete]);
  useEffect(() => {
    if (about && !dialogRef.current?.open) dialogRef.current?.showModal();
    if (!about && dialogRef.current?.open) dialogRef.current?.close();
  }, [about]);

  const update = (key, value) => { setForm(old => ({ ...old, [key]: value })); setSelection(null); setError(''); };
  async function plan(snapshot = { ...form }, resolved = {}) {
    setLoading(true); setError(''); setSelection(null); setRunning(false);
    try {
      for (const field of ['departure', 'arrival']) {
        if (!resolved[field]) {
          try { resolved[field] = await request('geocode', { query: snapshot[field] }); }
          catch (e) {
            if (e.details?.code === 'ambiguous_place') { setSelection({ field, candidates: e.details.candidates, snapshot, resolved }); return; }
            throw e;
          }
        }
      }
      const data = await request('predict', { departure: resolved.departure, arrival: resolved.arrival, departure_time: snapshot.departure_time, urban: snapshot.urban });
      buildTrack(data.route.geometry.coordinates);
      if (!Number.isFinite(data.duree_estimee_min) || data.duree_estimee_min <= 0) throw new Error('La durée reçue est invalide.');
      setResult(data); setLastForm(snapshot); setElapsed(0);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }
  const reset = () => { setRunning(false); setElapsed(0); };
  const goSimulation = () => { setView('simulation'); setRunning(false); };

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); setView('plan'); }} aria-label="Wasel, accueil"><img src="/favicon.svg" alt="" /><span>wasel<span className="brand-period">.</span><small>DELIVERY INTELLIGENCE</small></span></a>
      <div className="nav-heading">ESPACE DE TRAVAIL</div>
      <nav aria-label="Navigation principale">
        <button className={view === 'plan' ? 'nav-item active' : 'nav-item'} onClick={() => setView('plan')}><Route size={19} /><span>Planifier un trajet</span></button>
        <button className={view === 'simulation' ? 'nav-item active' : 'nav-item'} onClick={goSimulation}><Truck size={19} /><span>Simulation</span><span className="nav-tag">DÉMO</span></button>
      </nav>
      <div className="sidebar-bottom"><div className="country-mark"><span>MA</span><div>Conçu pour le Maroc<small>Un trajet à la fois.</small></div></div><button className="sidebar-help" onClick={() => setAbout(true)}><CircleHelp size={17} /><span>À propos du projet</span></button></div>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumb">Espace de travail<span>/</span><strong>{view === 'plan' ? 'Planification' : 'Simulation'}</strong></div><div className="topbar-right"><span className="prototype-badge">PROTOTYPE ÉDUCATIF</span><button className="icon-button" aria-label="Comprendre les estimations" onClick={() => setAbout(true)}><Info size={20} /></button><span className="avatar" aria-label="Espace Maroc">MA</span></div></header>

      <main>
        <div className="page-heading"><div><div className="eyebrow"><span /> ANTICIPER. PLANIFIER. LIVRER.</div><h1>{view === 'plan' ? 'Vos trajets, mieux anticipés.' : 'Votre livraison prend la route.'}</h1><p>{view === 'plan' ? 'Estimez votre temps de route et partez avec une longueur d’avance.' : 'Explorez votre itinéraire avec une simulation de déplacement.'}</p></div><div className="region-chip"><MapPin size={15} />Maroc</div></div>

        {configError && <div className="notice error-notice" role="alert"><Info size={19} /><span>{configError}</span><button onClick={() => loadConfig()}>Réessayer</button></div>}

        <div className="content-grid">
          <section className="planner card">
            {view === 'plan' ? <>
              <div className="section-heading"><span className="section-icon"><Route size={19} /></span><div><h2>Votre itinéraire</h2><p>Les détails de votre prochain trajet</p></div></div>
              <form onSubmit={event => { event.preventDefault(); plan(); }}>
                <fieldset disabled={loading || !config}>
                  <div className="route-inputs"><label htmlFor="departure">Point de départ</label><div className="location-input"><span className="waypoint-dot origin" /><input id="departure" list="cities" value={form.departure} onChange={e => update('departure', e.target.value)} placeholder="Ville ou adresse de départ" required maxLength={300} autoComplete="off" /></div>
                    <div className="swap-line"><i /><button type="button" onClick={() => { setForm(old => ({ ...old, departure: old.arrival, arrival: old.departure })); setSelection(null); setError(''); }}>Permuter</button></div>
                    <label htmlFor="arrival">Destination</label><div className="location-input"><span className="waypoint-dot destination" /><input id="arrival" list="cities" value={form.arrival} onChange={e => update('arrival', e.target.value)} placeholder="Ville ou adresse d’arrivée" required maxLength={300} autoComplete="off" /></div>
                  </div>
                  <datalist id="cities">{config?.cities.map(city => <option key={city} value={city} />)}</datalist>
                  <label className="date-label" htmlFor="departure-time">Date et heure de départ <span>Heure Maroc</span></label><div className="date-input"><CalendarDays size={17} /><input id="departure-time" type="datetime-local" required value={form.departure_time} min={config?.min_departure} max={config?.max_departure} onChange={e => update('departure_time', e.target.value)} /></div>
                  <div className="field-label">Type de trajet</div><div className="trip-types">{[[false, 'Interurbain', 'Entre deux villes'], [true, 'Urbain', 'Dans la même ville']].map(([value, label, description]) => <label key={label} className={form.urban === value ? 'trip-type selected' : 'trip-type'}><input type="radio" name="trip-type" checked={form.urban === value} onChange={() => update('urban', value)} /><span><strong>{label}</strong><small>{description}</small></span>{form.urban === value && <Check size={14} />}</label>)}</div>
                  <button type="submit" className="primary-button calculate-button">{loading ? <LoaderCircle className="spin" size={18} /> : <Navigation size={18} />}{loading ? 'Calcul de votre trajet…' : 'Estimer mon trajet'}</button>
                </fieldset>
              </form>
              <div className="form-note"><ShieldCheck size={16} /><span>Sans clé API. Prévisions jusqu’à 7 jours.</span></div>
              {dirty && <p className="dirty-note">Recalculez pour appliquer vos modifications.</p>}
              {error && <div className="notice inline-error" role="alert"><Info size={18} /><span>{error}</span></div>}
              {selection && <div className="place-selection"><h3>Précisez {selection.field === 'departure' ? 'le départ' : 'la destination'}</h3><p>Plusieurs lieux correspondent à votre recherche.</p>{selection.candidates.map((candidate, i) => <button key={i} disabled={loading} onClick={() => plan(selection.snapshot, { ...selection.resolved, [selection.field]: candidate })}><MapPin size={16} /><span>{candidate.label}</span></button>)}</div>}
            </> : <>
              <div className="section-heading"><span className="section-icon"><Truck size={19} /></span><div><h2>Livraison de démonstration</h2><p>Un parcours entièrement simulé</p></div></div>
              {result ? <><div className="demo-banner"><Info size={17} /><span>Aucune position GPS réelle n’est utilisée.</span></div><div className="delivery-timeline"><div><span className="timeline-circle"><Check size={14} /></span><strong>Itinéraire préparé</strong><small>{result.route.departure.label.split(',')[0]}</small></div><div><span className={`timeline-circle ${elapsed > 0 ? 'filled' : ''}`}><Truck size={14} /></span><strong>{complete ? 'Parcours terminé' : running ? 'Livraison en cours' : elapsed > 0 ? 'Simulation en pause' : 'Prêt au départ'}</strong><small>{number(fraction * 100, 0)} % du parcours</small></div><div><span className={`timeline-circle ${complete ? 'filled' : ''}`}><Flag size={14} /></span><strong>Destination</strong><small>{result.route.arrival.label.split(',')[0]}</small></div></div><div className="simulation-explainer"><h3>Comment ça fonctionne ?</h3><p>Le marqueur suit la route calculée. Sa vitesse est proportionnelle à la durée estimée, accélérée pour la démonstration.</p></div></> : <div className="empty-simulation"><Truck size={36} /><h3>Votre parcours commence ici.</h3><p>Estimez d’abord un trajet pour lancer sa simulation.</p><button className="primary-button" onClick={() => setView('plan')}>Planifier un trajet</button></div>}
              {result && <button className="secondary-button w-full" onClick={() => setView('plan')}>Modifier le trajet</button>}
            </>}
          </section>

          <div className="journey-panel">
            <div className="metrics-grid">
              <Metric icon={Clock3} label="Temps de référence" value={result ? durationLabel(result.duree_theorique_min) : '—'} />
              <Metric icon={Navigation} label="Durée estimée" value={result ? durationLabel(result.duree_estimee_min) : '—'} className="featured-metric" />
              <Metric icon={Route} label="Écart estimé" value={result ? `${result.retard_min > 0 ? '+' : ''}${number(result.retard_min)}` : '—'} suffix={result ? 'min' : ''} />
              <Metric icon={Flag} label="Arrivée estimée" value={result ? clockLabel(result.estimated_arrival_time) : '—'} />
            </div>
            <section className="map-card card"><div className="map-heading"><div><h2>Aperçu de l’itinéraire</h2><span>{result ? `${number(result.distance_km)} km de route` : 'Votre prochain trajet, en un coup d’œil'}</span></div><span className="simulation-badge"><Truck size={14} />SIMULATION</span></div>
              <JourneyMap result={result} track={track} fraction={fraction} running={running} mapRef={mapRef} />
              <div className="route-footer">{result ? <><span className={`traffic-status ${result.alert.color}`}><span />{result.alert.label}<small>estimation</small></span><span className="weather-chip"><CloudSun size={18} />{result.weather.meteo}<i />{number(result.weather.temperature_c)} °C</span></> : <><span><MapPin size={16} />L’itinéraire apparaîtra après votre estimation.</span><span className="muted">Voiture</span></>}</div>
            </section>
            <section className="playback card"><div className="playback-title"><span className="section-icon"><Play size={17} /></span><div><h2>Explorez le trajet</h2><p>{complete ? 'Simulation terminée. Vous pouvez la rejouer.' : 'Visualisez le déplacement d’un livreur simulé.'}</p></div>{view === 'plan' && result && <button className="text-button" onClick={goSimulation}>Vue livraison</button>}</div>
              <div className="playback-controls"><button className="primary-button play-button" disabled={!result || loading || complete} onClick={() => setRunning(value => !value)}>{complete ? <Check size={17} /> : running ? <Pause size={17} /> : <Play size={17} />}{complete ? 'Terminé' : running ? 'Pause' : elapsed > 0 ? 'Reprendre' : 'Démarrer'}</button><button className="reset-button" disabled={!result || loading} onClick={reset} aria-label="Réinitialiser la simulation" title="Réinitialiser"><RotateCcw size={18} /></button><div className="playback-progress"><div><span>{complete ? 'Terminé' : running ? 'En mouvement' : elapsed > 0 ? 'En pause' : 'Prêt au départ'}</span><strong>{number(fraction * 100, 0)} %</strong></div><progress value={fraction} max={1} aria-label="Progression du parcours simulé" /></div><label className="speed-control"><span>Vitesse</span><select value={speed} onChange={e => setSpeed(Number(e.target.value))} aria-label="Vitesse de simulation"><option value={1}>×1</option><option value={30}>×30</option><option value={120}>×120</option><option value={600}>×600</option></select><ChevronDown size={13} /></label></div>
              {result && <div className="remaining"><span><strong>{number(result.distance_km * (1 - fraction))} km</strong> restants simulés</span><span><strong>{durationLabel(result.duree_estimee_min * (1 - fraction))}</strong> restantes simulées</span></div>}
            </section>
          </div>
        </div>

        <footer className="page-footer"><span><Info size={15} /> Estimation expérimentale · modèle entraîné sur des données simulées.</span><div><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a><span>·</span><a href="https://project-osrm.org/" target="_blank" rel="noreferrer">OSRM</a><span>·</span><a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a></div></footer>
      </main>
    </div>

    <dialog ref={dialogRef} onCancel={() => setAbout(false)} onClose={() => setAbout(false)} className="about-dialog" aria-labelledby="about-title"><button className="dialog-close icon-button" onClick={() => setAbout(false)} aria-label="Fermer"><X size={21} /></button><span className="section-icon"><Route size={23} /></span><h2 id="about-title">Mieux anticiper, en toute clarté.</h2><p>Wasel associe un itinéraire OSRM, les prévisions Open-Meteo et un modèle de durée entraîné sur des trajets synthétiques.</p><div className="about-details"><h3>Ce que vous voyez</h3><p>Une estimation de conduite et une animation de démonstration. Ce prototype ne mesure pas le trafic en direct et ne suit aucun téléphone.</p><h3>Ce qui n’est pas inclus</h3><p>Préparation d’une commande, attente du livreur et remise au client. Les conditions météo non représentées dans l’entraînement ne donnent pas lieu à une prédiction.</p><h3>Les seuils d’alerte</h3><p>Moins de 5 minutes : fluide. De 5 à 15 minutes : ralentissements. Au-delà : alerte retard. Un écart négatif signifie une estimation inférieure à la référence.</p></div><button className="primary-button w-full" onClick={() => setAbout(false)}>J’ai compris</button></dialog>
  </div>;
}
