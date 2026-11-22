import { MapPin } from 'lucide-react';

export default function PageBanner({ simulation }) {
  return <header className={`page-heading page-banner${simulation ? ' page-banner-simulation' : ''}`}>
    <div>
      <h1>{simulation ? 'Votre livraison prend la route.' : 'Vos trajets, mieux anticipés.'}</h1>
      <p>{simulation ? 'Explorez votre itinéraire avec une simulation de déplacement.' : 'Estimez votre temps de route et partez avec une longueur d’avance.'}</p>
    </div>
    <span className="region-chip"><MapPin size={15} aria-hidden="true" />Maroc</span>
  </header>;
}
