import { Bell, CircleHelp, House, Info, Route, Search, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { WaselIcon, WaselLogoWhite } from './Logo.jsx';

const pages = [
  { id: 'home', label: 'Accueil', icon: House },
  { id: 'plan', label: 'Planifier un trajet', icon: Route },
  { id: 'simulation', label: 'Simulation', icon: Truck },
];

export function Sidebar({ view, navigate, onAbout }) {
  return (
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate('home')} aria-label="Wasel, accueil">
        <WaselLogoWhite />
        <span className="compact-brand"><WaselIcon /></span>
      </button>
      <div className="nav-heading">ESPACE DE TRAVAIL</div>
      <nav aria-label="Navigation principale">
        {pages.map(({ id, label, icon: Icon }) => (
          <button key={id} className={`nav-item${view === id ? ' active' : ''}`}
            aria-label={label} aria-current={view === id ? 'page' : undefined} onClick={() => navigate(id)}>
            <Icon size={19} aria-hidden="true" /><span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <button className="sidebar-help" onClick={onAbout}><CircleHelp size={17} /> À propos du projet</button>
      </div>
    </aside>
  );
}

export function Topbar({ view, navigate, onAbout, notification }) {
  const [query, setQuery] = useState('');
  const matches = pages.filter(({ label }) => label.toLocaleLowerCase('fr').includes(query.trim().toLocaleLowerCase('fr')));
  return (
    <header className="topbar">
      <div className="breadcrumb">Espace de travail<span aria-hidden="true">/</span><strong>{pages.find(({ id }) => id === view)?.label}</strong></div>
      <div className="topbar-right">
        <details className="topbar-popover">
          <summary aria-label="Rechercher une page"><Search size={18} /><span>Rechercher une page</span></summary>
          <div className="popover-body">
            <input className="page-search" aria-label="Nom de la page" placeholder="Nom de la page" value={query} onChange={event => setQuery(event.target.value)} />
            {matches.length === 0 && <p>Aucune page trouvée.</p>}
            {matches.map(({ id, label }) => (
              <button key={id} onClick={event => {
                event.currentTarget.closest('details').open = false;
                setQuery('');
                navigate(id);
              }}>{label}</button>
            ))}
          </div>
        </details>
        <details className="topbar-popover">
          <summary aria-label="Notifications"><Bell size={19} /></summary>
          <div className="popover-body"><strong>Notifications</strong><p>{notification || 'Aucune alerte pour le moment.'}</p></div>
        </details>
        <button className="icon-button" aria-label="Comprendre les estimations" onClick={onAbout}><Info size={20} /></button>
        <span className="avatar" aria-label="Espace Maroc">MA</span>
      </div>
    </header>
  );
}

const formatNumber = (value) => String(Math.round(value));
const delayNumber = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1, signDisplay: 'exceptZero' });

export function formatDelay(value) {
  const minutes = Math.round(Math.abs(value) * 10) / 10;
  return delayNumber.format(value < 0 ? -minutes : minutes);
}

export function formatDuration(value) {
  const minutes = Math.max(0, Math.round(value));
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}`;
}

export function formatClock(value) {
  const minutes = Math.round(value);
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

function CountUp({ value, format, suffix }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame;
    const started = performance.now();

    function tick(now) {
      const progress = Math.min(1, (now - started) / 650);
      setDisplay(progress === 1 ? value : value * (1 - (1 - progress) ** 3));
      if (progress < 1) frame = requestAnimationFrame(tick);
    }

    function finish() {
      cancelAnimationFrame(frame);
      setDisplay(value);
    }

    if (motion.matches) finish();
    else frame = requestAnimationFrame(tick);
    motion.addEventListener('change', finish);
    return () => {
      cancelAnimationFrame(frame);
      motion.removeEventListener('change', finish);
    };
  }, [value]);

  return <div className="metric-value">
    <div aria-hidden="true">{format(display)}{suffix && <span className="metric-unit">{suffix}</span>}</div>
    <span className="sr-only">{format(value)} {suffix}</span>
  </div>;
}

export function KpiCard({ icon: Icon, label, value, format = formatNumber, suffix, loading, className = '' }) {
  return (
    <div className={`metric ${className}`} aria-busy={loading}>
      <div className="metric-label"><span className="kpi-icon"><Icon size={17} /></span>{label}</div>
      {loading ? <div className="kpi-skeleton"><span className="sr-only">Calcul en cours</span></div> :
        value == null ? <p className="kpi-empty">À calculer</p> :
          <CountUp key={value} value={value} format={format} suffix={suffix} />}
    </div>
  );
}

export function StatusChip({ alert, delay }) {
  const text = delay < 0 ? 'En avance' : {
    green: 'Dans les temps', orange: 'Ralentissements', red: 'Retard probable',
  }[alert.color];
  return <span className={`traffic-status status-chip ${alert.color}`}><span aria-hidden="true" />{text || alert.label}</span>;
}
