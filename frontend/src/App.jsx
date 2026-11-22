import SimulationBar from './SimulationBar.jsx';
import LiveTracking from './LiveTracking.jsx';
import { formatClock, formatDelay, formatDuration, KpiCard, Sidebar, StatusChip, Topbar } from './Dashboard.jsx';
import Home from './Home.jsx';
import { useEffect, useMemo, useRef, useState } from 'react';
import MapPanel from './MapPanel.jsx';
import PageBanner from './PageBanner.jsx';
import { Route, Navigation, MapPin, Clock3, CloudSun, Truck, Check, Info, X, LoaderCircle, CalendarDays, ShieldCheck, Flag } from 'lucide-react';
import { advanceSimulation, buildTrack } from './simulation.js';

const number = (value, digits = 1) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(value);
function arrivalMinutes(iso) {
  const [hours, minutes] = iso.slice(11, 16).split(':').map(Number);
  return hours * 60 + minutes;
}
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

const routes = { home: '', plan: '#/planifier', simulation: '#/simulation', tracking: '#/suivi' };

function readView(hash) {
  const path = hash.split('?')[0];
  if (path === routes.plan) return 'plan';
  if (path === routes.simulation) return 'simulation';
  if (path === routes.tracking) return 'tracking';
  return 'home';
}

