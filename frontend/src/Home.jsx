import { CalendarDays, Clock3, CloudSun, Flag, MapPin, Navigation, Play, Route, Truck } from 'lucide-react';
import { formatClock, formatDelay, formatDuration, KpiCard } from './Dashboard.jsx';
import { WaselLogo } from './Logo.jsx';
import aerialInterchange from './images/aerial-interchange.jpg';
import cityMap from './images/city-map.jpg';
import eveningTraffic from './images/evening-traffic.jpg';
import urbanHighway from './images/urban-highway.jpg';
import './home.css';

const steps = [
  [MapPin, 'Choisissez votre trajet', 'Indiquez votre départ et votre destination au Maroc.', 'Casablanca → Rabat', cityMap, 'Carte stylisée d’un réseau routier urbain'],
  [CalendarDays, 'Fixez le départ', 'Sélectionnez la date et l’heure locale du trajet.', 'Départ à 15 h 00', eveningTraffic, 'Circulation dense à la tombée de la nuit'],
  [Clock3, 'Lisez votre estimation', 'Comparez le temps de référence avec la durée prévue.', '1 h 10 estimée', aerialInterchange, 'Vue aérienne d’un échangeur autoroutier'],
  [Truck, 'Suivez la simulation', 'Démarrez, mettez en pause ou accélérez le parcours.', 'Simulation · 48 %', urbanHighway, 'Véhicules sur une autoroute urbaine au crépuscule'],
];

const features = [
  [Clock3, 'Durée du trajet', 'Estimez votre temps de conduite et votre heure d’arrivée.'],
  [Route, 'Écart estimé', 'Comparez la prédiction au temps de référence OSRM.'],
  [CloudSun, 'Météo au départ', 'Consultez les conditions prévues à l’heure choisie.'],
  [Truck, 'Simulation', 'Suivez un véhicule simulé sur l’itinéraire.'],
  [Navigation, 'Suivi GPS', 'Consultez la dernière position partagée par un livreur.'],
  [MapPin, 'Couverture Maroc', 'Planifiez des trajets urbains et interurbains.'],
];

export function StepCard({ icon: Icon, title, description, preview, image, alt, step }) {
  return <article className="card home-step">
    <img className="step-photo" src={image} alt={alt} loading="lazy" decoding="async" />
    <div className="step-copy">
      <div className="step-preview" aria-hidden="true"><Icon size={17} /><span>{preview}</span></div>
      <h3>{step && <span className="home-step-number">{step}. </span>}{title}</h3><p>{description}</p>
    </div>
  </article>;
}

export function FeatureCard({ icon: Icon, title, description }) {
  return <article className="card home-feature">
    <span className="section-icon"><Icon size={19} aria-hidden="true" /></span>
    <h3>{title}</h3><p>{description}</p>
  </article>;
}

export default function Home({ navigate }) {
  return <main className="wasel-home">
    <section className="home-hero">
      <div className="home-hero-copy">
        <WaselLogo />
        <span className="home-kicker"><MapPin size={16} /> Trajets au Maroc</span>
        <h1>Anticiper. Planifier. Livrer.</h1>
        <p>Estimez votre heure d’arrivée, comparez votre temps de conduite à la référence et visualisez votre trajet.</p>
        <div className="home-actions">
          <button className="primary-button" onClick={() => navigate('plan')}>Commencer</button>
          <button className="home-secondary" onClick={() => navigate('simulation')}><Play size={17} /> Voir la simulation</button>
        </div>
      </div>
      <div className="home-hero-visual" role="img" aria-label="Illustration aérienne d’une route bordée d’arbres">
        <div className="home-route-preview" aria-hidden="true"><svg viewBox="0 0 240 120"><path d="M16 94 56 81 97 91 130 45 178 52 222 20" /><circle cx="16" cy="94" r="6" /><circle cx="222" cy="20" r="6" /></svg></div>
        <div className="hero-route"><Route size={20} /><span>Casablanca <span aria-hidden="true">→</span> Rabat<small>Exemple de trajet</small></span></div>
      </div>
    </section>

    <section className="home-section" aria-labelledby="how-title">
      <h2 id="how-title">Comment ça marche</h2>
      <ol className="home-steps">
        {steps.map(([icon, title, description, preview, image, alt], index) => <li key={title}><StepCard {...{ icon, title, description, preview, image, alt, step: index + 1 }} /></li>)}
      </ol>
    </section>

    <section className="home-section" aria-labelledby="example-title">
      <h2 id="example-title">Casablanca → Rabat</h2>
      <p className="home-section-note">Exemple illustratif pour un départ à 15 h 00.</p>
      <div className="home-example dashboard-kpis">
        <div className="metrics-grid">
          <KpiCard icon={Clock3} label="Temps de référence" value={68} format={formatDuration} />
          <KpiCard icon={Navigation} label="Durée estimée" value={70} format={formatDuration} className="featured-metric" />
          <KpiCard icon={Route} label="Écart estimé" value={2} format={formatDelay} suffix="min" />
          <KpiCard icon={Flag} label="Arrivée estimée" value={16 * 60 + 10} format={formatClock} />
        </div>
      </div>
    </section>

    <section className="home-section" aria-labelledby="features-title">
      <h2 id="features-title">Ce que vous pouvez faire</h2>
      <div className="home-features">
        {features.map(([icon, title, description]) => <FeatureCard key={title} {...{ icon, title, description }} />)}
      </div>
    </section>

    <section className="card home-sources">
      <h2>Sous le capot</h2>
      <p>OpenStreetMap fournit les données de la carte. OSRM calcule l’itinéraire et son temps de référence. Open-Meteo fournit les prévisions au départ.</p>
      <p>Wasel est un prototype éducatif. Son modèle a été entraîné sur des trajets simulés, et le véhicule de la démonstration suit une animation.</p>
    </section>
    <section className="home-cta">
      <h2>Prêt à préparer votre prochain trajet ?</h2>
      <button className="primary-button" onClick={() => navigate('plan')}>Planifier un trajet</button>
    </section>
    <footer className="page-footer">
      <span>Wasel · Prototype éducatif</span>
      <div><a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a><a href="https://project-osrm.org/">OSRM</a><a href="https://open-meteo.com/">Open-Meteo</a></div>
    </footer>
  </main>;
}
