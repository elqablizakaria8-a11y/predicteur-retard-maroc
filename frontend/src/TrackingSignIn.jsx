import { useState } from 'react';
import { Eye, EyeOff, LoaderCircle, LockKeyhole } from 'lucide-react';

export default function TrackingSignIn({ config, pending, error, resetToken, submit }) {
  const [mode, setMode] = useState(resetToken ? 'reset' : 'login');
  const [visible, setVisible] = useState(false);
  const [notice, setNotice] = useState('');
  const changeMode = next => { setNotice(''); setVisible(false); setMode(next); };

  async function authenticate(event) {
    event.preventDefault();
    setNotice('');
    const form = new FormData(event.currentTarget);
    const email = form.get('email');
    const password = form.get('password');
    const completed = await submit(mode, { email, password, setup_key: form.get('setup_key'), token: resetToken },
      form.has('remember'));
    if (!completed) return;
    if (mode === 'forgot') setNotice('Si cette adresse correspond à un compte, un lien sera envoyé.');
    if (mode === 'reset') {
      window.location.hash = '/suivi';
      changeMode('login');
      setNotice('Le mot de passe a été modifié. Connectez-vous.');
    }
  }

  return <div className="tracking-login">
    <div className="tracking-login-form">
      <section className="card tracking-card tracking-setup" aria-labelledby="tracking-login-title">
        <span className="tracking-icon"><LockKeyhole size={24} aria-hidden="true" /></span>
        <h1 id="tracking-login-title">{{ login: 'Connexion au suivi GPS', setup: 'Configurer le compte client',
          forgot: 'Récupérer votre compte', reset: 'Modifier le mot de passe' }[mode]}</h1>
        <form key={mode} onSubmit={authenticate}>
          {mode === 'login' && <p>Accédez à la position de vos livreurs en temps réel.</p>}
          {mode !== 'reset' && <label>E-mail<input name="email" type="email" autoComplete="email"
            placeholder="nom@entreprise.com" required maxLength={254} /></label>}
          {mode !== 'forgot' && <label>Mot de passe
            <span className="tracking-password">
              <input name="password" type={visible ? 'text' : 'password'} required maxLength={256}
                minLength={mode === 'login' ? undefined : 12} placeholder="Votre mot de passe"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
              <button type="button" aria-label={visible ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button>
            </span>
          </label>}
          {mode === 'setup' && <label>Clé d’installation<input name="setup_key" type="password"
            autoComplete="off" required maxLength={256} /></label>}
          {mode === 'login' && <div className="tracking-login-options">
            <label><input name="remember" type="checkbox" /> Rester connecté</label>
            <button type="button" className="text-button" onClick={() => changeMode('forgot')}>Mot de passe oublié ?</button>
          </div>}
          {mode === 'forgot' && !config?.reset_available && <p>La récupération par e-mail est indisponible.</p>}
          <button className="primary-button" disabled={pending || !config || (mode === 'forgot' && !config.reset_available)}>
            {pending && <LoaderCircle className="spin" size={18} aria-hidden="true" />}
            {{ login: 'Se connecter', setup: 'Créer le compte', forgot: 'Envoyer le lien', reset: 'Enregistrer le mot de passe' }[mode]}
          </button>
        </form>
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {mode === 'login' && config?.google_available && <a className="tracking-google" href="/api/auth/google">Continuer avec Google</a>}
        {mode === 'login' && config?.setup_available && <div className="tracking-login-footer">
          Première configuration ? <button type="button" className="text-button" onClick={() => changeMode('setup')}>Utiliser la clé d’installation</button>
        </div>}
        {mode !== 'login' && <button type="button" className="text-button" onClick={() => changeMode('login')}>Revenir à la connexion</button>}
      </section>
    </div>
    <div className="tracking-login-visual">
      <div className="tracking-login-art" aria-hidden="true">
        <img src="/images/gps-login.webp" alt="" width="1200" height="1110" />
      </div>
      <div className="tracking-login-caption">
        <h2>Chaque livraison, en temps réel.</h2>
        <p>Position du livreur, retard estimé et arrivée prévue sur une seule carte.</p>
      </div>
    </div>
  </div>;
}
