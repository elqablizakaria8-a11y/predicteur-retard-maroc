import React from 'react';
import { createRoot } from 'react-dom/client';
import 'leaflet/dist/leaflet.css';
import './styles.css';
import App from './App.jsx';
import PublicDelivery from './PublicDelivery.jsx';

const publicRoute = window.location.pathname.match(/^\/(livreur|suivi)\/([^/]+)\/?$/);
const screen = publicRoute ? <PublicDelivery role={publicRoute[1]} token={publicRoute[2]} /> : <App />;

createRoot(document.getElementById('root')).render(<React.StrictMode>{screen}</React.StrictMode>);
