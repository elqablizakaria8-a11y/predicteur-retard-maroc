import Deliveries from './Deliveries.jsx';
import TrackingSignIn from './TrackingSignIn.jsx';
import { useEffect, useCallback, useState } from 'react';
import './tracking.css';

const root = '/api/tracking';
async function trackingRequest(path, token, options = {}) {
  const response = await fetch(path.startsWith('/api/') ? path : root + path, {
    ...options,
    cache: 'no-store',
    headers: { ...(token && { Authorization: `Bearer ${token}` }), ...options.headers },
    signal: options.signal ?? AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = new Error(typeof body?.detail === 'string' ? body.detail : 'Le service GPS est indisponible.');
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function CreateDelivery({ tripConfig, resetToken, googleError, onSessionChange }) {
  const [config, setConfig] = useState(null);
  const expire = useCallback(() => {
    setConfig(previous => ({ ...previous, signed_in: false }));
    onSessionChange(false);
  }, [onSessionChange]);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState(googleError ? 'La connexion Google a échoué.' : '');
  const signedIn = config?.signed_in && !resetToken;

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const options = { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]) };
        const state = await trackingRequest('/api/auth/session', null, options);
        setConfig(state);
        onSessionChange(state.signed_in);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure.message);
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    }
    load();
    return () => controller.abort();
  }, [onSessionChange]);

  async function authenticate(mode, values, remember) {
    const paths = { login: '/session?remember=' + remember, setup: '/setup', forgot: '/forgot', reset: '/reset' };
    setPending(true);
    setError('');
    try {
      const data = await trackingRequest('/api/auth' + paths[mode], null, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
      });
      if (data?.signed_in) {
        setConfig({ ...config, signed_in: true, setup_available: false });
        onSessionChange(true);
      } else if (mode === 'reset') {
        setConfig({ ...config, signed_in: false });
        onSessionChange(false);
      }
      return true;
    } catch (failure) {
      setError(failure.message);
      return false;
    } finally {
      setPending(false);
    }
  }

  if (!signedIn) return <TrackingSignIn config={config} pending={pending} error={error}
    resetToken={resetToken} submit={authenticate} />;

  return <Deliveries tripConfig={tripConfig} onExpired={expire} />;
}

export default function LiveTracking({ tripConfig, hash, onSessionChange }) {
  const params = new URLSearchParams(hash.split('?')[1]);
  return <main className="tracking-page"><CreateDelivery tripConfig={tripConfig} resetToken={params.get('reset')}
    googleError={params.has('google')} onSessionChange={onSessionChange} /></main>;
}
