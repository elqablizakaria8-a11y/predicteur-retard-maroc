import QRCode from 'qrcode-terminal/vendor/QRCode/index.js';
import { useEffect, useMemo, useRef, useState } from 'react';

export const events = { created: 'Créée', connected: 'Livreur connecté', started: 'En route', near: 'Arrivée proche', delivered: 'Livrée' };
export const clockLabel = seconds => new Intl.DateTimeFormat('fr-MA', {
  timeZone: 'Africa/Casablanca', dateStyle: 'short', timeStyle: 'short',
}).format(seconds * 1000);

export async function deliveryRequest(path = '', { method = 'GET', token, data, signal } = {}) {
  const response = await fetch('/api/deliveries' + path, { method, cache: 'no-store',
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(90000)]) : AbortSignal.timeout(90000),
    headers: { ...(token && { Authorization: 'Bearer ' + token }), ...(data && { 'Content-Type': 'application/json' }) },
    body: data ? JSON.stringify(data) : undefined });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.error?.message || (typeof body?.detail === 'string' && body.detail) || 'Vérifiez les informations et réessayez.');
    error.status = response.status;
    throw error;
  }
  return body;
}

function ShareLink({ title, url, phone = '' }) {
  const [feedback, setFeedback] = useState('');
  const field = useRef(null);
  const qr = useMemo(() => {
    const code = new QRCode(-1, 0);
    code.addData(url);
    code.make();
    return code;
  }, [url]);
  async function copy() {
    try { await navigator.clipboard.writeText(url); setFeedback('Lien copié.'); }
    catch { field.current.select(); setFeedback('Sélectionnez Copier dans le menu du navigateur.'); }
  }
  const message = title + ' · ' + url;
  return <section className="card tracking-card">
    <h2>{title}</h2>
    <svg width="160" height="160" viewBox={`-4 -4 ${qr.moduleCount + 8} ${qr.moduleCount + 8}`}
      role="img" aria-label={'QR code · ' + title} shapeRendering="crispEdges" style={{background:'var(--surface)'}}>
      <path fill="var(--text)" d={qr.modules.map((row, y) => row.map((dark, x) => dark ? `M${x} ${y}h1v1h-1z` : '').join('')).join('')} />
    </svg>
    <input ref={field} aria-label={title} value={url} readOnly />
    <div className="delivery-actions"><button onClick={copy}>Copier</button>
      <a href={'https://wa.me/' + phone.replace(/\D/g, '') + '?text=' + encodeURIComponent(message)}
        rel="noreferrer" target="_blank">Envoyer par WhatsApp</a></div>
    {feedback && <p role="status">{feedback}</p>}
  </section>;
}