export default function App() {
  const [config, setConfig] = useState(null), [configError, setConfigError] = useState('');
  const [form, setForm] = useState({ departure: 'Casablanca', arrival: 'Rabat', departure_time: '', urban: false });
  const [hash, setHash] = useState(() => window.location.hash), [about, setAbout] = useState(false);
  const [customer, setCustomer] = useState(false);
  const [trackingVersion, setTrackingVersion] = useState(0);
  async function signOut() {
    try {
      const response = await fetch('/api/auth/session', { method: 'DELETE' });
      if (!response.ok) throw new Error();
      setCustomer(false);
      setTrackingVersion(version => version + 1);
    } catch {
      window.alert('Impossible de vous déconnecter. Réessayez.');
    }
  }
  const view = readView(hash);
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
  useEffect(() => {
    const syncView = () => { setHash(window.location.hash); setRunning(false); };
    window.addEventListener('hashchange', syncView);
    return () => window.removeEventListener('hashchange', syncView);
  }, []);

  const navigate = (page) => {
    window.location.hash = routes[page];
    setHash(routes[page]);
    setRunning(false);
    window.scrollTo(0, 0);
  };
  const goSimulation = () => navigate('simulation');

  return <div className="app-shell">
    <Sidebar view={view} navigate={navigate} onAbout={() => setAbout(true)} />
    <div className="workspace">
      <Topbar onSignOut={customer ? signOut : undefined} view={view} navigate={navigate} onAbout={() => setAbout(true)} notification={error || result?.alert.label} />

      {view === 'home' ? <Home navigate={navigate} /> :
        view === 'tracking' ? <LiveTracking tripConfig={config} key={trackingVersion} hash={hash} onSessionChange={setCustomer} /> : <main>
        <PageBanner simulation={view === 'simulation'} />

        {configError && <div className="notice error-notice" role="alert"><Info size={19} /><span>{configError}</span><button onClick={() => loadConfig()}>Réessayer</button></div>}

        <section className="dashboard-kpis" aria-label="Estimations du trajet">
          <div className="metrics-grid">
              <KpiCard loading={loading} icon={Clock3} label="Temps de référence" value={result?.duree_theorique_min} format={formatDuration} />
              <KpiCard loading={loading} icon={Navigation} label="Durée estimée" value={result?.duree_estimee_min} format={formatDuration} className="featured-metric" />
              <KpiCard loading={loading} icon={Route} label="Écart estimé" value={result?.retard_min} format={formatDelay} suffix="min" />
              <KpiCard loading={loading} icon={Flag} label="Arrivée estimée" value={result ? arrivalMinutes(result.estimated_arrival_time) : null} format={formatClock} />
            </div>
        </section>

        <div className={view === "simulation" ? "content-grid tracking-layout" : "content-grid"}>
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
              {result ? <><div className="demo-banner"><Info size={17} /><span>Aucune position GPS réelle n’est utilisée.</span></div><div className="delivery-timeline"><div><span className="timeline-circle"><Check size={14} /></span><strong>Itinéraire préparé</strong><small>{result.route.departure.label.split(',')[0]}</small></div><div><span className={`timeline-circle ${elapsed > 0 ? 'filled' : ''}`}><Truck size={14} /></span><strong>{complete ? 'Parcours terminé' : running ? 'Livraison en cours' : elapsed > 0 ? 'Simulation en pause' : 'Prêt au départ'}</strong><small>{number(fraction * 100, 0)} % du parcours</small></div><div><span className={`timeline-circle ${complete ? 'filled' : ''}`}><Flag size={14} /></span><strong>Destination</strong><small>{result.route.arrival.label.split(',')[0]}</small></div></div><div className="simulation-explainer"><h3>Comment ça fonctionne ?</h3><p>Le marqueur suit la route calculée. Sa vitesse est proportionnelle à la durée estimée, accélérée pour la démonstration.</p></div></> : <div className="empty-simulation"><Truck size={36} /><h3>Votre parcours commence ici.</h3><p>Estimez d’abord un trajet pour lancer sa simulation.</p><button className="primary-button" onClick={() => navigate('plan')}>Planifier un trajet</button></div>}
              {result && <button className="secondary-button w-full" onClick={() => navigate('plan')}>Modifier le trajet</button>}
            </>}
          </section>

          <div className="journey-panel">
            <section className="map-card card"><div className="map-heading"><div><h2>Aperçu de l’itinéraire</h2><span>{result ? `${number(result.distance_km)} km de route` : 'Votre prochain trajet, en un coup d’œil'}</span></div><span className="simulation-badge"><Truck size={14} />SIMULATION</span></div>
              <MapPanel result={result} track={track} fraction={fraction} running={running} mapRef={mapRef} />
            </section>
            <section className="delivery-details card" aria-labelledby="delivery-details-title"><h2 id="delivery-details-title">Détails du trajet</h2>
              {!result && <p className="details-empty">Lancez une estimation pour afficher la météo et le statut du trajet.</p>}
              {result && <div className="delivery-conditions">
                <StatusChip alert={result.alert} delay={result.retard_min} />
                <span className="weather-chip"><CloudSun size={18} />{result.weather.meteo}<i />{number(result.weather.temperature_c)} °C</span>
              </div>}
            </section>

            <SimulationBar
              ready={Boolean(result)}
              loading={loading}
              running={running}
              fraction={fraction}
              speed={speed}
              onToggle={() => {
                if (complete) setElapsed(0);
                setRunning(complete || !running);
              }}
              onReset={reset}
              onSpeedChange={setSpeed}
              onOpenDelivery={view === 'plan' && result ? goSimulation : undefined}
              remainingDistance={result ? number(result.distance_km * (1 - fraction)) + ' km' : null}
              remainingDuration={result ? formatDuration(result.duree_estimee_min * (1 - fraction)) : null}
            />
          </div>
        </div>

        <footer className="page-footer"><span><Info size={15} /> Estimation expérimentale · modèle entraîné sur des données simulées.</span><div><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a><span>·</span><a href="https://project-osrm.org/" target="_blank" rel="noreferrer">OSRM</a><span>·</span><a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a></div></footer>
      </main>}
    </div>

    <dialog ref={dialogRef} onCancel={() => setAbout(false)} onClose={() => setAbout(false)} className="about-dialog" aria-labelledby="about-title"><button className="dialog-close icon-button" onClick={() => setAbout(false)} aria-label="Fermer"><X size={21} /></button><span className="section-icon"><Route size={23} /></span><h2 id="about-title">Mieux anticiper, en toute clarté.</h2><p>Wasel associe un itinéraire OSRM, les prévisions Open-Meteo et un modèle de durée entraîné sur des trajets synthétiques.</p><div className="about-details"><h3>Ce que vous voyez</h3><p>Une estimation de conduite et une animation de démonstration. Ce prototype ne mesure pas le trafic en direct et ne suit aucun téléphone.</p><h3>Ce qui n’est pas inclus</h3><p>Préparation d’une commande, attente du livreur et remise au client. Les conditions météo non représentées dans l’entraînement ne donnent pas lieu à une prédiction.</p><h3>Les seuils d’alerte</h3><p>Moins de 5 minutes : fluide. De 5 à 15 minutes : ralentissements. Au-delà : alerte retard. Un écart négatif signifie une estimation inférieure à la référence.</p></div><button className="primary-button w-full" onClick={() => setAbout(false)}>J’ai compris</button></dialog>
  </div>;
}
