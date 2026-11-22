import { Check, ChevronDown, Pause, Play, RotateCcw } from 'lucide-react';

const speeds = [1, 30, 120, 600];

export default function SimulationBar({
  ready, loading, running, fraction, speed, onToggle, onReset, onSpeedChange,
  onOpenDelivery, remainingDistance, remainingDuration,
}) {
  const complete = fraction >= 1;
  const started = fraction > 0;
  const action = complete ? 'Rejouer' : running ? 'Pause' : started ? 'Reprendre' : 'Démarrer';
  const status = complete ? 'Arrivé' : running ? 'En route' : started ? 'En pause' : 'Prêt au départ';

  return (
    <section className="playback card" aria-labelledby="playback-title">
      <div className="playback-title">
        <span className="section-icon"><Play size={17} aria-hidden="true" /></span>
        <div>
          <h2 id="playback-title">Progression de la simulation</h2>
          <p>{ready ? status : 'Estimez un trajet pour lancer la simulation.'}</p>
        </div>
        {onOpenDelivery && <button className="text-button" onClick={onOpenDelivery}>Vue livraison</button>}
      </div>
      <div className="playback-controls">
        <button className="primary-button play-button" disabled={!ready || loading} onClick={onToggle}>
          {running ? <Pause size={17} /> : <Play size={17} />}{action}
        </button>
        <button className="reset-button" disabled={!ready || loading} onClick={onReset} aria-label="Réinitialiser la simulation">
          <RotateCcw size={18} />
        </button>
        <label className="speed-control">
          <span>Vitesse</span>
          <select value={speed} onChange={event => onSpeedChange(Number(event.target.value))} aria-label="Vitesse de simulation">
            {speeds.map(value => <option key={value} value={value}>×{value}</option>)}
          </select>
          <ChevronDown size={13} />
        </label>
      </div>
      <div className="simulation-timeline">
        <div className="simulation-milestones">
          <span>Départ</span><strong>{Math.round(fraction * 100)} %</strong>
          <span>{complete && <Check size={14} aria-hidden="true" />} Arrivée</span>
        </div>
        <progress value={fraction} max={1} aria-label="Progression du parcours simulé" />
      </div>
      {ready && <div className="remaining">
        <span><strong>{remainingDistance}</strong> restants</span>
        <span><strong>{remainingDuration}</strong> de trajet restant</span>
      </div>}
    </section>
  );
}