export default function Deliveries({ tripConfig, onExpired }) {
  const [list, setList] = useState(null), [form, setForm] = useState(false);
  const [receipt, setReceipt] = useState(null), [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    let timer;
    async function reload() {
      try { const result = await deliveryRequest('', { signal: ctrl.signal }); setList(result); setListError(''); }
      catch (failure) {
        if (ctrl.signal.aborted) return;
        if (failure.status === 401) { onExpired(); return; }
        setListError(failure.message);
      }
      if (!ctrl.signal.aborted) timer = setTimeout(reload, 15000);
    }
    reload();
    return () => { ctrl.abort(); clearTimeout(timer); };
  }, [version, onExpired]);

  async function create(event) {
    event.preventDefault();
    if (pending) return;
    const field = Array.from(event.currentTarget.elements).find(input => input.willValidate && !input.validity.valid);
    if (field) {
      const label = field.labels?.[0]?.textContent || 'Champ';
      setError(label + ' : ' + (field.validity.valueMissing ? 'ce champ est obligatoire.' : field.validationMessage));
      field.focus();
      return;
    }
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!/^\+?[\d ()-]+$/.test(values.phone.trim()) || !/^\d{7,15}$/.test(values.phone.replace(/\D/g, ''))) {
      setError('Téléphone du livreur : saisissez de 7 à 15 chiffres, par exemple +212612345678.');
      event.currentTarget.elements.phone.focus();
      return;
    }
    values.urban = values.urban === 'true';
    setPending(true); setError('');
    try {
      const result = await deliveryRequest('', { method: 'POST', data: values });
      setReceipt({ ...result, phone: values.phone }); setForm(false); setVersion(v => v + 1);
    } catch (failure) {
      if (failure.status === 401) onExpired();
      else setError(failure.name === 'TimeoutError' ? 'Le serveur met du temps à répondre. Vérifiez la liste des livraisons avant de réessayer.' : failure.message);
    } finally { setPending(false); }
  }
  return <div className="delivery-workspace">
    <header className="delivery-heading"><div><h1>Mes livraisons</h1><p>Retrouvez vos trajets et leur heure d’arrivée prévue.</p></div>
      {!form && <button className="primary-button" onClick={() => { setReceipt(null); setError(''); setForm(true); }}>Nouvelle livraison</button>}
    </header>
    {form && <form className="card tracking-card delivery-form" noValidate onSubmit={create}>
      <h2>Nouvelle livraison</h2>
      <datalist id="delivery-cities">{tripConfig?.cities.map(city => <option key={city} value={city} />)}</datalist>
      <label>Départ<input name="departure" list="delivery-cities" required placeholder="Casablanca" /></label>
      <label>Destination<input name="arrival" list="delivery-cities" required placeholder="Rabat" /></label>
      <label>Départ · heure du Maroc<input type="datetime-local" name="departure_time" defaultValue={tripConfig?.default_departure} min={tripConfig?.min_departure} max={tripConfig?.max_departure} required /></label>
      <label>Type de trajet<select name="urban"><option value="false">Interurbain</option><option value="true">Urbain</option></select></label>
      <label>Téléphone du livreur<input type="tel" name="phone" required placeholder="+212…" /></label>
      <label>E-mail du livreur (facultatif)<input type="email" name="driver_email" /></label>
      <label>E-mail du destinataire (facultatif)<input type="email" name="recipient_email" /></label>
      <p>{list?.email_enabled ? 'Les contacts renseignés recevront leur lien par e-mail.' : 'Envoi par e-mail indisponible. Partagez les liens par copie, QR code ou WhatsApp.'}</p>
      {error && <p role="alert">{error}</p>}
      {pending && <p role="status">Calcul du trajet et préparation des liens…</p>}
      <div className="delivery-actions"><button type="submit" className="primary-button" disabled={pending}>{pending ? 'Création en cours…' : 'Créer la livraison'}</button>
      <button type="button" disabled={pending} onClick={() => setForm(false)}>Annuler</button></div>
    </form>}
    {listError && <p role="alert">{listError}</p>}
    {receipt && <><h2>Livraison créée</h2><p>Conservez ces liens privés avant de quitter cette page.</p>
      {['localhost', '127.0.0.1'].includes(new URL(receipt.links.driver).hostname) &&
        <p role="status">Ces liens fonctionnent sur cet ordinateur. Pour un téléphone, configurez une adresse HTTPS publique puis créez une livraison depuis cette adresse.</p>}
      {receipt.mail.length > 0 && <p role="status">{receipt.mail.includes('failed') ? 'Certains e-mails n’ont pas pu être envoyés. Partagez les liens ci-dessous.' : 'E-mails transmis au service d’envoi.'}</p>}
      <div className="delivery-columns"><ShareLink title="Lien du livreur" url={receipt.links.driver} phone={receipt.phone} />
        <ShareLink title="Lien de suivi" url={receipt.links.viewer} /></div></>}
    {!list && !error && <p role="status">Chargement des livraisons…</p>}
    {list && !list.deliveries.length && !form && <section className="card tracking-card"><h2>Aucune livraison pour le moment</h2><p>Créez votre premier trajet pour inviter le livreur.</p></section>}
    {list?.deliveries.map(item => <article key={item.id} className="card delivery-row">
      <strong>{item.origin} → {item.destination}</strong><span className="delivery-chip">{item.expired && !item.events.delivered ? 'Lien expiré' : item.paused && !item.events.delivered ? 'Partage en pause' : events[Object.keys(events).filter(k => item.events[k]).at(-1)]}</span>
      <span>{item.events.delivered ? 'Arrivée' : 'Arrivée prévue'} · {clockLabel(item.eta)}</span>
    </article>)}
  </div>;
}
