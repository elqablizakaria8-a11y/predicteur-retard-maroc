function RouteMark({ tile = '#0F4D3A', line = '#FFFFFF', node = '#7ED6A8' }) {
  return <svg className="wasel-mark" viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" focusable="false">
    <rect width="48" height="48" rx="12" fill={tile} />
    <path d="M10 15L17 33L24 22L31 33L38 15" fill="none" stroke={line} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="10" cy="15" r="3.6" fill={node} />
    <circle cx="38" cy="15" r="3.6" fill={node} />
  </svg>;
}

function Signature({ tone = '', mark = <RouteMark /> }) {
  return <span className={`wasel-logo ${tone}`} role="img" aria-label="Wasel — Delivery Intelligence">
    {mark}
    <span className="wasel-wordmark" aria-hidden="true">wasel<small>Delivery Intelligence</small></span>
  </span>;
}

export function WaselLogo() { return <Signature />; }
export function WaselIcon() { return <span role="img" aria-label="Wasel"><RouteMark /></span>; }
export function WaselLogoWhite() { return <Signature tone="wasel-logo-white" />; }
export function WaselLogoMonochrome() {
  return <Signature tone="wasel-logo-mono" mark={<RouteMark tile="currentColor" node="#FFFFFF" />} />;
}
